"""MQTT topics and the telemetry payload model (docs/mqtt_contract.md)."""

import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TELEMETRY_FILTER = "weather/kit/+/telemetry"
STATUS_FILTER = "weather/kit/+/status"

_TOPIC = re.compile(r"^weather/kit/(?P<kit_id>[A-Za-z0-9_-]{1,32})/(?P<kind>telemetry|status)$")

TopicKind = Literal["telemetry", "status"]

# Numbers only: strings and booleans are rejected; NaN/Infinity are not allowed.
Number = Annotated[float | None, Field(default=None, strict=True, allow_inf_nan=False)]


def parse_topic(topic: str) -> tuple[str, TopicKind] | None:
    """Return (kit_id, kind) for a valid kit topic, else None."""
    match = _TOPIC.match(topic)
    if match is None:
        return None
    return match["kit_id"], match["kind"]  # type: ignore[return-value]


class TelemetryPayload(BaseModel):
    """One reading. Unknown extra fields are ignored."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    ts: datetime | None = None
    temp_bme_c: Number
    hum_bme_pct: Number
    pressure_hpa: Number
    temp_dht_c: Number
    hum_dht_pct: Number
    wind_speed_ms: Number
    wind_gust_ms: Number
    rain_mm: Number
    fw_version: str | None = Field(default=None, max_length=32)

    @field_validator("ts")
    @classmethod
    def _to_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:  # the contract says UTC
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def sensor_values(self) -> dict[str, float | None]:
        """All measured values keyed by payload field name."""
        return self.model_dump(exclude={"ts", "fw_version"})
