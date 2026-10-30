"""MQTT subscriber task (FR-ING-01, design §6.1).

Connects with a persistent session (fixed client id, clean_session=False) so the
broker queues QoS 1 readings while the backend is restarting. Reconnects with
back-off and never lets one bad message stop the loop.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import aiomqtt

from backend.app.mqtt.payload import STATUS_FILTER, TELEMETRY_FILTER, parse_topic
from backend.app.settings import EnvSettings

log = logging.getLogger(__name__)

Handler = Callable[[str, bytes], Awaitable[object]]

CLIENT_ID = "weather-backend"
MAX_BACKOFF_S = 30


class MqttSubscriber:
    def __init__(self, env: EnvSettings, on_telemetry: Handler, on_status: Handler) -> None:
        self._env = env
        self._on_telemetry = on_telemetry
        self._on_status = on_status
        self.connected = False

    async def run(self) -> None:
        backoff = 1
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self._env.mqtt_host,
                    port=self._env.mqtt_port,
                    username=self._env.mqtt_username,
                    password=self._env.mqtt_password.get_secret_value(),
                    identifier=CLIENT_ID,
                    clean_session=False,
                    keepalive=60,
                ) as client:
                    await client.subscribe([(TELEMETRY_FILTER, 1), (STATUS_FILTER, 1)])
                    self.connected = True
                    backoff = 1
                    log.info("MQTT connected to %s:%s", self._env.mqtt_host, self._env.mqtt_port)
                    async for message in client.messages:
                        await self._dispatch(message.topic.value, message.payload)
            except aiomqtt.MqttError as exc:
                log.warning("MQTT connection problem: %s — retrying in %d s", exc, backoff)
            finally:
                self.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)

    async def _dispatch(self, topic: str, payload) -> None:
        parsed = parse_topic(topic)
        if parsed is None:
            log.warning("Message on unexpected topic '%s' ignored", topic)
            return
        kit_id, kind = parsed
        if not isinstance(payload, bytes | bytearray):
            payload = str(payload or "").encode()
        try:
            if kind == "telemetry":
                await self._on_telemetry(kit_id, bytes(payload))
            else:
                await self._on_status(kit_id, bytes(payload))
        except Exception:
            log.exception("Error while handling message on '%s'", topic)
