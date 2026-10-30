"""A stored hazard prediction, shared by the runner, alert engine and API."""

from dataclasses import dataclass, field
from datetime import datetime

OK = "ok"
INSUFFICIENT = "insufficient_data"


@dataclass
class HazardPrediction:
    kit_id: str
    run_at: datetime  # site-local hour boundary (UTC)
    hazard: str  # wind / heat
    status: str  # ok / insufficient_data
    valid_until: datetime
    probabilities: dict[str, float] | None = None  # yellow / orange / red, monotonic
    level: str | None = None  # green / yellow / orange / red
    model_version: str | None = None
    fallback_used: bool = False
    context: dict = field(default_factory=dict)
    id: int | None = None

    def to_message(self) -> dict:
        return {
            "id": self.id,
            "kit_id": self.kit_id,
            "run_at": self.run_at,
            "hazard": self.hazard,
            "status": self.status,
            "level": self.level,
            "p": self.probabilities,
            "valid_until": self.valid_until,
            "model_version": self.model_version,
            "fallback_used": self.fallback_used,
            "context": self.context,
        }
