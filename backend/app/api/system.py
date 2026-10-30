"""System status and the active (read-only) settings (FR-API-01, FR-UI-07)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from backend.app import __version__
from backend.app.api.deps import require_admin
from backend.app.models import Alert

router = APIRouter(prefix="/api", tags=["system"], dependencies=[Depends(require_admin)])


@router.get("/system")
async def system(request: Request) -> dict:
    state = request.app.state
    site = state.config.site
    env = state.config.env
    loaded = state.model_store.loaded

    async with state.database.session_factory() as session:
        last_sent = await session.scalar(
            select(Alert.sent_at).where(Alert.email_status == "sent").order_by(Alert.id.desc())
        )
        last_failed = (
            await session.execute(
                select(Alert.created_at, Alert.error)
                .where(Alert.email_status == "failed")
                .order_by(Alert.id.desc())
                .limit(1)
            )
        ).first()

    heat = site.hazards.heat
    return {
        "version": __version__,
        "site": {
            "name": site.site.name,
            "latitude": site.site.latitude,
            "longitude": site.site.longitude,
            "elevation_m": site.site.elevation_m,
            "timezone": site.site.timezone,
            "coastal": site.site.coastal,
        },
        "model": {
            "version": loaded.version if loaded else None,
            "created_at": loaded.metadata.get("created_at") if loaded else None,
            "data_source": loaded.metadata.get("data_source") if loaded else None,
            "error": state.model_store.error,
        },
        "scheduler": {
            "running": state.scheduler.running,
            "next_run": state.scheduler.next_run_time,
            "last_run": state.runner.last_run,
        },
        "components": {
            "database": "ok" if await state.database.ping() else "down",
            "mqtt": "connected" if state.subscriber.connected else "disconnected",
            "email": {
                "enabled": site.alerts.enabled,
                "host": env.smtp_host,
                "recipient": env.admin_email,
                "last_sent_at": last_sent,
                "last_failed_at": last_failed.created_at if last_failed else None,
                "last_error": last_failed.error if last_failed else None,
            },
        },
        "settings": {
            "horizon_hours": site.prediction.horizon_hours,
            "show_level_cutoff": site.prediction.show_level_cutoff,
            "wind_kmh": site.hazards.wind.levels.model_dump(),
            "heat": {
                "abs_threshold_c": site.heat_abs_threshold_c,
                "departure_c": heat.departure_c.model_dump(),
                "red_abs_c": heat.red_abs_c,
            },
            "rain_enabled": site.hazards.rain.enabled,
            "alert_levels": site.alerts.levels,
            "cooldown_hours": site.alerts.cooldown_hours,
            "offline_after_min": site.kit_status.offline_after_min,
            "fusion_mismatch": site.qc.fusion_mismatch.model_dump(),
            "data_sufficiency": site.data_sufficiency.model_dump(),
        },
    }
