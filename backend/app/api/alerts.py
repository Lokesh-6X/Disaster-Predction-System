"""Alert history with outcomes and summary stats (FR-API-01, FR-UI-06).

Outcome: once an alert's window has ended, the readings in that window are
checked with the same level rules as the training labels.
"""

import math
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from backend.app.api.deps import require_admin, rounded, utc
from backend.app.models import Alert, Prediction, Reading
from ml.core.labels import reached_level
from ml.core.levels import RANK
from ml.core.normals import DailyNormals

router = APIRouter(prefix="/api/alerts", tags=["alerts"], dependencies=[Depends(require_admin)])

MIN_OUTCOME_READINGS = 6
STATS_DAYS = 7


async def outcome(session, alert: Alert, run_at: datetime, site, now: datetime) -> dict:
    if now < alert.valid_until:
        return {"status": "pending", "window_end": alert.valid_until}
    rows = (
        await session.execute(
            select(Reading.temp_c, Reading.wind_speed_ms, Reading.qc_flags).where(
                Reading.kit_id == alert.kit_id,
                Reading.ts > run_at,
                Reading.ts <= alert.valid_until,
            )
        )
    ).all()
    winds = [
        r.wind_speed_ms
        for r in rows
        if r.wind_speed_ms is not None
        and not any(f.startswith("wind_speed_ms:") for f in r.qc_flags)
    ]
    temps = [r.temp_c for r in rows if r.temp_c is not None]
    values = winds if alert.hazard == "wind" else temps
    if len(values) < MIN_OUTCOME_READINGS:
        return {"status": "unknown", "window_end": alert.valid_until}

    peak_kmh = max(winds) * 3.6 if winds else math.nan
    tmax = max(temps) if temps else math.nan
    doy = run_at.astimezone(ZoneInfo(site.site.timezone)).timetuple().tm_yday
    departure = tmax - float(DailyNormals(site.normals).tmax_for(doy))
    observed = reached_level(alert.hazard, peak_kmh, tmax, departure, site)
    happened = RANK[observed] >= RANK[alert.level]
    result = {
        "status": "happened" if happened else "did_not_happen",
        "observed_level": observed,
        "window_end": alert.valid_until,
    }
    if alert.hazard == "wind":
        result["peak_wind_kmh"] = rounded(peak_kmh, 0)
    else:
        result["tmax_c"] = rounded(tmax, 1)
    return result


def alert_dict(alert: Alert, run_at: datetime, result: dict) -> dict:
    return {
        "id": alert.id,
        "kit_id": alert.kit_id,
        "hazard": alert.hazard,
        "level": alert.level,
        "probability": rounded(alert.probability, 3),
        "run_at": run_at,
        "valid_until": alert.valid_until,
        "email_status": alert.email_status,
        "error": alert.error,
        "created_at": alert.created_at,
        "sent_at": alert.sent_at,
        "outcome": result,
    }


@router.get("")
async def list_alerts(
    request: Request,
    hazard: str | None = Query(None, pattern="^(wind|heat)$"),
    level: str | None = Query(None, pattern="^(yellow|orange|red)$"),
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    site = request.app.state.config.site
    now = datetime.now(UTC)
    filters = []
    if hazard:
        filters.append(Alert.hazard == hazard)
    if level:
        filters.append(Alert.level == level)
    if start:
        filters.append(Alert.created_at >= utc(start))
    if end:
        filters.append(Alert.created_at <= utc(end))

    async with request.app.state.database.session_factory() as session:
        total = await session.scalar(select(func.count()).select_from(Alert).where(*filters))
        rows = (
            await session.execute(
                select(Alert, Prediction.run_at)
                .join(Prediction, Prediction.id == Alert.prediction_id)
                .where(*filters)
                .order_by(Alert.created_at.desc(), Alert.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items = [
            alert_dict(alert, run_at, await outcome(session, alert, run_at, site, now))
            for alert, run_at in rows
        ]

        recent = (
            await session.execute(
                select(Alert, Prediction.run_at)
                .join(Prediction, Prediction.id == Alert.prediction_id)
                .where(Alert.created_at >= now - timedelta(days=STATS_DAYS))
            )
        ).all()
        emailed = [(a, r) for a, r in recent if a.email_status == "sent"]
        checked = [await outcome(session, a, r, site, now) for a, r in emailed]

    decided = [o for o in checked if o["status"] in ("happened", "did_not_happen")]
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": max(1, math.ceil(total / page_size)),
        "stats": {
            "days": STATS_DAYS,
            "raised": len(recent),
            "emailed": len(emailed),
            "confirmed": sum(o["status"] == "happened" for o in decided),
            "evaluated": len(decided),
        },
    }
