"""Model registry: versioned model folders and the active pointer (FR-ML-05, design §9.7).

ml/models/
  active            text file with the active version, e.g. "v1"
  v1/
    wind_yellow.json ... heat_red.json   (XGBoost JSON format)
    metadata.json
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from xgboost import XGBClassifier

from ml.core.features import feature_names
from ml.core.labels import LABELS

MODELS_DIR = Path(__file__).resolve().parent / "models"
_VERSION = re.compile(r"^v(\d+)$")


class RegistryError(Exception):
    pass


@dataclass
class LoadedModels:
    version: str
    models: dict[str, XGBClassifier]
    metadata: dict


def versions(models_dir: Path = MODELS_DIR) -> list[str]:
    found = [p.name for p in models_dir.glob("v*") if p.is_dir() and _VERSION.match(p.name)]
    return sorted(found, key=lambda name: int(name[1:]))


def next_version(models_dir: Path = MODELS_DIR) -> str:
    existing = versions(models_dir)
    return f"v{int(existing[-1][1:]) + 1 if existing else 1}"


def save_version(
    models: dict[str, XGBClassifier], metadata: dict, models_dir: Path = MODELS_DIR
) -> str:
    version = next_version(models_dir)
    folder = models_dir / version
    folder.mkdir(parents=True)
    for label, model in models.items():
        model.save_model(folder / f"{label}.json")
    metadata = {"version": version, **metadata}
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2, default=str))
    return version


def activate(version: str, models_dir: Path = MODELS_DIR) -> None:
    if version not in versions(models_dir):
        raise RegistryError(f"model version '{version}' not found in {models_dir}")
    (models_dir / "active").write_text(version + "\n")


def active_version(models_dir: Path = MODELS_DIR) -> str | None:
    pointer = models_dir / "active"
    return pointer.read_text().strip() if pointer.is_file() else None


def read_metadata(version: str, models_dir: Path = MODELS_DIR) -> dict:
    path = models_dir / version / "metadata.json"
    if not path.is_file():
        raise RegistryError(f"model version '{version}' not found in {models_dir}")
    return json.loads(path.read_text())


def load_version(version: str, models_dir: Path = MODELS_DIR) -> LoadedModels:
    metadata = read_metadata(version, models_dir)
    if metadata.get("feature_list") != feature_names():
        raise RegistryError(
            f"model {version} was trained with a different feature list than this code"
        )
    models = {}
    for label in LABELS:
        model = XGBClassifier()
        model.load_model(models_dir / version / f"{label}.json")
        models[label] = model
    return LoadedModels(version=version, models=models, metadata=metadata)


def load_active(models_dir: Path = MODELS_DIR) -> LoadedModels:
    version = active_version(models_dir)
    if version is None:
        raise RegistryError("no active model — run: python -m ml.cli activate v1")
    return load_version(version, models_dir)
