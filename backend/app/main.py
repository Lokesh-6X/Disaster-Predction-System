"""FastAPI application: start-up/shut-down and top-level routes.

Background tasks (MQTT subscriber, kit watchdog, scheduler) are added to the
lifespan in later phases.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app import __version__
from backend.app.settings import get_config

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    app.state.config = config
    log.info(
        "Starting backend v%s for site '%s' with %d enabled kit(s)",
        __version__,
        config.site.site.name,
        len(config.site.enabled_kits),
    )
    if config.site.normals.provisional:
        log.warning("Climate normals in site.yaml are provisional (open decision D8)")
    yield
    log.info("Backend stopped")


app = FastAPI(
    title="Site Weather Hazard Prediction API",
    version=__version__,
    lifespan=lifespan,
)


@app.get("/api/health")
async def health() -> dict:
    """Liveness check. Component health is filled in as components are added."""
    config = app.state.config
    return {
        "status": "ok",
        "version": __version__,
        "site": config.site.site.name,
        "components": {
            "mqtt": "not_started",
            "database": "not_connected",
            "scheduler": "not_started",
        },
    }
