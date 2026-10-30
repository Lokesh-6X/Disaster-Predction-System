"""Hazard levels from model probabilities (FR-INF-03, design §10.3)."""

from __future__ import annotations

from collections.abc import Mapping

LEVELS = ("yellow", "orange", "red")  # increasing severity; each means "this level or worse"
GREEN = "green"
RANK = {GREEN: 0, "yellow": 1, "orange": 2, "red": 3}


def make_monotonic(probabilities: Mapping[str, float]) -> dict[str, float]:
    """A worse level can never be more likely than a milder one."""
    result: dict[str, float] = {}
    ceiling = 1.0
    for level in LEVELS:
        ceiling = min(ceiling, float(probabilities[level]))
        result[level] = ceiling
    return result


def select_level(probabilities: Mapping[str, float], cutoff: float) -> str:
    """Highest level whose probability reaches the cutoff, else green."""
    for level in reversed(LEVELS):
        if probabilities[level] >= cutoff:
            return level
    return GREEN
