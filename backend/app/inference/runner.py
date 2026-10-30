"""Hourly inference (FR-INF-01..04, design §10.2).

sufficiency check → 5-min grid → hourly → features → 6 probabilities →
monotonic fix → level → store → broadcast → alert engine

:func:`assess_sufficiency` and :func:`predict` are pure (no database) and are
unit-tested on their own.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.inference.model_store import ModelStore
from backend.app.inference.prediction import INSUFFICIENT, OK, HazardPrediction
from backend.app.models import Prediction, Reading
from backend.app.settings import SiteConfig
from backend.app.ws.hub import WebSocketHub
from ml.core.aggregate import to_grid, to_hourly
from ml.core.features import build_features
from ml.core.levels import LEVELS, make_monotonic, select_level
from ml.registry import LoadedModels

log = logging.getLogger(__name__)

HAZARDS = ("wind", "heat")
SLOT = timedelta(minutes=5)
SLOTS_PER_DAY = 24 * 12
READING_COLUMNS = (
    "ts",
    "temp_c",
    "hum_pct",
    "pressure_hpa",
    "wind_speed_ms",
    "fallback",
    "qc_flags",
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def hour_boundary(now: datetime, timezone: str) -> datetime:
    """Start of the current site-local clock hour, in UTC."""
    local = now.astimezone(ZoneInfo(timezone)).replace(minute=0, second=0, microsecond=0)
    return local.astimezone(UTC)


@dataclass(frozen=True)
class Sufficiency:
    ok: bool
    missing_share_24h: float
    minutes_since_last: float | None
    reason: str | None = None


def assess_sufficiency(readings: pd.DataFrame, run_at: datetime, rules) -> Sufficiency:
    """FR-INF-02: enough data in the last 24 h and a recent reading."""
    day = readings[readings["ts"] >= run_at - timedelta(hours=24)]
    observed_slots = day["ts"].dt.floor(SLOT).nunique()
    missing = round(1 - min(1.0, observed_slots / SLOTS_PER_DAY), 3)
    since = None if readings.empty else (run_at - readings["ts"].max()).total_seconds() / 60
    if since is None or since > rules.require_data_within_min:
        reason = f"no reading in the last {rules.require_data_within_min} min"
        return Sufficiency(False, missing, since, reason)
    if missing > rules.max_missing_share_24h:
        reason = f"{missing:.0%} of the last 24 h is missing"
        return Sufficiency(False, missing, since, reason)
    return Sufficiency(True, missing, since)


def insufficient(kit_id: str, run_at: datetime, horizon: timedelta, context: dict) -> list:
    return [
        HazardPrediction(
            kit_id=kit_id,
            run_at=run_at,
            hazard=hazard,
            status=INSUFFICIENT,
            valid_until=run_at + horizon,
            context=context,
        )
        for hazard in HAZARDS
    ]


def predict(
    kit_id: str,
    readings: pd.DataFrame,
    run_at: datetime,
    site: SiteConfig,
    loaded: LoadedModels,
    sufficiency: Sufficiency,
) -> list[HazardPrediction]:
    """Predictions for both hazards at ``run_at`` from readings before it."""
    horizon = timedelta(hours=site.prediction.horizon_hours)
    start = pd.Timestamp(run_at) - pd.Timedelta(hours=site.prediction.history_hours)
    grid = to_grid(
        readings,
        site.data_sufficiency.max_interp_gap_min,
        start=start,
        end=pd.Timestamp(run_at) - SLOT,
    )
    hourly = to_hourly(grid, site.site.timezone)
    features = build_features(hourly, site)
    t = pd.Timestamp(run_at)
    if t not in features.index:
        return insufficient(kit_id, run_at, horizon, {"reason": "no features for this hour"})
    x = features.loc[[t], loaded.metadata["feature_list"]]

    recent = readings[readings["ts"] >= run_at - timedelta(hours=24)]
    fallback_used = bool(recent["fallback"].any())
    context = {
        "tmax_normal_c": round(float(x["tmax_normal"].iloc[0]), 1),
        "missing_share_24h": sufficiency.missing_share_24h,
        "minutes_since_last_reading": round(sufficiency.minutes_since_last or 0, 1),
    }
    results = []
    for hazard in HAZARDS:
        raw = {
            level: float(loaded.models[f"{hazard}_{level}"].predict_proba(x)[0, 1])
            for level in LEVELS
        }
        probabilities = {k: round(v, 4) for k, v in make_monotonic(raw).items()}
        results.append(
            HazardPrediction(
                kit_id=kit_id,
                run_at=run_at,
                hazard=hazard,
                status=OK,
                valid_until=run_at + horizon,
                probabilities=probabilities,
                level=select_level(probabilities, site.prediction.show_level_cutoff),
                model_version=loaded.version,
                fallback_used=fallback_used,
                context=context,
            )
        )
    return results


class InferenceRunner:
    def __init__(
        self,
        site: SiteConfig,
        session_factory: async_sessionmaker[AsyncSession],
        model_store: ModelStore,
        hub: WebSocketHub,
        alert_engine,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._site = site
        self._sessions = session_factory
        self._models = model_store
        self._hub = hub
        self._alerts = alert_engine
        self._clock = clock
        self.last_run: datetime | None = None

    async def run(self, run_at: datetime | None = None) -> list[HazardPrediction]:
        """Predict for every enabled kit at the given (or current) hour."""
        run_at = run_at or hour_boundary(self._clock(), self._site.site.timezone)
        results: list[HazardPrediction] = []
        for kit in self._site.enabled_kits:
            try:
                results += await self.run_kit(kit.kit_id, run_at)
            except Exception:
                log.exception("Prediction for kit '%s' at %s failed", kit.kit_id, run_at)
        self.last_run = self._clock()
        return results

    async def run_kit(self, kit_id: str, run_at: datetime) -> list[HazardPrediction]:
        horizon = timedelta(hours=self._site.prediction.horizon_hours)
        readings = await self._load_readings(kit_id, run_at)
        sufficiency = assess_sufficiency(readings, run_at, self._site.data_sufficiency)
        loaded = self._models.loaded
        if loaded is None:
            predictions = insufficient(
                kit_id, run_at, horizon, {"reason": "no_model", "detail": self._models.error}
            )
        elif not sufficiency.ok:
            predictions = insufficient(
                kit_id,
                run_at,
                horizon,
                {"reason": sufficiency.reason, "missing_share_24h": sufficiency.missing_share_24h},
            )
        else:
            predictions = await asyncio.to_thread(
                predict, kit_id, readings, run_at, self._site, loaded, sufficiency
            )

        for prediction in predictions:
            await self._store(prediction)
            log.info(
                "Kit '%s' %s at %s: %s %s",
                kit_id,
                prediction.hazard,
                run_at.isoformat(),
                prediction.status,
                prediction.level or "",
            )
            await self._hub.broadcast("prediction", prediction.to_message())
            await self._alerts.evaluate(prediction)
        return predictions

    async def _load_readings(self, kit_id: str, run_at: datetime) -> pd.DataFrame:
        since = run_at - timedelta(hours=self._site.prediction.history_hours)
        columns = [getattr(Reading, name) for name in READING_COLUMNS]
        async with self._sessions() as session:
            result = await session.execute(
                select(*columns)
                .where(Reading.kit_id == kit_id, Reading.ts >= since, Reading.ts < run_at)
                .order_by(Reading.ts)
            )
            rows = result.all()
        frame = pd.DataFrame(rows, columns=list(READING_COLUMNS))
        if frame.empty:
            return frame.astype({"ts": "datetime64[us, UTC]"})
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
        for name in ("temp_c", "hum_pct", "pressure_hpa", "wind_speed_ms"):
            frame[name] = frame[name].astype(float)
        return frame

    async def _store(self, prediction: HazardPrediction) -> None:
        p = prediction.probabilities or {}
        values = {
            "status": prediction.status,
            "p_yellow": p.get("yellow"),
            "p_orange": p.get("orange"),
            "p_red": p.get("red"),
            "level": prediction.level,
            "valid_until": prediction.valid_until,
            "model_version": prediction.model_version,
            "fallback_used": prediction.fallback_used,
            "context": prediction.context,
        }
        statement = (
            insert(Prediction)
            .values(
                kit_id=prediction.kit_id,
                run_at=prediction.run_at,
                hazard=prediction.hazard,
                **values,
            )
            .on_conflict_do_update(
                index_elements=[Prediction.kit_id, Prediction.hazard, Prediction.run_at],
                set_=values,
            )
            .returning(Prediction.id)
        )
        async with self._sessions() as session, session.begin():
            prediction.id = (await session.execute(statement)).scalar_one()
