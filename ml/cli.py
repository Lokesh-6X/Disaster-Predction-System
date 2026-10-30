"""ML pipeline commands (design §9.1). Run from the project root:

.venv\\Scripts\\python.exe -m ml.cli generate        synthetic dataset (config/synthetic.yaml)
.venv\\Scripts\\python.exe -m ml.cli build           QC → hourly → features + labels
.venv\\Scripts\\python.exe -m ml.cli train           train 6 models, evaluate, save as v{N}
.venv\\Scripts\\python.exe -m ml.cli evaluate [vN]   show a version's metrics (default: active)
.venv\\Scripts\\python.exe -m ml.cli activate vN     use version vN for live predictions
.venv\\Scripts\\python.exe -m ml.cli all             generate, build, train and activate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from backend.app.settings import PROJECT_ROOT, ConfigError, load_site_config, load_synthetic_config
from ml import registry
from ml.core.features import feature_names
from ml.core.labels import LABELS
from ml.dataset import build_dataset
from ml.evaluate import NOTE, summary_table, top_features_text
from ml.synthetic import generator
from ml.train import TrainingError, train_models

LABEL_DEFINITIONS = {
    "wind": "peak reported wind speed (km/h) in the next horizon ≥ level threshold",
    "heat": "max temperature in the next horizon ≥ abs threshold and departure from the normal "
    "daily max ≥ level departure, or ≥ red_abs_c (cumulative levels)",
}


def _configs():
    site = load_site_config()
    return site, load_synthetic_config(site=site)


def _dataset_path(syn) -> Path:
    output = syn.output_path
    return output.parent.parent / "datasets" / f"{output.stem}_dataset.parquet"


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def cmd_generate(args) -> None:
    site, syn = _configs()
    started = time.perf_counter()
    result = generator.generate(site, syn)
    meta = generator.save(result, syn.output_path, site, syn)
    print(
        f"Synthetic dataset: {_relative(syn.output_path)}  ({meta['rows']:,} readings, "
        f"{time.perf_counter() - started:.1f} s)"
    )
    print(f"  period {meta['start']} → {meta['end']}")
    print(
        f"  hazard hours (Yellow+): {meta['hazard_shares']['hazard_any']:.1%}  "
        f"(target {syn.target_hazard_hour_share[0]:.0%}–{syn.target_hazard_hour_share[1]:.0%})"
    )
    print(f"  positive hours per label: {meta['hazard_shares']['positive_hours']}")
    print(f"  events: {meta['events']}   faults: {meta['faults']}")


def cmd_build(args) -> None:
    site, syn = _configs()
    source = Path(args.input) if args.input else syn.output_path
    if not source.is_file():
        sys.exit(f"{_relative(source)} not found — run: python -m ml.cli generate")
    started = time.perf_counter()
    readings = pd.read_parquet(source)
    data = build_dataset(readings, site)
    target = _dataset_path(syn)
    target.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(target)
    print(
        f"Dataset: {_relative(target)}  ({len(data):,} hourly rows, "
        f"{len(feature_names())} features, {time.perf_counter() - started:.1f} s)"
    )
    print("  positive rows: " + ", ".join(f"{label}={int(data[label].sum())}" for label in LABELS))


def cmd_train(args) -> None:
    site, syn = _configs()
    source = Path(args.dataset) if args.dataset else _dataset_path(syn)
    if not source.is_file():
        sys.exit(f"{_relative(source)} not found — run: python -m ml.cli build")
    data = pd.read_parquet(source)
    started = time.perf_counter()
    try:
        result = train_models(data, syn.seed)
    except TrainingError as exc:
        sys.exit(f"Training failed: {exc}")

    synthetic_meta_path = syn.output_path.with_suffix(".meta.json")
    metadata = {
        "created_at": datetime.now(UTC).isoformat(),
        "data_source": "synthetic",
        "dataset": _relative(source),
        "dataset_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "synthetic": json.loads(synthetic_meta_path.read_text())
        if synthetic_meta_path.is_file()
        else None,
        "feature_list": feature_names(),
        "labels": list(LABELS),
        "label_definitions": LABEL_DEFINITIONS,
        "config": {
            "hazards": site.hazards.model_dump(),
            "heat_abs_threshold_c": site.heat_abs_threshold_c,
            "prediction": site.prediction.model_dump(),
            "data_sufficiency": site.data_sufficiency.model_dump(),
            "normals_source": site.normals.source,
        },
        "training": {
            "model": "xgboost.XGBClassifier (default hyper-parameters)",
            "split": "random stratified 80/20",
            "seed": syn.seed,
            "rows": result.rows,
        },
        "metrics": result.metrics,
        "note": NOTE,
    }
    version = registry.save_version(result.models, metadata)
    print(f"Trained 6 models in {time.perf_counter() - started:.1f} s → ml/models/{version}\n")
    print(summary_table(result.metrics))
    if args.activate:
        registry.activate(version)
        print(f"\nActive model: {version}")
    else:
        print(f"\nTo use it: python -m ml.cli activate {version}")


def cmd_evaluate(args) -> None:
    version = args.version or registry.active_version()
    if version is None:
        sys.exit("No version given and no active model.")
    metadata = registry.read_metadata(version)
    active = " (active)" if version == registry.active_version() else ""
    print(f"Model {version}{active}, trained {metadata['created_at']} on {metadata['dataset']}\n")
    print(summary_table(metadata["metrics"]))
    print("\nTop features (by gain):")
    print(top_features_text(metadata["metrics"]))


def cmd_activate(args) -> None:
    registry.activate(args.version)
    print(f"Active model: {args.version}")


def cmd_all(args) -> None:
    cmd_generate(args)
    print()
    args.input = None
    cmd_build(args)
    print()
    args.dataset = None
    args.activate = True
    cmd_train(args)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m ml.cli",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("generate", help="create the synthetic dataset")
    build = commands.add_parser("build", help="build features and labels")
    build.add_argument("--input", help="readings Parquet file (default: synthetic output)")
    train = commands.add_parser("train", help="train, evaluate and save a model version")
    train.add_argument("--dataset", help="dataset Parquet file (default: built dataset)")
    train.add_argument("--activate", action="store_true", help="make the new version active")
    evaluate = commands.add_parser("evaluate", help="show metrics of a model version")
    evaluate.add_argument("version", nargs="?")
    activate = commands.add_parser("activate", help="set the active model version")
    activate.add_argument("version")
    commands.add_parser("all", help="generate, build, train and activate")

    args = parser.parse_args(argv)
    handlers = {
        "generate": cmd_generate,
        "build": cmd_build,
        "train": cmd_train,
        "evaluate": cmd_evaluate,
        "activate": cmd_activate,
        "all": cmd_all,
    }
    try:
        handlers[args.command](args)
    except (ConfigError, registry.RegistryError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
