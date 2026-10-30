"""Training dataset: raw readings → QC/fusion → grid → hourly → features + labels."""

from __future__ import annotations

import pandas as pd

from ml.core.aggregate import to_grid, to_hourly
from ml.core.batch import qc_and_fuse
from ml.core.features import build_features
from ml.core.labels import LABELS, make_labels
from ml.core.qc import QcLimits


def build_dataset(readings: pd.DataFrame, site) -> pd.DataFrame:
    """One row per prediction time with all features and the six labels.

    Rows are kept only when live inference would also run (same data-sufficiency
    rules): enough data in the last 24 h and at least one reading in the last hour.
    """
    checked = qc_and_fuse(
        readings, QcLimits.from_config(site.qc), site.qc.fusion_mismatch.model_dump()
    )
    grid = to_grid(checked, site.data_sufficiency.max_interp_gap_min)
    hourly = to_hourly(grid)
    features = build_features(hourly, site)
    labels = make_labels(grid, site, site.prediction.horizon_hours)

    data = features.join(labels, how="inner")
    observed_last_hour = hourly["n_observed"].set_axis(hourly.index + pd.Timedelta(hours=1))
    enough_recent = observed_last_hour.reindex(data.index).fillna(0) > 0
    enough_24h = data["coverage_24h"] >= 1 - site.data_sufficiency.max_missing_share_24h
    data = data[enough_recent & enough_24h]
    return data.dropna(subset=list(LABELS), how="all")
