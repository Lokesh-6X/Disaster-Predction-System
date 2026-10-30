"""Alert engine: trigger, cooldown and escalation (FR-ALT-01..06, design §11).

For each prediction at an alert level (default Orange/Red):
- alerts switched off              → recorded as ``disabled``
- nothing sent for this hazard in the cooldown, or the level is higher than
  the last one sent               → email; ``sent`` or ``failed``
- otherwise                        → recorded as ``cooldown``
A failed send does not start a cooldown, so the next hour tries again.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.alerts.emailer import Emailer, render_alert_email
from backend.app.inference.prediction import OK, HazardPrediction
from backend.app.models import Alert, Reading
from backend.app.settings import EnvSettings, SiteConfig
from backend.app.ws.hub import WebSocketHub
from ml.core.levels import RANK

log = logging.getLogger(__name__)

SENT, COOLDOWN, FAILED, DISABLED = "sent", "cooldown", "failed", "disabled"


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class AlertRecord:
    id: int
    prediction_id: int
    kit_id: str
    hazard: str
    level: str
    probability: float
    valid_until: datetime
    email_status: str
    error: str | None
    created_at: datetime
    sent_at: datetime | None

    def to_message(self) -> dict:
        return dict(self.__dict__)


class AlertEngine:
    def __init__(
        self,
        site: SiteConfig,
        env: EnvSettings,
        session_factory: async_sessionmaker[AsyncSession],
        hub: WebSocketHub,
        emailer: Emailer,
        clock: Callable[[], datetime] = utcnow,
        is_synthetic_model: Callable[[], bool] = lambda: True,
    ) -> None:
        self._site = site
        self._env = env
        self._sessions = session_factory
        self._hub = hub
        self._emailer = emailer
        self._clock = clock
        self._is_synthetic_model = is_synthetic_model

    async def evaluate(self, prediction: HazardPrediction) -> AlertRecord | None:
        alerts = self._site.alerts
        if prediction.status != OK or prediction.level not in alerts.levels:
            return None
        now = self._clock()
        last_level = await self._last_sent_level(
            prediction.kit_id, prediction.hazard, now - timedelta(hours=alerts.cooldown_hours)
        )
        error = None
        sent_at = None
        if not alerts.enabled:
            status = DISABLED
        elif last_level is None or RANK[prediction.level] > RANK[last_level]:
            try:
                await self._emailer.send(await self._render(prediction))
                status, sent_at = SENT, self._clock()
            except Exception as exc:  # SMTP, network, timeout: record and carry on
                status, error = FAILED, f"{type(exc).__name__}: {exc}"[:500]
                log.error("Alert email failed: %s", error)
        else:
            status = COOLDOWN

        record = await self._store(prediction, status, error, now, sent_at)
        log.info(
            "Alert %s %s for kit '%s': %s",
            prediction.hazard,
            prediction.level,
            prediction.kit_id,
            status,
        )
        await self._hub.broadcast("alert", record.to_message())
        return record

    async def _last_sent_level(self, kit_id: str, hazard: str, since: datetime) -> str | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(Alert.level)
                .where(
                    Alert.kit_id == kit_id,
                    Alert.hazard == hazard,
                    Alert.email_status == SENT,
                    Alert.created_at > since,
                )
                .order_by(Alert.created_at.desc())
                .limit(1)
            )

    async def _render(self, prediction: HazardPrediction):
        kit = self._site.kit(prediction.kit_id)
        wind = self._site.hazards.wind.levels
        heat = self._site.hazards.heat
        abs_c = self._site.heat_abs_threshold_c
        thresholds = {
            "wind": {
                "yellow": f"≥ {wind.yellow:g} km/h",
                "orange": f"≥ {wind.orange:g} km/h",
                "red": f"≥ {wind.red:g} km/h",
            },
            "heat": {
                "yellow": f"≥ {abs_c:g} °C and +{heat.departure_c.yellow:g} °C",
                "orange": f"≥ {abs_c:g} °C and +{heat.departure_c.orange:g} °C",
                "red": f"≥ {heat.red_abs_c:g} °C",
            },
        }[prediction.hazard]
        return render_alert_email(
            site_name=self._site.site.name,
            timezone=self._site.site.timezone,
            kit_id=prediction.kit_id,
            kit_description=kit.description if kit else "",
            hazard=prediction.hazard,
            level=prediction.level,
            probabilities=prediction.probabilities,
            thresholds=thresholds,
            run_at=prediction.run_at,
            valid_until=prediction.valid_until,
            reading=await self._latest_reading(prediction.kit_id),
            model_version=prediction.model_version,
            synthetic_model=self._is_synthetic_model(),
            fallback_used=prediction.fallback_used,
            dashboard_url=self._env.frontend_url,
            horizon_hours=self._site.prediction.horizon_hours,
            cooldown_hours=self._site.alerts.cooldown_hours,
        )

    async def _latest_reading(self, kit_id: str) -> dict | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(Reading).where(Reading.kit_id == kit_id).order_by(Reading.ts.desc()).limit(1)
            )
        if row is None:
            return None

        def fmt(value, unit: str, scale: float = 1.0, digits: int = 1) -> str:
            return "—" if value is None else f"{value * scale:.{digits}f} {unit}"

        return {
            "ts": row.ts,
            "temp": fmt(row.temp_c, "°C"),
            "hum": fmt(row.hum_pct, "%", digits=0),
            "pressure": fmt(row.pressure_hpa, "hPa"),
            "wind": fmt(row.wind_speed_ms, "km/h", scale=3.6, digits=0),
        }

    async def _store(
        self,
        prediction: HazardPrediction,
        status: str,
        error: str | None,
        created_at: datetime,
        sent_at: datetime | None,
    ) -> AlertRecord:
        alert = Alert(
            prediction_id=prediction.id,
            kit_id=prediction.kit_id,
            hazard=prediction.hazard,
            level=prediction.level,
            probability=prediction.probabilities[prediction.level],
            valid_until=prediction.valid_until,
            email_status=status,
            error=error,
            created_at=created_at,
            sent_at=sent_at,
        )
        async with self._sessions() as session, session.begin():
            session.add(alert)
            await session.flush()
            alert_id = alert.id
        return AlertRecord(
            id=alert_id,
            prediction_id=prediction.id,
            kit_id=prediction.kit_id,
            hazard=prediction.hazard,
            level=prediction.level,
            probability=prediction.probabilities[prediction.level],
            valid_until=prediction.valid_until,
            email_status=status,
            error=error,
            created_at=created_at,
            sent_at=sent_at,
        )
