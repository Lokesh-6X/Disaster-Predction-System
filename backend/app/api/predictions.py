"""Predictions: latest, history and manual run (FR-API-01)."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from backend.app.api.deps import check_kit, require_admin, time_range
from backend.app.models import Prediction

router = APIRouter(
    prefix="/api/predictions", tags=["predictions"], dependencies=[Depends(require_admin)]
)

HAZARDS = ("wind", "heat")


def prediction_dict(p: Prediction) -> dict:
    probabilities = (
        None if p.p_yellow is None else {"yellow": p.p_yellow, "orange": p.p_orange, "red": p.p_red}
    )
    return {
        "id": p.id,
        "kit_id": p.kit_id,
        "run_at": p.run_at,
        "hazard": p.hazard,
        "status": p.status,
        "level": p.level,
        "p": probabilities,
        "valid_until": p.valid_until,
        "model_version": p.model_version,
        "fallback_used": p.fallback_used,
        "context": p.context,
    }


@router.get("/latest")
async def latest(request: Request, kit_id: str = Query(...)) -> dict:
    check_kit(request, kit_id)
    items = []
    async with request.app.state.database.session_factory() as session:
        for hazard in HAZARDS:
            row = await session.scalar(
                select(Prediction)
                .where(Prediction.kit_id == kit_id, Prediction.hazard == hazard)
                .order_by(Prediction.run_at.desc())
                .limit(1)
            )
            if row is not None:
                items.append(prediction_dict(row))
    run_at = max((item["run_at"] for item in items), default=None)
    return {"kit_id": kit_id, "run_at": run_at, "items": items}


@router.get("")
async def history(
    request: Request,
    kit_id: str = Query(...),
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
) -> dict:
    check_kit(request, kit_id)
    start, end = time_range(start, end, timedelta(hours=24), timedelta(days=92))
    async with request.app.state.database.session_factory() as session:
        rows = await session.scalars(
            select(Prediction)
            .where(
                Prediction.kit_id == kit_id, Prediction.run_at >= start, Prediction.run_at <= end
            )
            .order_by(Prediction.run_at, Prediction.hazard)
        )
        items = [prediction_dict(p) for p in rows]
    return {"kit_id": kit_id, "from": start, "to": end, "items": items}


@router.post("/run")
async def run_now(request: Request) -> dict:
    """Predict for the current hour now (testing)."""
    results = await request.app.state.runner.run()
    return {"count": len(results), "items": [p.to_message() for p in results]}
