"""Holds the active model version for live predictions (FR-ML-05, design §10)."""

import logging
from pathlib import Path

from ml.registry import MODELS_DIR, LoadedModels, RegistryError, load_active

log = logging.getLogger(__name__)


class ModelStore:
    def __init__(self, models_dir: Path = MODELS_DIR) -> None:
        self._models_dir = models_dir
        self.loaded: LoadedModels | None = None
        self.error: str | None = None

    def load(self) -> None:
        """Load the active version; on failure predictions report insufficient data."""
        try:
            self.loaded = load_active(self._models_dir)
            self.error = None
            source = self.loaded.metadata.get("data_source", "unknown")
            log.info("Loaded model %s (trained on %s data)", self.loaded.version, source)
        except RegistryError as exc:
            self.loaded = None
            self.error = str(exc)
            log.error("No usable model: %s", exc)

    @property
    def version(self) -> str | None:
        return self.loaded.version if self.loaded else None
