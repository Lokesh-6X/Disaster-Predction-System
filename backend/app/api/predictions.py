"""Prediction routes.

``POST /api/predictions/run`` triggers a prediction run now (for testing). It is
open in Phase 4 and protected by the admin login in Phase 5.
"""

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.post("/run")
async def run_now(request: Request) -> dict:
    results = await request.app.state.runner.run()
    return {"count": len(results), "items": [p.to_message() for p in results]}
