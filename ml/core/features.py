"""Model features from hourly aggregates (FR-ML-02, design §9.4).

Rows are indexed by prediction time *t* (UTC hour boundary) and use only the
hours ending at or before *t*, so there is no look-ahead. Training and live
inference both call :func:`build_features`.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ml.core.aggregate import SLOTS_PER_HOUR
from ml.core.normals import DailyNormals

LAGS = (1, 2, 3, 6, 12, 24)
ROLLING = (6, 12, 24)
TENDENCIES = (1, 3)
SERIES = ("temp_mean", "hum_mean", "pressure_mean", "wind_max")
CURRENT = (
    "temp_mean",
    "temp_max",
    "temp_min",
    "hum_mean",
    "pressure_mean",
    "wind_mean",
    "wind_max",
)


def dewpoint_c(temp_c, rh_pct):
    """Magnus formula."""
    rh = np.clip(rh_pct, 1, 100)
    gamma = np.log(rh / 100) + 17.625 * temp_c / (243.04 + temp_c)
    return 243.04 * gamma / (17.625 - gamma)


def feature_names() -> list[str]:
    names = list(CURRENT) + ["dewpoint", "tmax_normal", "departure"]
    names += [f"{s}_lag{k}" for s in SERIES for k in LAGS]
    names += [f"{s}_chg{k}" for s in SERIES for k in TENDENCIES]
    names += [
        f"{s}_{stat}{w}" for s in SERIES for w in ROLLING for stat in ("mean", "min", "max", "std")
    ]
    names += ["hour_sin", "hour_cos", "doy_sin", "doy_cos", "coverage_24h"]
    return names


def build_features(hourly: pd.DataFrame, site) -> pd.DataFrame:
    """Feature rows for every prediction time covered by ``hourly``.

    ``hourly`` comes from :func:`ml.core.aggregate.to_hourly` (complete hourly
    index of hour starts). The row for *t* describes the hour [t − 1 h, t).
    """
    h = hourly.copy()
    h.index = h.index + pd.Timedelta(hours=1)  # hour start → prediction time t
    h.index.name = "t"

    local = h.index.tz_convert(ZoneInfo(site.site.timezone))
    # The current hour started one hour before t
    hour_local = (local - pd.Timedelta(hours=1)).hour + 0.5
    normals = DailyNormals(site.normals)
    tmax_normal = normals.tmax_for((local - pd.Timedelta(hours=1)).dayofyear)

    columns: dict[str, pd.Series | np.ndarray] = {name: h[name] for name in CURRENT}
    columns["dewpoint"] = dewpoint_c(h["temp_mean"], h["hum_mean"])
    columns["tmax_normal"] = tmax_normal
    columns["departure"] = h["temp_max"] - tmax_normal
    for s in SERIES:
        for k in LAGS:
            columns[f"{s}_lag{k}"] = h[s].shift(k)
        for k in TENDENCIES:
            columns[f"{s}_chg{k}"] = h[s] - h[s].shift(k)
        for w in ROLLING:
            rolling = h[s].rolling(w, min_periods=max(1, w // 2))
            columns[f"{s}_mean{w}"] = rolling.mean()
            columns[f"{s}_min{w}"] = rolling.min()
            columns[f"{s}_max{w}"] = rolling.max()
            columns[f"{s}_std{w}"] = rolling.std()
    columns["hour_sin"] = np.sin(2 * np.pi * hour_local / 24)
    columns["hour_cos"] = np.cos(2 * np.pi * hour_local / 24)
    doy = local.dayofyear
    columns["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    columns["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    columns["coverage_24h"] = h["n_observed"].rolling(24, min_periods=1).sum() / (
        24 * SLOTS_PER_HOUR
    )

    features = pd.DataFrame(columns, index=h.index)
    return features[feature_names()].astype(float)
