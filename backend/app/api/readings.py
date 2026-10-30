"""Readings: latest value, chart series and CSV export (FR-API-01, design §13.2)."""

import csv
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, literal, literal_column, select

from backend.app.api.deps import check_kit, require_admin, rounded, time_range
from backend.app.models import Prediction, Reading
from ml.core.features import dewpoint_c

router = APIRouter(prefix="/api/readings", tags=["readings"], dependencies=[Depends(require_admin)])

RAW_LIMIT = timedelta(days=7)  # longer ranges are returned as hourly averages
MAX_RANGE = timedelta(days=92)
TREND_LOOKBACK = timedelta(minutes=30)
TREND_STEP = {"temp_c": 0.2, "hum_pct": 1.0, "pressure_hpa": 0.2, "wind_speed_ms": 0.5}
VALUE_FIELDS = (
    "temp_c",
    "hum_pct",
    "temp_bme_c",
    "hum_bme_pct",
    "temp_dht_c",
    "hum_dht_pct",
    "pressure_hpa",
    "wind_speed_ms",
)


def reading_dict(row: Reading) -> dict:
    return {
        "kit_id": row.kit_id,
        "ts": row.ts,
        "ts_source": row.ts_source,
        **{name: rounded(getattr(row, name)) for name in VALUE_FIELDS},
        "wind_gust_ms": rounded(row.wind_gust_ms),
        "rain_mm": rounded(row.rain_mm),
        "fallback": row.fallback,
        "qc_flags": list(row.qc_flags),
        "fw_version": row.fw_version,
    }


def _trend(now: float | None, before: float | None, step: float) -> str | None:
    if now is None or before is None:
        return None
    if now - before > step:
        return "up"
    if before - now > step:
        return "down"
    return "steady"


@router.get("/latest")
async def latest(request: Request, kit_id: str = Query(...)) -> dict:
    check_kit(request, kit_id)

    async def at_or_before(session, ts=None):
        query = select(Reading).where(Reading.kit_id == kit_id)
        if ts is not None:
            query = query.where(Reading.ts <= ts)
        return await session.scalar(query.order_by(Reading.ts.desc()).limit(1))

    async with request.app.state.database.session_factory() as session:
        row = await at_or_before(session)
        if row is None:
            return {"kit_id": kit_id, "reading": None}
        earlier = await at_or_before(session, row.ts - TREND_LOOKBACK)
        three_hours = await at_or_before(session, row.ts - timedelta(hours=3))

    result = reading_dict(row)
    result["trend"] = {
        name: _trend(getattr(row, name), getattr(earlier, name, None), step)
        for name, step in TREND_STEP.items()
    }
    result["dewpoint_c"] = (
        rounded(dewpoint_c(row.temp_c, row.hum_pct), 1)
        if row.temp_c is not None and row.hum_pct is not None
        else None
    )
    result["pressure_change_3h"] = (
        rounded(row.pressure_hpa - three_hours.pressure_hpa, 1)
        if three_hours is not None and None not in (row.pressure_hpa, three_hours.pressure_hpa)
        else None
    )
    return {"kit_id": kit_id, "reading": result}


def _hour_origin(timezone: str) -> datetime:
    """Origin for hourly buckets aligned to the site's clock hours."""
    return datetime(2000, 1, 1, tzinfo=ZoneInfo(timezone))


@router.get("")
async def series(
    request: Request,
    kit_id: str = Query(...),
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
) -> dict:
    """Readings in a range: raw points up to 7 days, hourly averages beyond."""
    check_kit(request, kit_id)
    start, end = time_range(start, end, timedelta(hours=24), MAX_RANGE)
    in_range = (Reading.kit_id == kit_id, Reading.ts >= start, Reading.ts <= end)
    async with request.app.state.database.session_factory() as session:
        if end - start <= RAW_LIMIT:
            rows = await session.execute(
                select(
                    Reading.ts,
                    *(getattr(Reading, name) for name in VALUE_FIELDS),
                    Reading.wind_speed_ms.label("wind_max_ms"),
                    (func.cardinality(Reading.qc_flags) > 0).label("flagged"),
                    Reading.fallback,
                )
                .where(*in_range)
                .order_by(Reading.ts)
            )
            resolution = "raw"
        else:
            bucket = func.date_bin(
                literal_column("interval '1 hour'"),
                Reading.ts,
                literal(_hour_origin(request.app.state.config.site.site.timezone)),
            ).label("ts")
            rows = await session.execute(
                select(
                    bucket,
                    *(func.avg(getattr(Reading, name)).label(name) for name in VALUE_FIELDS),
                    func.max(Reading.wind_speed_ms).label("wind_max_ms"),
                    func.bool_or(func.cardinality(Reading.qc_flags) > 0).label("flagged"),
                    func.bool_or(Reading.fallback).label("fallback"),
                )
                .where(*in_range)
                .group_by(bucket)
                .order_by(bucket)
            )
            resolution = "hourly"
    points = [
        {
            "ts": row.ts,
            **{name: rounded(getattr(row, name)) for name in VALUE_FIELDS},
            "wind_max_ms": rounded(row.wind_max_ms),
            "flagged": bool(row.flagged),
            "fallback": bool(row.fallback),
        }
        for row in rows
    ]
    return {"kit_id": kit_id, "from": start, "to": end, "resolution": resolution, "points": points}


CSV_COLUMNS = [
    "ts_utc",
    "ts_local",
    "temp_c",
    "hum_pct",
    "temp_bme_c",
    "hum_bme_pct",
    "temp_dht_c",
    "hum_dht_pct",
    "pressure_hpa",
    "wind_speed_ms",
    "wind_gust_ms",
    "rain_mm",
    "fallback",
    "qc_flags",
    "wind_level",
    "wind_p_yellow",
    "wind_p_orange",
    "wind_p_red",
    "heat_level",
    "heat_p_yellow",
    "heat_p_orange",
    "heat_p_red",
]


@router.get("/export.csv")
async def export_csv(
    request: Request,
    kit_id: str = Query(...),
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
) -> StreamingResponse:
    """Readings with the prediction of the hour they fall in (FR-UI-05)."""
    check_kit(request, kit_id)
    start, end = time_range(start, end, timedelta(days=7), MAX_RANGE)
    tz = ZoneInfo(request.app.state.config.site.site.timezone)
    async with request.app.state.database.session_factory() as session:
        readings = (
            await session.scalars(
                select(Reading)
                .where(Reading.kit_id == kit_id, Reading.ts >= start, Reading.ts <= end)
                .order_by(Reading.ts)
            )
        ).all()
        predictions = (
            await session.scalars(
                select(Prediction).where(
                    Prediction.kit_id == kit_id,
                    Prediction.run_at >= start - timedelta(hours=1),
                    Prediction.run_at <= end,
                )
            )
        ).all()
    by_hour = {(p.run_at, p.hazard): p for p in predictions}

    def hour_of(ts: datetime) -> datetime:
        local = ts.astimezone(tz).replace(minute=0, second=0, microsecond=0)
        return local.astimezone(ts.tzinfo)

    def rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(CSV_COLUMNS)
        for r in readings:
            hour = hour_of(r.ts)
            row = [
                r.ts.isoformat(),
                r.ts.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S"),
                *(rounded(getattr(r, name)) for name in CSV_COLUMNS[2:12]),
                int(r.fallback),
                ";".join(r.qc_flags),
            ]
            for hazard in ("wind", "heat"):
                p = by_hour.get((hour, hazard))
                row += [p.level, p.p_yellow, p.p_orange, p.p_red] if p else ["", "", "", ""]
            writer.writerow(row)
            if buffer.tell() > 64_000:
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate()
        yield buffer.getvalue()

    filename = f"{kit_id}_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    return StreamingResponse(
        rows(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
