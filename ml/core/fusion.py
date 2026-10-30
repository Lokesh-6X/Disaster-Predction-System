"""BME280 / DHT11 sensor fusion (FR-QC-04, design §6.4).

The BME280 is primary. The DHT11 is used only when the BME280 value is missing
or flagged by QC, and a large disagreement between usable values is flagged.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ml.core.qc import INVALIDATING_RULES, make_flag

MISMATCH = "bme_dht_mismatch"

# fused name, BME280 field, DHT11 field
PAIRS = (
    ("temp_c", "temp_bme_c", "temp_dht_c"),
    ("hum_pct", "hum_bme_pct", "hum_dht_pct"),
)


@dataclass(frozen=True)
class FusionResult:
    temp_c: float | None
    hum_pct: float | None
    fallback: bool
    flags: tuple[str, ...]


def _usable(values: Mapping[str, float | None], flags: set[str], name: str) -> float | None:
    if any(make_flag(name, rule) in flags for rule in INVALIDATING_RULES):
        return None
    return values.get(name)


def fuse(
    values: Mapping[str, float | None],
    flags: Iterable[str],
    mismatch_limits: Mapping[str, float],
) -> FusionResult:
    """Choose temperature and humidity values; ``mismatch_limits`` is keyed by fused name."""
    flag_set = set(flags)
    fused: dict[str, float | None] = {}
    fallback = False
    added: list[str] = []
    for name, bme_field, dht_field in PAIRS:
        bme = _usable(values, flag_set, bme_field)
        dht = _usable(values, flag_set, dht_field)
        if bme is not None:
            fused[name] = bme
            if dht is not None and abs(bme - dht) > mismatch_limits[name]:
                added.append(make_flag(name, MISMATCH))
        elif dht is not None:
            fused[name] = dht
            fallback = True
        else:
            fused[name] = None
    return FusionResult(
        temp_c=fused["temp_c"],
        hum_pct=fused["hum_pct"],
        fallback=fallback,
        flags=tuple(added),
    )
