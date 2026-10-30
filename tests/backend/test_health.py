"""Smoke test: the app starts with valid configuration and answers /api/health.

The test .env has made-up credentials, so the database and broker are reported
as unavailable — the app must still start and answer.
"""

from fastapi.testclient import TestClient

from backend.app import settings
from backend.app.main import app


def test_health(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DB_PASSWORD=db-secret",
                "MQTT_PASSWORD=mqtt-secret",
                "MQTT_KIT_PASSWORD=kit-secret",
                "ADMIN_PASSWORD=admin-secret",
                "ADMIN_EMAIL=admin@example.com",
                "JWT_SECRET=" + "x" * 40,
                "SMTP_FROM=alerts@example.com",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "ENV_FILE", env_file)
    settings.get_config.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["site"] == "Karur Campus"
        assert body["components"]["database"] == "down"
        assert body["components"]["mqtt"] == "disconnected"
    finally:
        settings.get_config.cache_clear()
