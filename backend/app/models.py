"""Database tables (design §5.1). All timestamps are stored in UTC (timestamptz)."""

from datetime import datetime

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        str: Text,
        float: Float,
        bool: Boolean,
    }


class Kit(Base):
    __tablename__ = "kits"

    kit_id: Mapped[str] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(server_default="")
    latitude: Mapped[float | None]
    longitude: Mapped[float | None]
    anemometer_height_m: Mapped[float | None]
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    fw_version: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default="unknown")  # online / offline / unknown
    last_seen: Mapped[datetime | None]  # time the last reading was received
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class KitStatusLog(Base):
    __tablename__ = "kit_status_log"
    __table_args__ = (Index("ix_kit_status_log_kit_ts", "kit_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kit_id: Mapped[str] = mapped_column(ForeignKey("kits.kit_id"))
    ts: Mapped[datetime]
    status: Mapped[str]
    source: Mapped[str]  # mqtt_status / telemetry / watchdog


class Reading(Base):
    __tablename__ = "readings"
    # The unique constraint's index also serves time-range queries per kit.
    __table_args__ = (UniqueConstraint("kit_id", "ts", name="uq_readings_kit_ts"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kit_id: Mapped[str] = mapped_column(ForeignKey("kits.kit_id"))
    ts: Mapped[datetime]
    ts_source: Mapped[str]  # kit / arrival
    received_at: Mapped[datetime]
    # Raw values as sent by the kit
    temp_bme_c: Mapped[float | None] = mapped_column(REAL)
    hum_bme_pct: Mapped[float | None] = mapped_column(REAL)
    pressure_hpa: Mapped[float | None] = mapped_column(REAL)
    temp_dht_c: Mapped[float | None] = mapped_column(REAL)
    hum_dht_pct: Mapped[float | None] = mapped_column(REAL)
    wind_speed_ms: Mapped[float | None] = mapped_column(REAL)
    wind_gust_ms: Mapped[float | None] = mapped_column(REAL)
    rain_mm: Mapped[float | None] = mapped_column(REAL)
    # Fused values (BME280 primary, DHT11 fallback)
    temp_c: Mapped[float | None] = mapped_column(REAL)
    hum_pct: Mapped[float | None] = mapped_column(REAL)
    fallback: Mapped[bool] = mapped_column(server_default=text("false"))
    qc_flags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    fw_version: Mapped[str | None]


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("kit_id", "hazard", "run_at", name="uq_predictions_kit_hazard_run"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kit_id: Mapped[str] = mapped_column(ForeignKey("kits.kit_id"))
    run_at: Mapped[datetime]
    hazard: Mapped[str]  # wind / heat
    status: Mapped[str]  # ok / insufficient_data
    p_yellow: Mapped[float | None] = mapped_column(REAL)
    p_orange: Mapped[float | None] = mapped_column(REAL)
    p_red: Mapped[float | None] = mapped_column(REAL)
    level: Mapped[str | None]  # green / yellow / orange / red
    valid_until: Mapped[datetime]
    model_version: Mapped[str | None]
    fallback_used: Mapped[bool] = mapped_column(server_default=text("false"))
    context: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_kit_hazard_created", "kit_id", "hazard", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"))
    kit_id: Mapped[str] = mapped_column(ForeignKey("kits.kit_id"))
    hazard: Mapped[str]
    level: Mapped[str]
    probability: Mapped[float] = mapped_column(REAL)
    valid_until: Mapped[datetime]
    email_status: Mapped[str]  # sent / cooldown / failed / disabled
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    sent_at: Mapped[datetime | None]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str]
    password_hash: Mapped[str]
    role: Mapped[str] = mapped_column(server_default="admin")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
