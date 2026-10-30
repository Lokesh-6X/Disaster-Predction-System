"""Kit online/offline status (FR-ING-04, design §6.5).

Sources of status changes:
- ``mqtt_status``: the kit's retained status message or Last-Will,
- ``telemetry``: a reading arrived from a kit that was not online,
- ``watchdog``: no reading for ``kit_status.offline_after_min`` minutes.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.models import Kit, KitStatusLog
from backend.app.settings import SiteConfig
from backend.app.ws.hub import WebSocketHub

log = logging.getLogger(__name__)

ONLINE = "online"
OFFLINE = "offline"


def utcnow() -> datetime:
    return datetime.now(UTC)


class KitStatusService:
    def __init__(
        self,
        site: SiteConfig,
        session_factory: async_sessionmaker[AsyncSession],
        hub: WebSocketHub,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._site = site
        self._sessions = session_factory
        self._hub = hub
        self._clock = clock
        self._offline_after = timedelta(minutes=site.kit_status.offline_after_min)

    async def sync_kits(self) -> None:
        """Insert or update the kits table from site.yaml."""
        async with self._sessions() as session, session.begin():
            for kit in self._site.kits:
                values = {
                    "description": kit.description,
                    "latitude": kit.latitude,
                    "longitude": kit.longitude,
                    "anemometer_height_m": kit.anemometer_height_m,
                    "enabled": kit.enabled,
                }
                statement = insert(Kit).values(kit_id=kit.kit_id, **values)
                statement = statement.on_conflict_do_update(
                    index_elements=[Kit.kit_id], set_={**values, "updated_at": func.now()}
                )
                await session.execute(statement)
        log.info("Synced %d kit(s) from site.yaml", len(self._site.kits))

    async def handle_status_message(self, kit_id: str, payload: bytes) -> None:
        if self._site.kit(kit_id) is None:
            log.warning("Status message from unknown kit '%s' ignored", kit_id)
            return
        status = payload.decode("utf-8", errors="replace").strip().lower()
        if status not in (ONLINE, OFFLINE):
            log.warning("Kit '%s' sent unknown status '%s'", kit_id, status[:40])
            return
        await self._set_status(kit_id, status, "mqtt_status")

    async def reading_received(
        self, kit_id: str, received_at: datetime, fw_version: str | None
    ) -> None:
        values: dict = {"last_seen": received_at}
        if fw_version:
            values["fw_version"] = fw_version
        async with self._sessions() as session, session.begin():
            await session.execute(update(Kit).where(Kit.kit_id == kit_id).values(**values))
        await self._set_status(kit_id, ONLINE, "telemetry")

    async def check_offline(self) -> list[str]:
        """Mark online kits offline when nothing has arrived recently. Returns their ids."""
        cutoff = self._clock() - self._offline_after
        async with self._sessions() as session:
            result = await session.execute(
                select(Kit.kit_id).where(
                    Kit.status == ONLINE,
                    func.coalesce(Kit.last_seen, Kit.updated_at) < cutoff,
                )
            )
            stale = list(result.scalars())
        for kit_id in stale:
            await self._set_status(kit_id, OFFLINE, "watchdog")
        return stale

    async def run_watchdog(self, interval_s: float = 60) -> None:
        while True:
            try:
                await self.check_offline()
            except Exception:
                log.exception("Kit watchdog check failed")
            await asyncio.sleep(interval_s)

    async def _set_status(self, kit_id: str, status: str, source: str) -> None:
        now = self._clock()
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(Kit)
                .where(Kit.kit_id == kit_id, Kit.status != status)
                .values(status=status, updated_at=now)
                .returning(Kit.kit_id)
            )
            if result.scalar_one_or_none() is None:
                return  # unchanged (or unknown kit)
            session.add(KitStatusLog(kit_id=kit_id, ts=now, status=status, source=source))
        log.info("Kit '%s' is now %s (%s)", kit_id, status, source)
        await self._hub.broadcast(
            "kit_status", {"kit_id": kit_id, "status": status, "ts": now, "source": source}
        )
