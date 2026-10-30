"""Kits, online/offline history and data quality (FR-API-01, FR-UI-07)."""

import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from backend.app.api.deps import check_kit, require_admin, rounded
from backend.app.models import Kit, KitStatusLog, Reading
from ml.core.qc import INVALIDATING_RULES

router = APIRouter(prefix="/api", tags=["kits"], dependencies=[Depends(require_admin)])

DEFAULT_INTERVAL_S = 300
SLOTS_PER_DAY = 288  # 5-minute slots
BME_FIELDS = ("temp_bme_c", "hum_bme_pct", "pressure_hpa")
DHT_DRIFT_WARN_C = 1.0


def _interval_s(times: list[datetime]) -> float:
    """Typical sending interval (median gap), or the 5-min default."""
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)]
    gaps = [g for g in gaps if g > 0]
    return statistics.median(gaps) if len(gaps) >= 3 else DEFAULT_INTERVAL_S


@router.get("/kits")
async def kits(request: Request) -> dict:
    site = request.app.state.config.site
    async with request.app.state.database.session_factory() as session:
        stored = {k.kit_id: k for k in await session.scalars(select(Kit))}
        items = []
        for kit in site.kits:
            row = stored.get(kit.kit_id)
            recent = (
                await session.scalars(
                    select(Reading.ts)
                    .where(Reading.kit_id == kit.kit_id)
                    .order_by(Reading.ts.desc())
                    .limit(20)
                )
            ).all()
            items.append(
                {
                    "kit_id": kit.kit_id,
                    "description": kit.description,
                    "latitude": kit.latitude,
                    "longitude": kit.longitude,
                    "anemometer_height_m": kit.anemometer_height_m,
                    "notes": kit.notes,
                    "enabled": kit.enabled,
                    "status": row.status if row else "unknown",
                    "last_seen": row.last_seen if row else None,
                    "fw_version": row.fw_version if row else None,
                    "interval_s": round(_interval_s(sorted(recent))),
                    "telemetry_topic": f"weather/kit/{kit.kit_id}/telemetry",
                }
            )
    return {"items": items}


@router.get("/kits/{kit_id}/status-history")
async def status_history(request: Request, kit_id: str, days: int = Query(7, ge=1, le=31)) -> dict:
    """Status changes plus the share of 5-min slots with data, per local day."""
    check_kit(request, kit_id)
    site = request.app.state.config.site
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    async with request.app.state.database.session_factory() as session:
        events = (
            await session.scalars(
                select(KitStatusLog)
                .where(KitStatusLog.kit_id == kit_id, KitStatusLog.ts >= since)
                .order_by(KitStatusLog.ts)
            )
        ).all()
        times = (
            await session.scalars(
                select(Reading.ts).where(Reading.kit_id == kit_id, Reading.ts >= since)
            )
        ).all()

    tz = ZoneInfo(site.site.timezone)
    slots_by_day: dict[str, set] = {}
    for ts in times:
        local = ts.astimezone(tz)
        slot = (local.hour * 60 + local.minute) // 5
        slots_by_day.setdefault(local.date().isoformat(), set()).add(slot)
    local_now = now.astimezone(tz)
    today = local_now.date()
    slots_today = (local_now.hour * 60 + local_now.minute) // 5 + 1
    daily = []
    for back in range(days - 1, -1, -1):
        day = today - timedelta(days=back)
        expected = slots_today if back == 0 else SLOTS_PER_DAY
        observed = len(slots_by_day.get(day.isoformat(), ()))
        daily.append({"date": day.isoformat(), "share": round(min(1.0, observed / expected), 3)})
    total_expected = SLOTS_PER_DAY * (days - 1) + slots_today
    uptime = sum(len(v) for v in slots_by_day.values()) / total_expected
    return {
        "kit_id": kit_id,
        "days": days,
        "uptime_pct": round(min(100.0, uptime * 100), 1),
        "daily": daily,
        "events": [{"ts": e.ts, "status": e.status, "source": e.source} for e in events],
    }


@router.get("/quality")
async def quality(
    request: Request, kit_id: str = Query(...), hours: int = Query(24, ge=1, le=168)
) -> dict:
    """Data-quality summary and sensor health for the last ``hours``."""
    check_kit(request, kit_id)
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    async with request.app.state.database.session_factory() as session:
        rows = (
            await session.execute(
                select(
                    Reading.ts,
                    Reading.qc_flags,
                    Reading.fallback,
                    Reading.temp_bme_c,
                    Reading.temp_dht_c,
                    Reading.wind_speed_ms,
                )
                .where(Reading.kit_id == kit_id, Reading.ts >= since)
                .order_by(Reading.ts)
            )
        ).all()

    times = [r.ts for r in rows]
    interval = _interval_s(times)
    gaps = []
    boundaries = [since, *times, now]
    for a, b in zip(boundaries, boundaries[1:], strict=False):
        missing = (b - a).total_seconds()
        if missing > 2 * interval:
            gaps.append({"from": a, "to": b, "minutes": round(missing / 60)})

    rule_counts = Counter(f.split(":")[-1] for r in rows for f in r.qc_flags)
    flagged_fields = Counter(f.split(":")[0] for r in rows for f in r.qc_flags)
    fallback_minutes = sum(r.fallback for r in rows) * interval / 60

    latest = rows[-1] if rows else None
    bme_problems = sum(flagged_fields[f] for f in BME_FIELDS)
    if latest is not None and latest.temp_bme_c is None:
        bme = {"status": "fault", "detail": "no value in the latest reading"}
    elif bme_problems:
        bme = {"status": "warn", "detail": f"{bme_problems} flagged values"}
    else:
        bme = {"status": "ok", "detail": None}

    diffs = [
        abs(r.temp_bme_c - r.temp_dht_c)
        for r in rows
        if r.temp_bme_c is not None and r.temp_dht_c is not None
    ]
    drift = statistics.mean(diffs) if diffs else None
    if latest is not None and latest.temp_dht_c is None:
        dht = {"status": "fault", "detail": "no value in the latest reading", "drift_c": None}
    elif drift is not None and drift >= DHT_DRIFT_WARN_C:
        dht = {"status": "warn", "detail": f"drift {drift:.1f} °C", "drift_c": rounded(drift, 1)}
    else:
        dht = {"status": "ok", "detail": None, "drift_c": rounded(drift, 1)}

    wind_bad = sum(
        any(f == f"wind_speed_ms:{rule}" for f in r.qc_flags for rule in INVALIDATING_RULES)
        for r in rows
    )
    anemometer = (
        {"status": "warn", "detail": f"{wind_bad} flagged values"}
        if wind_bad
        else {"status": "ok", "detail": None}
    )

    return {
        "kit_id": kit_id,
        "hours": hours,
        "received": len(rows),
        "expected": round(hours * 3600 / interval),
        "interval_s": round(interval),
        "gaps": gaps,
        "flags": {
            rule: rule_counts.get(rule, 0)
            for rule in ("spike", "stuck", "out_of_range", "null", "bme_dht_mismatch", "ts_missing")
        },
        "fallback_minutes": round(fallback_minutes),
        "sensors": {
            "bme280": bme,
            "dht11": dht,
            "anemometer": anemometer,
            "rain_gauge": {"status": "not_fitted", "detail": None},
        },
    }
