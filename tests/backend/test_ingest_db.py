"""Integration tests: ingestion and kit status against PostgreSQL (FR-ING, FR-DB)."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from backend.app.ingest.kit_status import KitStatusService
from backend.app.ingest.pipeline import IngestPipeline
from backend.app.models import Kit, KitStatusLog, Reading
from backend.app.settings import load_site_config

SITE = load_site_config()
NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
GOOD = {
    "temp_bme_c": 32.0,
    "hum_bme_pct": 55.0,
    "pressure_hpa": 1000.0,
    "temp_dht_c": 33,
    "hum_dht_pct": 57,
    "wind_speed_ms": 3.0,
    "fw_version": "1.2.0",
}


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def message(ts: datetime, **changes) -> bytes:
    return json.dumps({"ts": ts.isoformat().replace("+00:00", "Z"), **GOOD, **changes}).encode()


@pytest.fixture
def clock() -> Clock:
    return Clock(NOW)


@pytest.fixture
async def services(session_factory, hub, clock):
    kit_status = KitStatusService(SITE, session_factory, hub, clock=clock)
    await kit_status.sync_kits()
    pipeline = IngestPipeline(SITE, session_factory, kit_status, hub, clock=clock)
    return kit_status, pipeline


async def count(session_factory, model) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def get_kit(session_factory) -> Kit:
    async with session_factory() as session:
        return await session.get(Kit, "kit01")


async def test_sync_kits_creates_config_kits(session_factory, services):
    kit = await get_kit(session_factory)
    assert kit.description == "Block A rooftop"
    assert kit.status == "unknown"


async def test_reading_is_stored_and_kit_goes_online(session_factory, services, hub):
    _, pipeline = services
    stored = await pipeline.handle_telemetry("kit01", message(NOW), received_at=NOW)

    assert stored is not None
    async with session_factory() as session:
        row = (await session.execute(select(Reading))).scalar_one()
    assert row.ts == NOW
    assert row.temp_c == 32.0
    assert row.qc_flags == []

    kit = await get_kit(session_factory)
    assert (kit.status, kit.last_seen, kit.fw_version) == ("online", NOW, "1.2.0")
    assert await count(session_factory, KitStatusLog) == 1
    assert [kind for kind, _ in hub.messages] == ["kit_status", "reading"]


async def test_duplicate_reading_is_ignored(session_factory, services):
    _, pipeline = services
    assert await pipeline.handle_telemetry("kit01", message(NOW), received_at=NOW)
    assert await pipeline.handle_telemetry("kit01", message(NOW), received_at=NOW) is None
    assert await count(session_factory, Reading) == 1


async def test_unknown_kit_and_bad_payload_are_not_stored(session_factory, services):
    _, pipeline = services
    assert await pipeline.handle_telemetry("kit99", message(NOW), received_at=NOW) is None
    assert await pipeline.handle_telemetry("kit01", b"{not json", received_at=NOW) is None
    assert await count(session_factory, Reading) == 0


async def test_status_messages(session_factory, services, hub):
    kit_status, _ = services
    await kit_status.handle_status_message("kit01", b"online")
    await kit_status.handle_status_message("kit01", b"online")  # unchanged: not logged again
    await kit_status.handle_status_message("kit01", b"OFFLINE\n")
    await kit_status.handle_status_message("kit01", b"sleeping")  # unknown: ignored

    assert (await get_kit(session_factory)).status == "offline"
    async with session_factory() as session:
        log = (await session.execute(select(KitStatusLog).order_by(KitStatusLog.id))).scalars()
        assert [(e.status, e.source) for e in log] == [
            ("online", "mqtt_status"),
            ("offline", "mqtt_status"),
        ]
    assert len(hub.of_type("kit_status")) == 2


async def test_watchdog_marks_silent_kit_offline(session_factory, services, clock):
    kit_status, pipeline = services
    await pipeline.handle_telemetry("kit01", message(NOW), received_at=NOW)

    clock.now = NOW + timedelta(minutes=9)
    assert await kit_status.check_offline() == []
    clock.now = NOW + timedelta(minutes=11)
    assert await kit_status.check_offline() == ["kit01"]
    assert (await get_kit(session_factory)).status == "offline"

    # The next reading brings it back online
    later = NOW + timedelta(minutes=12)
    await pipeline.handle_telemetry("kit01", message(later), received_at=later)
    assert (await get_kit(session_factory)).status == "online"


async def test_qc_history_survives_restart(session_factory, services, hub, clock):
    kit_status, pipeline = services
    await pipeline.handle_telemetry("kit01", message(NOW), received_at=NOW)

    # A new pipeline (as after a backend restart) loads history from the database
    clock.now = NOW + timedelta(minutes=5)
    restarted = IngestPipeline(SITE, session_factory, kit_status, hub, clock=clock)
    await restarted.load_history()
    reading = await restarted.handle_telemetry(
        "kit01", message(clock.now, temp_bme_c=40.0), received_at=clock.now
    )
    assert "temp_bme_c:spike" in reading.qc_flags
    assert reading.temp_c == 33  # DHT11 fallback while BME280 value is a spike
    assert reading.fallback is True
