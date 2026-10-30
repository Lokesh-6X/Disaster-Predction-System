"""Logging to the console and a rotating file, logs/backend.log (NFR-06)."""

import logging.config

from backend.app.settings import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"


def setup_logging(level: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {"format": "%(asctime)s %(levelname)-7s %(name)s: %(message)s"}
            },
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "standard"},
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "standard",
                    "filename": str(LOG_DIR / "backend.log"),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 5,
                    "encoding": "utf-8",
                },
            },
            "root": {"level": level, "handlers": ["console", "file"]},
            # Uvicorn's own loggers pass their records to the root handlers.
            "loggers": {
                "uvicorn": {"level": level, "handlers": [], "propagate": True},
                "uvicorn.error": {"level": level, "handlers": [], "propagate": True},
                "uvicorn.access": {"level": "WARNING", "handlers": [], "propagate": True},
            },
        }
    )
