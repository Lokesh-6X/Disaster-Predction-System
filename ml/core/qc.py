"""Quality-control rules for kit readings (FR-QC-01..03, design §6.3).

Pure functions with no database or web dependencies, shared by live ingestion
and the offline ML pipeline. Flags are strings of the form ``"<field>:<rule>"``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Sensor field -> measured quantity (selects the range and spike limits)
SENSOR_FIELDS: dict[str, str] = {
    "temp_bme_c": "temp_c",
    "hum_bme_pct": "hum_pct",
    "pressure_hpa": "pressure_hpa",
    "temp_dht_c": "temp_c",
    "hum_dht_pct": "hum_pct",
    "wind_speed_ms": "wind_ms",
}
SPIKE_FIELDS = ("temp_bme_c", "hum_bme_pct", "pressure_hpa", "temp_dht_c", "hum_dht_pct")

# The DHT11 reports whole numbers, so a steady night-time value can repeat for a
# long time without the sensor being stuck; it gets a longer stuck window.
LOW_RESOLUTION_FIELDS = ("temp_dht_c", "hum_dht_pct")
LOW_RESOLUTION_STUCK_FACTOR = 3

MIN_STUCK_READINGS = 6
MAX_SPIKE_GAP = timedelta(minutes=15)

NULL = "null"
OUT_OF_RANGE = "out_of_range"
SPIKE = "spike"
STUCK = "stuck"
TS_MISSING = "ts_missing"

# Flags that make a value unusable for fusion and features (the raw value is still stored)
INVALIDATING_RULES = (NULL, OUT_OF_RANGE, SPIKE, STUCK)


@dataclass(frozen=True)
class QcLimits:
    ranges: Mapping[str, tuple[float, float]]
    spike_per_min: Mapping[str, float]
    stuck_minutes: int

    @classmethod
    def from_config(cls, qc) -> QcLimits:
        """Build from the ``qc`` section of site.yaml."""
        return cls(
            ranges={k: tuple(v) for k, v in qc.ranges.model_dump().items()},
            spike_per_min=qc.spike_per_min.model_dump(),
            stuck_minutes=qc.stuck_minutes,
        )

    @property
    def history_window(self) -> timedelta:
        """How much earlier data the checks need."""
        return timedelta(minutes=self.stuck_minutes * LOW_RESOLUTION_STUCK_FACTOR) + MAX_SPIKE_GAP


@dataclass(frozen=True)
class QcReading:
    """An earlier reading of the same kit, as needed by the spike and stuck checks."""

    ts: datetime
    values: Mapping[str, float | None]
    flags: frozenset[str] = field(default_factory=frozenset)


def make_flag(field_name: str, rule: str) -> str:
    return f"{field_name}:{rule}"


def field_flagged(flags: Iterable[str], field_name: str) -> bool:
    prefix = field_name + ":"
    return any(f.startswith(prefix) for f in flags)


def check_reading(
    ts: datetime,
    values: Mapping[str, float | None],
    history: Sequence[QcReading],
    limits: QcLimits,
) -> list[str]:
    """Return QC flags for one reading.

    ``history`` holds earlier readings of the same kit, oldest first; entries at or
    after ``ts`` are ignored.
    """
    earlier = [r for r in history if r.ts < ts]
    flags: list[str] = []
    for name, quantity in SENSOR_FIELDS.items():
        value = values.get(name)
        if value is None:
            flags.append(make_flag(name, NULL))
            continue
        low, high = limits.ranges[quantity]
        if not low <= value <= high:
            flags.append(make_flag(name, OUT_OF_RANGE))
            continue
        if name in SPIKE_FIELDS and _is_spike(name, quantity, ts, value, earlier, limits):
            flags.append(make_flag(name, SPIKE))
        if _is_stuck(name, ts, value, earlier, limits):
            flags.append(make_flag(name, STUCK))
    return flags


def _previous_valid(name: str, earlier: Sequence[QcReading]) -> QcReading | None:
    for reading in reversed(earlier):
        if reading.values.get(name) is None:
            continue
        if any(make_flag(name, rule) in reading.flags for rule in (OUT_OF_RANGE, SPIKE)):
            continue
        return reading
    return None


def _is_spike(
    name: str,
    quantity: str,
    ts: datetime,
    value: float,
    earlier: Sequence[QcReading],
    limits: QcLimits,
) -> bool:
    previous = _previous_valid(name, earlier)
    if previous is None:
        return False
    gap = ts - previous.ts
    if gap > MAX_SPIKE_GAP:
        return False
    minutes = gap.total_seconds() / 60
    change_per_min = abs(value - previous.values[name]) / minutes
    return change_per_min > limits.spike_per_min[quantity]


def _is_stuck(
    name: str,
    ts: datetime,
    value: float,
    earlier: Sequence[QcReading],
    limits: QcLimits,
) -> bool:
    if name == "wind_speed_ms" and value == 0:
        return False  # calm is a valid steady value
    factor = LOW_RESOLUTION_STUCK_FACTOR if name in LOW_RESOLUTION_FIELDS else 1
    window = timedelta(minutes=limits.stuck_minutes * factor)
    count, oldest = 1, ts
    for reading in reversed(earlier):
        if reading.values.get(name) != value:
            break
        count += 1
        oldest = reading.ts
    return count >= MIN_STUCK_READINGS and ts - oldest >= window
