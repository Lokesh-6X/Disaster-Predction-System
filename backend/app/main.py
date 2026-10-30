"""FastAPI application: start-up/shut-down and top-level routes.

Start-up loads the active model and starts the hourly prediction scheduler,
then waits for the database (syncs kits, creates the admin, loads QC history)
and starts the MQTT subscriber and the kit watchdog as background tasks.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from backend.app import __version__
from backend.app.alerts.emailer import Emailer
from backend.app.alerts.engine import AlertEngine
from backend.app.api import predictions
from backend.app.db import Database
from backend.app.inference.model_store import ModelStore
from backend.app.inference.runner import InferenceRunner
from backend.app.inference.scheduler import PredictionScheduler
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
    model_store = ModelStore()
    model_store.load()
    alert_engine = AlertEngine(
        config.site,
        config.env,
        database.session_factory,
        hub,
        Emailer(config.env),
        is_synthetic_model=lambda: bool(
            model_store.loaded and model_store.loaded.metadata.get("data_source") == "synthetic"
        ),
    )
    runner = InferenceRunner(config.site, database.session_factory, model_store, hub, alert_engine)
    scheduler = PredictionScheduler(config.site, runner)

    app.state.config = config
    app.state.database = database
    app.state.hub = hub
    app.state.kit_status = kit_status
    app.state.pipeline = pipeline
    app.state.subscriber = subscriber
    app.state.model_store = model_store
    app.state.runner = runner
    app.state.scheduler = scheduler

    scheduler.start()
    services = asyncio.create_task(_run_services(app), name="services")
    try:
        yield
    finally:
        scheduler.shutdown()
        services.cancel()
        await asyncio.gather(services, return_exceptions=True)
        await database.dispose()
        log.info("Backend stopped")


app = FastAPI(
    title="Site Weather Hazard Prediction API",
    version=__version__,
    lifespan=lifespan,
)
app.include_router(predictions.router)


@app.get("/api/health")
async def health() -> dict:
    state = app.state
    database_ok = await state.database.ping()
    mqtt_ok = state.subscriber.connected
    scheduler_ok = state.scheduler.running
    model = state.model_store.version
    healthy = database_ok and mqtt_ok and scheduler_ok and model is not None
    return {
        "status": "ok" if healthy else "degraded",
        "version": __version__,
        "site": state.config.site.site.name,
        "components": {
            "database": "ok" if database_ok else "down",
            "mqtt": "connected" if mqtt_ok else "disconnected",
            "scheduler": "running" if scheduler_ok else "stopped",
            "model": model or "missing",
        },
        "next_prediction": state.scheduler.next_run_time,
        "last_prediction_run": state.runner.last_run,
    }
