"""Kit simulator: publishes readings in the kit's MQTT format (FR-SIM-01).

Uses a simple daily-cycle model based on the climate normals in site.yaml.
(Phase 3 replaces it with the synthetic generator's model and adds forced hazards.)

Examples (from the project root):
    .venv\\Scripts\\python.exe tools\\kit_simulator.py                      # live, every 5 min
    .venv\\Scripts\\python.exe tools\\kit_simulator.py --interval 10s
    .venv\\Scripts\\python.exe tools\\kit_simulator.py --backfill-hours 48 --speed 600
    .venv\\Scripts\\python.exe tools\\kit_simulator.py --no-ts --faults
    .venv\\Scripts\\python.exe tools\\kit_simulator.py --drop-after 3       # test Last-Will

With --backfill-hours the simulated clock starts in the past and runs --speed
times faster until it catches up with real time, then continues live. (The
server rejects timestamps in the future, so the clock never runs ahead.)
"""

import argparse
import json
import math
import os
import random
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root

import paho.mqtt.client as mqtt  # noqa: E402

from backend.app.settings import (  # noqa: E402
    ConfigError,
    SiteConfig,
    load_env_settings,
    load_site_config,
)

FW_VERSION = "sim-0.1"
PRESSURE_DROP_PER_M = 0.12  # hPa per metre of elevation, near sea level


def parse_interval(text: str) -> timedelta:
    match = re.fullmatch(r"(\d+)\s*([sm])", text.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError("use e.g. 60s or 5m")
    amount, unit = int(match[1]), match[2]
    return timedelta(seconds=amount) if unit == "s" else timedelta(minutes=amount)


def daily_shape(hour: float) -> float:
    """0 at about 06:00, 1 at about 14:30, smooth decay overnight."""
    if 6 <= hour <= 14.5:
        return (1 - math.cos(math.pi * (hour - 6) / 8.5)) / 2
    fraction = ((hour - 14.5) % 24) / 15.5
    return (1 + math.cos(math.pi * fraction)) / 2


class WeatherModel:
    def __init__(self, site: SiteConfig, rng: random.Random, faults: bool) -> None:
        self._site = site
        self._tz = ZoneInfo(site.site.timezone)
        self._rng = rng
        self._faults = faults
        self._dht_bias = rng.uniform(-1.0, 1.0)

    def reading(self, ts: datetime) -> dict:
        n = self._site.normals
        local = ts.astimezone(self._tz)
        month = local.month - 1
        hour = local.hour + local.minute / 60
        shape = daily_shape(hour)
        gauss = self._rng.gauss

        temp = n.tmin_c[month] + (n.tmax_c[month] - n.tmin_c[month]) * shape + gauss(0, 0.3)
        rh = n.rh_morning_pct[month] + (n.rh_evening_pct[month] - n.rh_morning_pct[month]) * shape
        rh = min(100.0, max(5.0, rh + gauss(0, 2)))
        pressure = (
            n.mslp_hpa[month]
            - self._site.site.elevation_m * PRESSURE_DROP_PER_M
            + 1.5 * math.cos(2 * math.pi * (hour - 10) / 12)
            + gauss(0, 0.1)
        )
        wind_kmh = n.wind_kmh[month] * (0.5 + shape) * self._rng.gammavariate(4, 0.25)
        wind = max(0.0, wind_kmh / 3.6)

        values = {
            "temp_bme_c": round(temp, 2),
            "hum_bme_pct": round(rh, 1),
            "pressure_hpa": round(pressure, 2),
            "temp_dht_c": round(temp + self._dht_bias + gauss(0, 0.5)),
            "hum_dht_pct": round(rh + 2 * self._dht_bias + gauss(0, 1.5)),
            "wind_speed_ms": round(wind, 1),
            "wind_gust_ms": None,
            "rain_mm": None,
        }
        if self._faults:
            self._inject_fault(values)
        return values

    def _inject_fault(self, values: dict) -> None:
        roll = self._rng.random()
        if roll < 0.02:
            field = self._rng.choice(["temp_bme_c", "hum_bme_pct", "pressure_hpa"])
            values[field] = round(values[field] + self._rng.choice([-1, 1]) * 20, 2)
        elif roll < 0.03:
            values.update(temp_bme_c=None, hum_bme_pct=None, pressure_hpa=None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish simulated kit readings over MQTT.")
    parser.add_argument("--kit", default="kit01", help="kit_id (default kit01)")
    parser.add_argument("--interval", type=parse_interval, default=timedelta(minutes=5))
    parser.add_argument("--speed", type=float, default=1.0, help="time acceleration for backfill")
    parser.add_argument("--backfill-hours", type=float, default=0.0)
    parser.add_argument("--count", type=int, default=0, help="stop after N readings (0 = run)")
    parser.add_argument("--no-ts", action="store_true", help="omit ts (server uses arrival time)")
    parser.add_argument("--faults", action="store_true", help="inject occasional spikes/nulls")
    parser.add_argument(
        "--drop-after", type=int, default=0, help="vanish without disconnecting after N readings"
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # --drop-after exits without flushing

    try:
        site = load_site_config()
        env = load_env_settings()
    except ConfigError as exc:
        sys.exit(f"Configuration error:\n{exc}")
    if site.kit(args.kit) is None:
        sys.exit(f"Kit '{args.kit}' is not in config/site.yaml")
    if args.kit != env.mqtt_kit_username:
        print(
            f"Note: logging in as '{env.mqtt_kit_username}'; the broker only lets it publish "
            f"under weather/kit/{env.mqtt_kit_username}/"
        )

    model = WeatherModel(site, random.Random(args.seed), args.faults)
    telemetry_topic = f"weather/kit/{args.kit}/telemetry"
    status_topic = f"weather/kit/{args.kit}/status"

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=args.kit, clean_session=True)
    client.username_pw_set(env.mqtt_kit_username, env.mqtt_kit_password.get_secret_value())
    client.will_set(status_topic, "offline", qos=1, retain=True)
    host, port = args.host or env.mqtt_host, args.port or env.mqtt_port
    client.connect(host, port, keepalive=15 if args.drop_after else 60)
    client.loop_start()
    client.publish(status_topic, "online", qos=1, retain=True).wait_for_publish(5)
    print(f"Connected to {host}:{port} as '{args.kit}'; publishing to {telemetry_topic}")

    sim_time = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=args.backfill_hours)
    sent = 0
    try:
        while True:
            payload = model.reading(sim_time)
            if not args.no_ts:
                payload = {"ts": sim_time.isoformat().replace("+00:00", "Z"), **payload}
            payload["fw_version"] = FW_VERSION
            client.publish(telemetry_topic, json.dumps(payload), qos=1).wait_for_publish(5)
            sent += 1
            print(
                f"{sent:5d}  {sim_time:%Y-%m-%d %H:%M} UTC  "
                f"T={payload['temp_bme_c']}  RH={payload['hum_bme_pct']}  "
                f"P={payload['pressure_hpa']}  wind={payload['wind_speed_ms']} m/s"
            )

            if args.drop_after and sent >= args.drop_after:
                print("Dropping off without disconnecting — the broker will publish the Last-Will")
                os._exit(0)
            if args.count and sent >= args.count:
                break

            sim_time += args.interval
            behind = datetime.now(UTC) - sim_time
            if behind > timedelta(0):  # catching up: accelerated
                time.sleep(args.interval.total_seconds() / max(args.speed, 1e-6))
            else:  # live
                time.sleep(-behind.total_seconds())
    except KeyboardInterrupt:
        pass
    client.publish(status_topic, "offline", qos=1, retain=True).wait_for_publish(5)
    client.loop_stop()
    client.disconnect()
    print("Disconnected cleanly (status offline)")


if __name__ == "__main__":
    main()
