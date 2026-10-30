"""Batch QC and fusion of a readings table — the same rules as live ingestion.

Used to prepare training data from raw kit-format readings (synthetic now,
real kit data in the next version).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping

import pandas as pd

from ml.core.fusion import fuse
from ml.core.qc import SENSOR_FIELDS, QcLimits, QcReading, check_reading


def qc_and_fuse(
    readings: pd.DataFrame, limits: QcLimits, mismatch_limits: Mapping[str, float]
) -> pd.DataFrame:
    """Add ``qc_flags``, ``temp_c``, ``hum_pct`` and ``fallback`` to raw readings.

    ``readings`` holds one kit's readings in the MQTT payload format with a UTC
    ``ts`` column; it is processed in time order.
    """
    frame = readings.sort_values("ts").reset_index(drop=True)
    fields = list(SENSOR_FIELDS)
    rows = frame[fields].astype(float).to_numpy()
    times = frame["ts"].tolist()

    history: deque[QcReading] = deque()
    window = limits.history_window
    all_flags: list[list[str]] = []
    temp: list[float | None] = []
    hum: list[float | None] = []
    fallback: list[bool] = []

    for ts, row in zip(times, rows, strict=True):
        values = {f: (None if v != v else float(v)) for f, v in zip(fields, row, strict=True)}
        while history and history[0].ts < ts - window:
            history.popleft()
        flags = check_reading(ts, values, history, limits)
        fusion = fuse(values, flags, mismatch_limits)
        flags += fusion.flags
        all_flags.append(flags)
        temp.append(fusion.temp_c)
        hum.append(fusion.hum_pct)
        fallback.append(fusion.fallback)
        history.append(QcReading(ts=ts, values=values, flags=frozenset(flags)))

    frame["qc_flags"] = all_flags
    frame["temp_c"] = pd.array(temp, dtype="Float64").astype(float)
    frame["hum_pct"] = pd.array(hum, dtype="Float64").astype(float)
    frame["fallback"] = fallback
    return frame
