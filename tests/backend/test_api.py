"""API tests: auth, readings, predictions, alerts with outcomes, kits, quality, system, WebSocket.

The real app (routers, middleware) runs against a temporary database schema;
background services are replaced by small fakes.
"""

import csv
import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.inference.runner import hour_boundary
from backend.app.ingest.kit_status import KitStatusService
from backend.app.main import app
from backend.app.models import Alert, Kit, Prediction, Reading, User
from backend.app.security import LoginRateLimiter, create_access_token, hash_password
from backend.app.settings import (
    AppConfig,
    load_env_settings,
    load_site_config,
    load_synthetic_config,
)
from backend.app.ws.hub import WebSocketHub
from ml.core.features import dewpoint_c

SITE = load_site_config()
ENV = load_env_settings()
NOW = datetime.now(UTC).replace(second=0, microsecond=0)
HOUR = hour_boundary(NOW, SITE.site.timezone)  # predictions run on site-clock hours
ENDED = HOUR - timedelta(hours=5)  # an alert window that has finished
PASSWORD = "correct horse battery"


class FakeDatabase:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def ping(self) -> bool:
        return True


class Fake:
    """Attribute bag standing in for background services."""

    def __init__(self, **values) -> None:
        self.__dict__.update(values)


def install_state(session_factory, hub) -> None:
    state = app.state
    state.config = AppConfig(site=SITE, synthetic=load_synthetic_config(site=SITE), env=ENV)
    state.database = FakeDatabase(session_factory)
    state.hub = hub
    state.login_limiter = LoginRateLimiter()
    state.subscriber = Fake(connected=True)
    state.scheduler = Fake(running=True, next_run_time=NOW + timedelta(minutes=30))
    state.runner = Fake(last_run=NOW - timedelta(minutes=30))
    state.model_store = Fake(
        version="v1",
        loaded=Fake(
            version="v1", metadata={"created_at": "2026-10-31", "data_source": "synthetic"}
        ),
        error=None,
    )


def prediction(run_at, hazard, level, p) -> Prediction:
    return Prediction(
        kit_id="kit01",
        run_at=run_at,
        hazard=hazard,
        status="ok",
        p_yellow=p,
        p_orange=p,
        p_red=p / 2,
        level=level,
        valid_until=run_at + timedelta(hours=3),
        model_version="v1",
        context={},
    )


@pytest.fixture
async def client(session_factory, hub):
    """Seeded database + logged-out HTTP client."""
    await KitStatusService(SITE, session_factory, hub).sync_kits()
    start = NOW - timedelta(hours=48)
    async with session_factory() as session, session.begin():
        session.add(
            User(username="admin", email="Admin@Example.com", password_hash=hash_password(PASSWORD))
        )
        for i in range(48 * 12):
            ts = start + timedelta(minutes=5 * i)
            windy = ENDED < ts <= ENDED + timedelta(hours=3)
            session.add(
                Reading(
                    kit_id="kit01",
                    ts=ts,
                    ts_source="kit",
                    received_at=ts,
                    temp_bme_c=35.0 + i * 0.001,
                    hum_bme_pct=45.0,
                    temp_dht_c=36.0,
                    hum_dht_pct=47.0,
                    pressure_hpa=1000.0 - i * 0.002,
                    wind_speed_ms=15.0 if windy else 3.0,
                    temp_c=35.0 + i * 0.001,
                    hum_pct=45.0,
                    qc_flags=["pressure_hpa:spike"] if i == 100 else [],
                )
            )
        wind = prediction(ENDED, "wind", "orange", 0.7)
        heat = prediction(ENDED, "heat", "orange", 0.6)
        current = prediction(HOUR, "wind", "red", 0.9)
        session.add_all([wind, heat, current])
        await session.flush()
        for p, status in ((wind, "sent"), (heat, "sent"), (current, "cooldown")):
            session.add(
                Alert(
                    prediction_id=p.id,
                    kit_id="kit01",
                    hazard=p.hazard,
                    level=p.level,
                    probability=p.p_orange,
                    valid_until=p.valid_until,
                    email_status=status,
                    created_at=p.run_at + timedelta(seconds=30),
                    sent_at=p.run_at + timedelta(seconds=31) if status == "sent" else None,
                )
            )
        kit = await session.get(Kit, "kit01")
        kit.status, kit.last_seen, kit.fw_version = "online", NOW, "1.2.0"

    install_state(session_factory, hub)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def auth() -> dict:
    token, _ = create_access_token("admin", ENV)
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------- auth


async def test_login_with_username_or_email(client):
    for login in ("admin", "admin@example.com"):
        response = await client.post(
            "/api/auth/login", json={"username": login, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["username"] == "admin"
        me = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        assert me.json() == {"username": "admin"}


async def test_wrong_password_and_rate_limit(client):
    for _ in range(5):
        response = await client.post(
            "/api/auth/login", json={"username": "admin", "password": "nope"}
        )
        assert response.status_code == 401
    blocked = await client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert blocked.status_code == 429


@pytest.mark.parametrize(
    "path",
    [
        "/api/readings/latest?kit_id=kit01",
        "/api/readings?kit_id=kit01",
        "/api/readings/export.csv?kit_id=kit01",
        "/api/predictions/latest?kit_id=kit01",
        "/api/alerts",
        "/api/kits",
        "/api/quality?kit_id=kit01",
        "/api/system",
    ],
)
async def test_endpoints_require_login(client, path):
    assert (await client.get(path)).status_code == 401
    bad = await client.get(path, headers={"Authorization": "Bearer not-a-token"})
    assert bad.status_code == 401


async def test_health_is_public(client):
    assert (await client.get("/api/health")).status_code == 200


# ----------------------------------------------------------------- readings


async def test_latest_reading(client):
    body = (await client.get("/api/readings/latest?kit_id=kit01", headers=auth())).json()
    reading = body["reading"]
    assert reading["temp_c"] == pytest.approx(35.575, abs=0.01)
    assert reading["trend"]["temp_c"] == "steady"
    assert reading["dewpoint_c"] == pytest.approx(dewpoint_c(reading["temp_c"], 45.0), abs=0.1)
    assert reading["pressure_change_3h"] == pytest.approx(-0.07, abs=0.05)


async def test_unknown_kit_is_404(client):
    response = await client.get("/api/readings/latest?kit_id=kit99", headers=auth())
    assert response.status_code == 404


async def test_series_raw_and_hourly(client):
    raw = (await client.get("/api/readings?kit_id=kit01", headers=auth())).json()
    assert raw["resolution"] == "raw"
    assert 280 <= len(raw["points"]) <= 290
    assert {"temp_bme_c", "temp_dht_c", "wind_max_ms", "flagged"} <= set(raw["points"][0])

    start = (NOW - timedelta(days=10)).isoformat()
    hourly = (
        await client.get("/api/readings", params={"kit_id": "kit01", "from": start}, headers=auth())
    ).json()
    assert hourly["resolution"] == "hourly"
    assert 47 <= len(hourly["points"]) <= 50
    assert max(p["wind_max_ms"] for p in hourly["points"]) == 15.0


async def test_bad_range_is_400(client):
    start, end = NOW.isoformat(), (NOW - timedelta(hours=1)).isoformat()
    response = await client.get(
        "/api/readings", params={"kit_id": "kit01", "from": start, "to": end}, headers=auth()
    )
    assert response.status_code == 400


async def test_csv_export(client):
    response = await client.get(
        "/api/readings/export.csv",
        params={"kit_id": "kit01", "from": (NOW - timedelta(hours=6)).isoformat()},
        headers=auth(),
    )
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 72
    with_prediction = [r for r in rows if r["wind_level"]]
    assert {r["wind_level"] for r in with_prediction} <= {"orange", "red"}
    assert len(with_prediction) >= 12  # a full hour of readings matched to its prediction


# -------------------------------------------------------- predictions/alerts


async def test_latest_predictions(client):
    body = (await client.get("/api/predictions/latest?kit_id=kit01", headers=auth())).json()
    levels = {item["hazard"]: item["level"] for item in body["items"]}
    assert levels == {"wind": "red", "heat": "orange"}


async def test_alerts_with_outcomes_and_stats(client):
    body = (await client.get("/api/alerts", headers=auth())).json()
    by_hazard_level = {(a["hazard"], a["email_status"]): a for a in body["items"]}
    assert body["total"] == 3

    pending = by_hazard_level[("wind", "cooldown")]
    assert pending["outcome"]["status"] == "pending"

    wind = by_hazard_level[("wind", "sent")]
    assert wind["outcome"]["status"] == "happened"  # 54 km/h ≥ Orange (40)
    assert wind["outcome"]["observed_level"] == "orange"
    assert wind["outcome"]["peak_wind_kmh"] == 54

    heat = by_hazard_level[("heat", "sent")]
    assert heat["outcome"]["status"] == "did_not_happen"  # ~35.5 °C < 40 °C

    assert body["stats"] == {"days": 7, "raised": 3, "emailed": 2, "confirmed": 1, "evaluated": 2}


async def test_alert_filters_and_pagination(client):
    body = (await client.get("/api/alerts?hazard=heat", headers=auth())).json()
    assert [a["hazard"] for a in body["items"]] == ["heat"]
    page = (await client.get("/api/alerts?page=2&page_size=2", headers=auth())).json()
    assert (page["page"], page["pages"], len(page["items"])) == (2, 2, 1)


# ------------------------------------------------------ kits/quality/system


async def test_kits(client):
    kit = (await client.get("/api/kits", headers=auth())).json()["items"][0]
    assert (kit["kit_id"], kit["status"], kit["fw_version"]) == ("kit01", "online", "1.2.0")
    assert kit["interval_s"] == 300
    assert kit["telemetry_topic"] == "weather/kit/kit01/telemetry"

    history = (await client.get("/api/kits/kit01/status-history", headers=auth())).json()
    assert len(history["daily"]) == 7
    assert history["daily"][-1]["share"] > 0.9


async def test_quality(client):
    body = (await client.get("/api/quality?kit_id=kit01", headers=auth())).json()
    assert body["interval_s"] == 300
    assert body["expected"] == 288
    assert 285 <= body["received"] <= 289
    assert body["flags"]["spike"] == 0  # the flagged reading is older than 24 h
    assert body["sensors"]["dht11"]["status"] == "ok"
    assert body["sensors"]["dht11"]["drift_c"] == pytest.approx(0.6, abs=0.2)
    assert body["sensors"]["rain_gauge"]["status"] == "not_fitted"


async def test_system(client):
    body = (await client.get("/api/system", headers=auth())).json()
    assert body["site"]["name"] == "Karur Campus"
    assert body["model"]["version"] == "v1"
    assert body["settings"]["wind_kmh"] == {"yellow": 30, "orange": 40, "red": 60}
    assert body["settings"]["heat"]["abs_threshold_c"] == 40
    assert body["components"]["email"]["last_sent_at"] is not None


# ---------------------------------------------------------------- websocket


def test_websocket_rejects_bad_token(session_factory, hub):
    install_state(session_factory, WebSocketHub())
    with TestClient(app) as http, pytest.raises(WebSocketDisconnect) as closed:
        with http.websocket_connect("/ws/live?token=bad") as socket:
            socket.receive_text()
    assert closed.value.code == 4401


def test_websocket_accepts_valid_token(session_factory, hub):
    install_state(session_factory, WebSocketHub())
    token, _ = create_access_token("admin", ENV)
    with TestClient(app) as http, http.websocket_connect(f"/ws/live?token={token}"):
        assert app.state.hub.client_count == 1
