"""Telemetry ingestion (FR-ING-01..03, FR-QC-01..05, design §6.1).

validate → timestamp rules → QC → fusion → store → kit status → broadcast

:func:`prepare_reading` is the pure part (no database) and is unit-tested on its
own; :class:`IngestPipeline` adds history, storage and broadcasting.
"""

import bisect
import logging
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.ingest.kit_status import KitStatusService
from backend.app.models import Reading
from backend.app.mqtt.payload import TelemetryPayload
from backend.app.settings import SiteConfig
from backend.app.ws.hub import WebSocketHub
from ml.core.fusion import fuse
from ml.core.qc import SENSOR_FIELDS, TS_MISSING, QcLimits, QcReading, check_reading

log = logging.getLogger(__name__)

RAW_FIELDS = (*SENSOR_FIELDS, "wind_gust_ms", "rain_mm")


class Rejected(Exception):
    """The message is not stored; the reason is logged."""


@dataclass(frozen=True)
class PreparedReading:
    kit_id: str
    ts: datetime
    ts_source: str  # kit / arrival
    received_at: datetime
    values: dict[str, float | None]  # raw values keyed by RAW_FIELDS
    temp_c: float | None
    hum_pct: float | None
    fallback: bool
    qc_flags: list[str]
    fw_version: str | None

    def to_row(self) -> dict:
        row = asdict(self)
        row.update(row.pop("values"))
        return row

    def to_message(self) -> dict:
        """Live update sent to dashboards."""
        return self.to_row()


def prepare_reading(
    kit_id: str,
    raw: bytes,
    received_at: datetime,
    history: Sequence[QcReading],
    site: SiteConfig,
    limits: QcLimits,
) -> PreparedReading:
    """Validate and check one telemetry message. Raises :class:`Rejected`."""
    try:
        payload = TelemetryPayload.model_validate_json(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'payload'}: {e['msg']}"
            for e in exc.errors()[:3]
        )
        raise Rejected(f"invalid payload ({problems})") from None

    flags: list[str] = []
    if payload.ts is None:
        ts, ts_source = received_at, "arrival"
        flags.append(TS_MISSING)
    else:
        ts, ts_source = payload.ts, "kit"
        tolerance = timedelta(minutes=site.qc.future_ts_tolerance_min)
        if ts > received_at + tolerance:
            raise Rejected(f"timestamp {ts.isoformat()} is more than {tolerance} in the future")

    values = payload.sensor_values()
    flags += check_reading(ts, values, history, limits)
    fusion = fuse(values, flags, site.qc.fusion_mismatch.model_dump())
    flags += fusion.flags

    return PreparedReading(
        kit_id=kit_id,
        ts=ts,
        ts_source=ts_source,
        received_at=received_at,
        values={name: values.get(name) for name in RAW_FIELDS},
        temp_c=fusion.temp_c,
        hum_pct=fusion.hum_pct,
        fallback=fusion.fallback,
        qc_flags=flags,
        fw_version=payload.fw_version,
    )


class _RateLimitedLog:
    """Logs a repeated warning at most once per interval per key."""

    def __init__(self, interval_s: float = 60) -> None:
        self._interval = interval_s
        self._last: dict[str, float] = {}
        self._suppressed: dict[str, int] = defaultdict(int)

    def warning(self, key: str, message: str, *args) -> None:
        now = time.monotonic()
        if now - self._last.get(key, -self._interval) < self._interval:
            self._suppressed[key] += 1
            return
        suppressed = self._suppressed.pop(key, 0)
        suffix = f" ({suppressed} similar messages suppressed)" if suppressed else ""
        log.warning(message + suffix, *args)
        self._last[key] = now


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IngestPipeline:
    def __init__(
        self,
        site: SiteConfig,
        session_factory: async_sessionmaker[AsyncSession],
        kit_status: KitStatusService,
        hub: WebSocketHub,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._site = site
        self._sessions = session_factory
        self._kit_status = kit_status
        self._hub = hub
        self._clock = clock
        self._limits = QcLimits.from_config(site.qc)
        self._history: dict[str, list[QcReading]] = defaultdict(list)
        self._warn = _RateLimitedLog()

    async def load_history(self) -> None:
        """Fill the QC history from the database so checks work across restarts."""
        since = self._clock() - self._limits.history_window
        async with self._sessions() as session:
            for kit in self._site.enabled_kits:
                result = await session.execute(
                    select(Reading)
                    .where(Reading.kit_id == kit.kit_id, Reading.ts >= since)
                    .order_by(Reading.ts)
                )
                self._history[kit.kit_id] = [
                    QcReading(
                        ts=row.ts,
                        values={name: getattr(row, name) for name in SENSOR_FIELDS},
                        flags=frozenset(row.qc_flags),
                    )
                    for row in result.scalars()
                ]

    async def handle_telemetry(
        self, kit_id: str, raw: bytes, received_at: datetime | None = None
    ) -> PreparedReading | None:
        """Process one telemetry message. Returns the stored reading, or None."""
        received_at = received_at or self._clock()
        kit = self._site.kit(kit_id)
        if kit is None or not kit.enabled:
            self._warn.warning(
                f"unknown:{kit_id}", "Telemetry from unknown/disabled kit '%s'", kit_id
            )
            return None

        try:
            reading = prepare_reading(
                kit_id, raw, received_at, self._history[kit_id], self._site, self._limits
            )
        except Rejected as exc:
            self._warn.warning(f"rejected:{kit_id}", "Kit '%s': reading rejected: %s", kit_id, exc)
            return None

        try:
            async with self._sessions() as session, session.begin():
                statement = (
                    insert(Reading)
                    .values(**reading.to_row())
                    .on_conflict_do_nothing(index_elements=[Reading.kit_id, Reading.ts])
                    .returning(Reading.id)
                )
                inserted = (await session.execute(statement)).scalar_one_or_none()
        except (SQLAlchemyError, OSError) as exc:
            self._warn.warning("db", "Database unavailable, reading dropped: %s", exc)
            return None
        if inserted is None:
            log.info("Kit '%s': duplicate reading at %s ignored", kit_id, reading.ts.isoformat())
            return None

        self._remember(reading)
        await self._kit_status.reading_received(kit_id, received_at, reading.fw_version)
        await self._hub.broadcast("reading", reading.to_message())
        return reading

    def _remember(self, reading: PreparedReading) -> None:
        history = self._history[reading.kit_id]
        entry = QcReading(
            ts=reading.ts,
            values={name: reading.values[name] for name in SENSOR_FIELDS},
            flags=frozenset(reading.qc_flags),
        )
        bisect.insort(history, entry, key=lambda r: r.ts)
        cutoff = history[-1].ts - self._limits.history_window
        while history and history[0].ts < cutoff:
            history.pop(0)
