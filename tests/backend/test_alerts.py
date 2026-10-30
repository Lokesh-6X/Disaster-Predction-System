"""Integration tests: hourly runner + alert engine against PostgreSQL (FR-INF, FR-ALT)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from backend.app.alerts.emailer import render_alert_email
from backend.app.alerts.engine import AlertEngine
from backend.app.inference.runner import InferenceRunner
from backend.app.ingest.kit_status import KitStatusService
from backend.app.models import Alert, Prediction, Reading
from backend.app.settings import load_env_settings, load_site_config
from ml.core.labels import LABELS
from tests.backend.test_inference import stub_models

SITE = load_site_config()
RUN_AT = datetime(2026, 5, 10, 8, 30, tzinfo=UTC)  # 14:00 IST
HOUR = timedelta(hours=1)


class FakeEmailer:
    def __init__(self) -> None:
        self.sent = []
        self.fail = False

    async def send(self, email) -> None:
        if self.fail:
            raise ConnectionRefusedError("SMTP server not reachable")
        self.sent.append(email)


class FakeModelStore:
    def __init__(self, probabilities: dict | None) -> None:
        self.loaded = stub_models(probabilities) if probabilities is not None else None
        self.error = None if probabilities is not None else "no active model"

    @property
    def version(self):
        return self.loaded.version if self.loaded else None


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def levels(wind: str = "green", heat: str = "green") -> dict:
    """Stub probabilities that produce the given levels."""
    value = {"green": 0.1, "yellow": 0.6, "orange": 0.7, "red": 0.8}
    rank = ["green", "yellow", "orange", "red"]
    result = {}
    for hazard, level in (("wind", wind), ("heat", heat)):
        for name in ("yellow", "orange", "red"):
            reached = rank.index(level) >= rank.index(name)
            result[f"{hazard}_{name}"] = value[level] if reached else 0.05
    return result


@pytest.fixture
async def stack(session_factory, hub):
    """Kits synced, readings from 48 h before to 6 h after RUN_AT, runner + engine, fake emailer."""
    await KitStatusService(SITE, session_factory, hub).sync_kits()
    async with session_factory() as session, session.begin():
        start = RUN_AT - timedelta(hours=48)
        session.add_all(
            Reading(
                kit_id="kit01",
                ts=start + timedelta(minutes=5 * i),
                ts_source="kit",
                received_at=start + timedelta(minutes=5 * i),
                temp_c=35.0,
                hum_pct=45.0,
                pressure_hpa=995.0,
                wind_speed_ms=3.0,
                qc_flags=[],
            )
            for i in range(54 * 12)
        )

    def build(probabilities: dict | None, site=SITE):
        clock = Clock(RUN_AT + timedelta(seconds=30))
        emailer = FakeEmailer()
        engine = AlertEngine(site, load_env_settings(), session_factory, hub, emailer, clock=clock)
        runner = InferenceRunner(
            site, session_factory, FakeModelStore(probabilities), hub, engine, clock=clock
        )
        return runner, emailer, clock

    return build


async def all_alerts(session_factory) -> list[tuple]:
    async with session_factory() as session:
        rows = await session.execute(select(Alert).order_by(Alert.id))
        return [(a.hazard, a.level, a.email_status) for a in rows.scalars()]


async def count(session_factory, model) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_predictions_are_stored_and_rerun_overwrites(session_factory, stack, hub):
    runner, _, _ = stack(levels())
    first = await runner.run(RUN_AT)
    second = await runner.run(RUN_AT)
    assert [p.status for p in first] == ["ok", "ok"]
    assert [p.id for p in first] == [p.id for p in second]
    assert await count(session_factory, Prediction) == 2
    assert len(hub.of_type("prediction")) == 4


async def test_missing_data_gives_insufficient_and_no_alert(session_factory, stack):
    runner, emailer, _ = stack(levels(wind="red"))
    results = await runner.run(RUN_AT + 9 * HOUR)  # last reading 3 h earlier
    assert {p.status for p in results} == {"insufficient_data"}
    assert results[0].context["reason"] == "no reading in the last 60 min"
    assert await all_alerts(session_factory) == []
    assert emailer.sent == []


async def test_missing_model_gives_insufficient(session_factory, stack):
    runner, _, _ = stack(None)
    results = await runner.run(RUN_AT)
    assert {p.context["reason"] for p in results} == {"no_model"}


async def test_yellow_does_not_alert(session_factory, stack):
    runner, emailer, _ = stack(levels(wind="yellow"))
    await runner.run(RUN_AT)
    assert await all_alerts(session_factory) == []


async def test_cooldown_and_escalation(session_factory, stack):
    runner, emailer, clock = stack(levels(wind="orange"))
    probabilities = runner._models.loaded.models["wind_yellow"]._probabilities

    await runner.run(RUN_AT)  # Orange: sent
    clock.now += HOUR
    await runner.run(RUN_AT + HOUR)  # Orange again within 3 h: cooldown
    probabilities.update(levels(wind="red"))
    clock.now += HOUR
    await runner.run(RUN_AT + 2 * HOUR)  # escalation to Red: sent immediately
    probabilities.update(levels(wind="orange"))
    clock.now += 3 * HOUR
    await runner.run(RUN_AT + 5 * HOUR)  # 3 h after the Red email: cooldown over

    assert await all_alerts(session_factory) == [
        ("wind", "orange", "sent"),
        ("wind", "orange", "cooldown"),
        ("wind", "red", "sent"),
        ("wind", "orange", "sent"),
    ]
    assert [e.subject for e in emailer.sent][:2] == [
        "[ORANGE] Wind risk at Karur Campus — next 3 h",
        "[RED] Wind risk at Karur Campus — next 3 h",
    ]


async def test_hazards_have_separate_cooldowns(session_factory, stack):
    runner, emailer, _ = stack(levels(wind="orange", heat="orange"))
    await runner.run(RUN_AT)
    assert await all_alerts(session_factory) == [
        ("wind", "orange", "sent"),
        ("heat", "orange", "sent"),
    ]


async def test_failed_email_is_recorded_and_retried_next_hour(session_factory, stack):
    runner, emailer, clock = stack(levels(wind="red"))
    emailer.fail = True
    await runner.run(RUN_AT)
    emailer.fail = False
    clock.now += HOUR
    await runner.run(RUN_AT + HOUR)
    assert await all_alerts(session_factory) == [("wind", "red", "failed"), ("wind", "red", "sent")]
    async with session_factory() as session:
        error = await session.scalar(select(Alert.error).where(Alert.email_status == "failed"))
    assert "SMTP server not reachable" in error


async def test_disabled_alerts_are_recorded_without_email(session_factory, stack):
    site = SITE.model_copy(update={"alerts": SITE.alerts.model_copy(update={"enabled": False})})
    runner, emailer, _ = stack(levels(wind="red"), site=site)
    await runner.run(RUN_AT)
    assert await all_alerts(session_factory) == [("wind", "red", "disabled")]
    assert emailer.sent == []


async def test_alert_email_content(session_factory, stack):
    runner, emailer, _ = stack(levels(heat="orange"))
    await runner.run(RUN_AT)
    email = emailer.sent[0]
    assert email.subject == "[ORANGE] Heat risk at Karur Campus — next 3 h"
    assert "Severe heat wave is likely at Karur Campus in the next 3 hours." in email.text
    assert "10 May 2026, 17:00 IST" in email.text  # valid until 14:00 + 3 h
    assert "70 %" in email.text
    assert "35.0 °C" in email.text  # latest reading
    assert "trained on synthetic data" in email.text
    assert "<h1" in email.html and "Severe heat wave" in email.html


def test_render_escapes_html():
    email = render_alert_email(
        site_name="<Campus>",
        timezone="Asia/Kolkata",
        kit_id="kit01",
        kit_description="",
        hazard="wind",
        level="red",
        probabilities=dict.fromkeys(("yellow", "orange", "red"), 0.9),
        thresholds=dict.fromkeys(("yellow", "orange", "red"), "x"),
        run_at=RUN_AT,
        valid_until=RUN_AT + 3 * HOUR,
        reading=None,
        model_version="v1",
        synthetic_model=False,
        fallback_used=True,
        dashboard_url="http://localhost:5173",
        horizon_hours=3,
        cooldown_hours=3,
    )
    assert "&lt;Campus&gt;" in email.html
    assert "DHT11" in email.text
    assert len(LABELS) == 6
