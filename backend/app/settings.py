"""Configuration loading and validation (FR-CFG-01..04).

Loads ``config/site.yaml``, ``config/synthetic.yaml`` and ``.env`` into typed,
read-only models. Any problem raises :class:`ConfigError` naming the file, the
setting and the reason, so the backend refuses to start with a clear message.
The ML command-line tools use the same loader.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("WEATHER_CONFIG_DIR", PROJECT_ROOT / "config"))
ENV_FILE = PROJECT_ROOT / ".env"

Level = Literal["yellow", "orange", "red"]
Range = tuple[float, float]


class ConfigError(Exception):
    """Raised when a configuration file is missing or invalid."""


class _Strict(BaseModel):
    # Unknown keys are errors, so typos in the YAML are caught.
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- site.yaml


class Site(_Strict):
    name: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation_m: float = Field(ge=-500, le=9000)
    timezone: str
    coastal: bool

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone '{value}'") from None
        return value


class Kit(_Strict):
    # kit_id is used inside MQTT topics, so MQTT wildcard characters are not allowed.
    kit_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    description: str = ""
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    anemometer_height_m: float | None = Field(default=None, gt=0)
    enabled: bool = True
    notes: str = ""


class WindLevels(_Strict):
    yellow: float = Field(gt=0)
    orange: float = Field(gt=0)
    red: float = Field(gt=0)

    @model_validator(mode="after")
    def _increasing(self) -> WindLevels:
        if not self.yellow < self.orange < self.red:
            raise ValueError("levels must increase: yellow < orange < red")
        return self


class WindHazard(_Strict):
    levels: WindLevels


class HeatDeparture(_Strict):
    yellow: float = Field(gt=0)
    orange: float = Field(gt=0)

    @model_validator(mode="after")
    def _increasing(self) -> HeatDeparture:
        if not self.yellow < self.orange:
            raise ValueError("departures must increase: yellow < orange")
        return self


class HeatHazard(_Strict):
    abs_threshold_c: float
    coastal_abs_threshold_c: float
    departure_c: HeatDeparture
    red_abs_c: float

    @model_validator(mode="after")
    def _red_above_thresholds(self) -> HeatHazard:
        if self.red_abs_c <= max(self.abs_threshold_c, self.coastal_abs_threshold_c):
            raise ValueError("red_abs_c must be above abs_threshold_c and coastal_abs_threshold_c")
        return self


class RainHazard(_Strict):
    enabled: bool = False


class Hazards(_Strict):
    wind: WindHazard
    heat: HeatHazard
    rain: RainHazard = RainHazard()


class QcRanges(_Strict):
    temp_c: Range
    hum_pct: Range
    pressure_hpa: Range
    wind_ms: Range

    @field_validator("temp_c", "hum_pct", "pressure_hpa", "wind_ms")
    @classmethod
    def _ordered(cls, value: Range) -> Range:
        low, high = value
        if not low < high:
            raise ValueError(f"range [{low}, {high}] must have low < high")
        return value


class SpikePerMin(_Strict):
    temp_c: float = Field(gt=0)
    hum_pct: float = Field(gt=0)
    pressure_hpa: float = Field(gt=0)


class FusionMismatch(_Strict):
    temp_c: float = Field(gt=0)
    hum_pct: float = Field(gt=0)


class Qc(_Strict):
    ranges: QcRanges
    spike_per_min: SpikePerMin
    stuck_minutes: int = Field(gt=0)
    fusion_mismatch: FusionMismatch
    future_ts_tolerance_min: int = Field(ge=0)


class Prediction(_Strict):
    run_cron_minute: int = Field(ge=0, le=59)
    horizon_hours: int = Field(gt=0, le=24)
    # Features use 24 h lags and rolling windows, so at least 25 h of history are needed.
    history_hours: int = Field(ge=25, le=168)
    show_level_cutoff: float = Field(gt=0, lt=1)


class DataSufficiency(_Strict):
    max_interp_gap_min: int = Field(ge=0)
    max_missing_share_24h: float = Field(ge=0, le=1)
    require_data_within_min: int = Field(gt=0)


class KitStatus(_Strict):
    offline_after_min: int = Field(gt=0)


class Alerts(_Strict):
    enabled: bool
    levels: list[Level] = Field(min_length=1)
    cooldown_hours: float = Field(ge=0)

    @field_validator("levels")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("levels must not repeat")
        return value


Monthly = list[float]


class Normals(_Strict):
    source: str
    provisional: bool = False
    tmax_c: Monthly
    tmin_c: Monthly
    rh_morning_pct: Monthly
    rh_evening_pct: Monthly
    wind_kmh: Monthly
    mslp_hpa: Monthly

    @field_validator("tmax_c", "tmin_c", "rh_morning_pct", "rh_evening_pct", "wind_kmh", "mslp_hpa")
    @classmethod
    def _twelve_months(cls, value: Monthly) -> Monthly:
        if len(value) != 12:
            raise ValueError(f"needs 12 monthly values (Jan..Dec), got {len(value)}")
        return value

    @model_validator(mode="after")
    def _tmax_above_tmin(self) -> Normals:
        for month, (tmax, tmin) in enumerate(zip(self.tmax_c, self.tmin_c, strict=True), start=1):
            if tmax <= tmin:
                raise ValueError(f"month {month}: tmax_c must be above tmin_c")
        return self


class SiteConfig(_Strict):
    site: Site
    kits: list[Kit] = Field(min_length=1)
    hazards: Hazards
    qc: Qc
    prediction: Prediction
    data_sufficiency: DataSufficiency
    kit_status: KitStatus
    alerts: Alerts
    normals: Normals

    @field_validator("kits")
    @classmethod
    def _unique_kit_ids(cls, kits: list[Kit]) -> list[Kit]:
        ids = [k.kit_id for k in kits]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate kit_id: {', '.join(duplicates)}")
        return kits

    @property
    def heat_abs_threshold_c(self) -> float:
        heat = self.hazards.heat
        return heat.coastal_abs_threshold_c if self.site.coastal else heat.abs_threshold_c

    @property
    def enabled_kits(self) -> list[Kit]:
        return [k for k in self.kits if k.enabled]

    def kit(self, kit_id: str) -> Kit | None:
        return next((k for k in self.kits if k.kit_id == kit_id), None)


# ----------------------------------------------------------- synthetic.yaml


class SyntheticEvents(_Strict):
    heat_spells_per_year: float = Field(ge=0)
    wind_spells_per_year: float = Field(ge=0)
    storms_per_year: float = Field(ge=0)


class SyntheticFaults(_Strict):
    enabled: bool
    spike_prob: float = Field(ge=0, le=1)
    stuck_runs_per_year: float = Field(ge=0)
    gap_runs_per_year: float = Field(ge=0)
    offline_runs_per_year: float = Field(ge=0)
    bme_failure_runs_per_year: float = Field(ge=0)


class SyntheticConfig(_Strict):
    start_date: date
    years: int = Field(ge=1, le=30)
    interval_min: int = Field(ge=1, le=5)
    seed: int
    kit_id: str
    target_hazard_hour_share: tuple[float, float]
    events: SyntheticEvents
    faults: SyntheticFaults
    output: str

    @field_validator("target_hazard_hour_share")
    @classmethod
    def _share_range(cls, value: tuple[float, float]) -> tuple[float, float]:
        low, high = value
        if not 0 < low < high < 1:
            raise ValueError("must be [low, high] with 0 < low < high < 1")
        return value

    @property
    def output_path(self) -> Path:
        return PROJECT_ROOT / self.output


# --------------------------------------------------------------------- .env


_PLACEHOLDER = "change-me"


class EnvSettings(BaseSettings):
    """Secrets and machine-specific settings from ``.env`` (FR-CFG-03)."""

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "weather"
    db_user: str = "weather"
    db_password: SecretStr

    mqtt_host: str = "localhost"
    mqtt_port: int = 1884
    mqtt_username: str = "backend"
    mqtt_password: SecretStr
    mqtt_kit_username: str = "kit01"
    mqtt_kit_password: SecretStr

    admin_username: str = "admin"
    admin_password: SecretStr
    admin_email: str

    jwt_secret: SecretStr
    jwt_expire_hours: float = Field(default=8, gt=0)

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str
    smtp_starttls: bool = False

    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator(
        "db_password", "mqtt_password", "mqtt_kit_password", "admin_password", "jwt_secret"
    )
    @classmethod
    def _not_placeholder(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value().startswith(_PLACEHOLDER):
            raise ValueError("still the placeholder from .env.example — set a real value")
        return value

    @field_validator("jwt_secret")
    @classmethod
    def _long_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("must be at least 32 characters")
        return value

    @property
    def database_url(self) -> str:
        password = quote_plus(self.db_password.get_secret_value())
        user = quote_plus(self.db_user)
        return (
            f"postgresql+asyncpg://{user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


# ------------------------------------------------------------------ loading


def _format_errors(source: str, error: ValidationError) -> str:
    lines = [f"{source} is invalid:"]
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "(top level)"
        lines.append(f"  - {location}: {item['msg']}")
    return "\n".join(lines)


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"{path} not found")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping of settings at the top level")
    return data


def load_site_config(path: Path | None = None) -> SiteConfig:
    path = path or CONFIG_DIR / "site.yaml"
    try:
        return SiteConfig.model_validate(_read_yaml(path))
    except ValidationError as exc:
        raise ConfigError(_format_errors(str(path), exc)) from None


def load_synthetic_config(
    path: Path | None = None, site: SiteConfig | None = None
) -> SyntheticConfig:
    path = path or CONFIG_DIR / "synthetic.yaml"
    try:
        config = SyntheticConfig.model_validate(_read_yaml(path))
    except ValidationError as exc:
        raise ConfigError(_format_errors(str(path), exc)) from None
    if site is not None and site.kit(config.kit_id) is None:
        raise ConfigError(
            f"{path} is invalid:\n  - kit_id: '{config.kit_id}' is not a kit in site.yaml"
        )
    return config


def load_env_settings(env_file: Path | None = None) -> EnvSettings:
    env_file = env_file or ENV_FILE
    try:
        return EnvSettings(_env_file=env_file)
    except ValidationError as exc:
        raise ConfigError(_format_errors(str(env_file), exc)) from None


@dataclass(frozen=True)
class AppConfig:
    site: SiteConfig
    synthetic: SyntheticConfig
    env: EnvSettings


def load_app_config() -> AppConfig:
    """Load and cross-check all configuration. Raises ConfigError on any problem."""
    site = load_site_config()
    synthetic = load_synthetic_config(site=site)
    env = load_env_settings()
    return AppConfig(site=site, synthetic=synthetic, env=env)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Cached application configuration (loaded once per process)."""
    return load_app_config()
