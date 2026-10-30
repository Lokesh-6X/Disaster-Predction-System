"""FastAPI application: start-up/shut-down and top-level routes.

Start-up waits for the database (syncs kits, creates the admin, loads QC
history), then starts the MQTT subscriber and the kit watchdog as background
tasks. The scheduler is added in Phase 4.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from backend.app import __version__
from backend.app.db import Database
from backend.app.ingest.kit_status import KitStatusService
from backend.app.ingest.pipeline import IngestPipeline
from backend.app.mqtt.subscriber import MqttSubscriber
from backend.app.security import ensure_admin
from backend.app.settings import AppConfig, get_config
from backend.app.ws.hub import WebSocketHub

log = logging.getLogger(__name__)

MAX_DB_RETRY_S = 30


async def _prepare_database(
    config: AppConfig,
    database: Database,
    kit_status: KitStatusService,
    pipeline: IngestPipeline,
) -> None:
    delay = 1
    while True:
        try:
            await kit_status.sync_kits()
            await ensure_admin(database.session_factory, config.env)
            await pipeline.load_history()
            return
        except (SQLAlchemyError, OSError) as exc:
            log.error(
                "Database not ready (%s). Is PostgreSQL running and scripts\\init_db.ps1 run? "
                "Retrying in %d s",
                str(exc).splitlines()[0],
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_DB_RETRY_S)


async def _run_services(app: FastAPI) -> None:
    state = app.state
    await _prepare_database(state.config, state.database, state.kit_status, state.pipeline)
    async with asyncio.TaskGroup() as group:
        group.create_task(state.subscriber.run(), name="mqtt-subscriber")
        group.create_task(state.kit_status.run_watchdog(), name="kit-watchdog")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    log.info(
        "Starting backend v%s for site '%s' with %d enabled kit(s)",
        __version__,
        config.site.site.name,
        len(config.site.enabled_kits),
    )
    if config.site.normals.provisional:
        log.warning("Climate normals in site.yaml are provisional (open decision D8)")

    database = Database(config.env.database_url)
    hub = WebSocketHub()
    kit_status = KitStatusService(config.site, database.session_factory, hub)
    pipeline = IngestPipeline(config.site, database.session_factory, kit_status, hub)
    subscriber = MqttSubscriber(
        config.env, pipeline.handle_telemetry, kit_status.handle_status_message
    )

    app.state.config = config
    app.state.database = database
    app.state.hub = hub
    app.state.kit_status = kit_status
    app.state.pipeline = pipeline
    app.state.subscriber = subscriber

    services = asyncio.create_task(_run_services(app), name="services")
    try:
        yield
    finally:
        services.cancel()
        await asyncio.gather(services, return_exceptions=True)
        await database.dispose()
        log.info("Backend stopped")


app = FastAPI(
    title="Site Weather Hazard Prediction API",
    version=__version__,
    lifespan=lifespan,
)


@app.get("/api/health")
async def health() -> dict:
    state = app.state
    database_ok = await state.database.ping()
    mqtt_ok = state.subscriber.connected
    return {
        "status": "ok" if database_ok and mqtt_ok else "degraded",
        "version": __version__,
        "site": state.config.site.site.name,
        "components": {
            "database": "ok" if database_ok else "down",
            "mqtt": "connected" if mqtt_ok else "disconnected",
            "scheduler": "not_started",
        },
    }
