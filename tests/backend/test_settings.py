"""Tests for configuration loading and validation (FR-CFG-01..04)."""

import copy
from pathlib import Path

import pytest
import yaml

from backend.app.settings import (
    CONFIG_DIR,
    ConfigError,
    load_env_settings,
    load_site_config,
    load_synthetic_config,
)

SITE_YAML = CONFIG_DIR / "site.yaml"
SYNTHETIC_YAML = CONFIG_DIR / "synthetic.yaml"

VALID_ENV = {
    "DB_PASSWORD": "db-secret",
    "MQTT_PASSWORD": "mqtt-secret",
    "MQTT_KIT_PASSWORD": "kit-secret",
    "ADMIN_PASSWORD": "admin-secret",
    "ADMIN_EMAIL": "admin@example.com",
    "JWT_SECRET": "x" * 40,
    "SMTP_FROM": "alerts@example.com",
}


@pytest.fixture
def site_data() -> dict:
    return yaml.safe_load(SITE_YAML.read_text(encoding="utf-8"))


def write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def write_env(path: Path, values: dict) -> Path:
    path.write_text("\n".join(f"{k}={v}" for k, v in values.items()), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    # Real environment variables would override the test .env files.
    for key in [*VALID_ENV, "DB_USER", "LOG_LEVEL"]:
        monkeypatch.delenv(key, raising=False)


# ------------------------------------------------------------- shipped files


def test_shipped_site_config_is_valid():
    config = load_site_config()
    assert config.site.name == "Karur Campus"
    assert [k.kit_id for k in config.kits] == ["kit01"]
    assert config.heat_abs_threshold_c == 40


def test_shipped_synthetic_config_is_valid():
    config = load_synthetic_config(site=load_site_config())
    assert config.interval_min == 5
    assert config.output_path.name == "karur_v1.parquet"


# ---------------------------------------------------------------- site.yaml


def test_coastal_site_uses_coastal_heat_threshold(tmp_path, site_data):
    site_data["site"]["coastal"] = True
    config = load_site_config(write_yaml(tmp_path / "site.yaml", site_data))
    assert config.heat_abs_threshold_c == 37


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda d: d["hazards"]["wind"]["levels"].update(orange=25), "yellow < orange < red"),
        (lambda d: d["hazards"]["heat"]["departure_c"].update(orange=4.0), "yellow < orange"),
        (lambda d: d["hazards"]["heat"].update(red_abs_c=39), "red_abs_c must be above"),
        (lambda d: d["kits"].append(copy.deepcopy(d["kits"][0])), "duplicate kit_id: kit01"),
        (lambda d: d["kits"][0].update(kit_id="kit/01"), "kits.0.kit_id"),
        (lambda d: d["kits"][0].update(colour="red"), "kits.0.colour"),
        (lambda d: d.update(kits=[]), "kits"),
        (lambda d: d["site"].update(timezone="Asia/Nowhere"), "unknown timezone"),
        (lambda d: d["site"].update(latitude=95), "site.latitude"),
        (lambda d: d["normals"]["tmax_c"].pop(), "needs 12 monthly values"),
        (lambda d: d["normals"]["tmin_c"].__setitem__(0, 31), "month 1: tmax_c must be above"),
        (lambda d: d["qc"]["ranges"].update(temp_c=[55, 0]), "must have low < high"),
        (lambda d: d["prediction"].update(show_level_cutoff=1.5), "prediction.show_level_cutoff"),
        (lambda d: d["prediction"].update(history_hours=12), "prediction.history_hours"),
        (lambda d: d["alerts"].update(levels=["orange", "purple"]), "alerts.levels"),
        (lambda d: d["alerts"].update(levels=["red", "red"]), "levels must not repeat"),
        (lambda d: d.pop("qc"), "qc: Field required"),
    ],
)
def test_invalid_site_config_is_rejected(tmp_path, site_data, change, expected):
    change(site_data)
    path = write_yaml(tmp_path / "site.yaml", site_data)
    with pytest.raises(ConfigError) as error:
        load_site_config(path)
    message = str(error.value)
    assert str(path) in message
    assert expected in message


def test_missing_site_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_site_config(tmp_path / "missing.yaml")


def test_broken_yaml(tmp_path):
    path = tmp_path / "site.yaml"
    path.write_text("site: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_site_config(path)


def test_yaml_that_is_not_a_mapping(tmp_path):
    path = tmp_path / "site.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_site_config(path)


# ----------------------------------------------------------- synthetic.yaml


def test_synthetic_kit_must_exist_in_site(tmp_path):
    data = yaml.safe_load(SYNTHETIC_YAML.read_text(encoding="utf-8"))
    data["kit_id"] = "kit99"
    path = write_yaml(tmp_path / "synthetic.yaml", data)
    with pytest.raises(ConfigError, match="'kit99' is not a kit in site.yaml"):
        load_synthetic_config(path, site=load_site_config())


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("target_hazard_hour_share", [0.05, 0.03], "0 < low < high < 1"),
        ("interval_min", 10, "interval_min"),
        ("years", 0, "years"),
    ],
)
def test_invalid_synthetic_config(tmp_path, key, value, expected):
    data = yaml.safe_load(SYNTHETIC_YAML.read_text(encoding="utf-8"))
    data[key] = value
    with pytest.raises(ConfigError, match=expected):
        load_synthetic_config(write_yaml(tmp_path / "synthetic.yaml", data))


# --------------------------------------------------------------------- .env


def test_valid_env(tmp_path):
    env = load_env_settings(
        write_env(tmp_path / ".env", {**VALID_ENV, "DB_PASSWORD": "p@ss:word/1"})
    )
    assert env.mqtt_port == 1884
    assert (
        env.database_url == "postgresql+asyncpg://weather:p%40ss%3Aword%2F1@localhost:5432/weather"
    )
    assert env.cors_origin_list == ["http://localhost:5173"]


def test_env_secrets_are_hidden_in_repr(tmp_path):
    env = load_env_settings(write_env(tmp_path / ".env", VALID_ENV))
    assert "db-secret" not in repr(env)


def test_env_missing_required_value(tmp_path):
    values = {k: v for k, v in VALID_ENV.items() if k != "JWT_SECRET"}
    with pytest.raises(ConfigError, match="jwt_secret: Field required"):
        load_env_settings(write_env(tmp_path / ".env", values))


def test_env_placeholder_is_rejected(tmp_path):
    values = {**VALID_ENV, "MQTT_PASSWORD": "change-me"}
    with pytest.raises(ConfigError, match="mqtt_password: .*placeholder"):
        load_env_settings(write_env(tmp_path / ".env", values))


def test_env_short_jwt_secret_is_rejected(tmp_path):
    values = {**VALID_ENV, "JWT_SECRET": "short"}
    with pytest.raises(ConfigError, match="at least 32 characters"):
        load_env_settings(write_env(tmp_path / ".env", values))
