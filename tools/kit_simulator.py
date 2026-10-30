"""Kit simulator: publishes readings in the kit's MQTT format (FR-SIM-01).

The weather comes from the synthetic generator's model (same climate, events
and sensor behaviour as the training data), generated a few days at a time.

Examples (from the project root):
    .venv\\Scripts\\python.exe tools\\kit_simulator.py                      # live, every 5 min
    .venv\\Scripts\\python.exe tools\\kit_simulator.py --interval 10s
    .venv\\Scripts\\python.exe tools\\kit_simulator.py --backfill-hours 48 --speed 600
    .venv\\Scripts\\python.exe tools\\kit_simulator.py --backfill-hours 48 --force wind:red
    .venv\\Scripts\\python.exe tools\\kit_simulator.py --no-ts --faults
    .venv\\Scripts\\python.exe tools\\kit_simulator.py --drop-after 3       # test Last-Will

With --backfill-hours the simulated clock starts in the past and runs --speed
times faster until it catches up with real time, then continues live. (The
server rejects timestamps in the future, so the clock never runs ahead.)

--force HAZARD:LEVEL starts a hazard when the simulated clock reaches the
present: wind builds up over an hour to the level's speed and holds for 4 more
hours; heat ramps up (0.5 °C/min) to the level's temperature and stays there
for 3 hours. Hourly predictions only use readings from before the hour, so to
see the effect straight away start the hazard in the backfilled past, e.g.
--backfill-hours 48 --force wind:orange --force-minutes-ago 150.
"""

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root

import numpy as np  # noqa: E402
import paho.mqtt.client as mqtt  # noqa: E402
import pandas as pd  # noqa: E402

from backend.app.settings import (  # noqa: E402
    ConfigError,
    SiteConfig,
    SyntheticConfig,
    load_env_settings,
    load_site_config,
    load_synthetic_config,
)
from ml.core.normals import DailyNormals  # noqa: E402
from ml.synthetic.generator import Scales, generate_truth, sensor_layer  # noqa: E402

FW_VERSION = "sim-0.2"
LEVELS = ("yellow", "orange", "red")
# Forced wind is a sustained spell (like the monsoon spells in the training data),
# not a short storm burst: the models learned that a sudden spike soon calms down.
WIND_FORCE = timedelta(hours=5)
WIND_RAMP_MIN = 60
HEAT_FORCE = timedelta(hours=3)
HEAT_RAMP_C_PER_MIN = 0.5  # stays under the QC spike limit
WIND_FORCE_MARGIN = 1.1  # forced wind sits 10 % above the level's threshold
HEAT_FORCE_MARGIN_C = 0.8  # forced heat sits 0.8 °C above the level's threshold


def parse_interval(text: str) -> timedelta:
    match = re.fullmatch(r"(\d+)\s*([sm])", text.strip().lower())
    if not match:
        raise argparse.ArgumentTypeError("use e.g. 60s or 5m")
    amount, unit = int(match[1]), match[2]
    return timedelta(seconds=amount) if unit == "s" else timedelta(minutes=amount)


def parse_force(text: str) -> tuple[str, str]:
    hazard, _, level = text.strip().lower().partition(":")
    if hazard not in ("wind", "heat") or level not in LEVELS:
        raise argparse.ArgumentTypeError("use wind:yellow|orange|red or heat:yellow|orange|red")
    return hazard, level


class SyntheticWeather:
    """Readings from the synthetic model, generated in 4-day chunks at 1-minute steps."""

    def __init__(
        self,
        site: SiteConfig,
        syn: SyntheticConfig,
        kit_id: str,
        seed: int,
        faults: bool,
        force: tuple[str, str] | None,
        force_start: datetime,
    ) -> None:
        self._site = site
        self._syn = syn
        self._kit_id = kit_id
        self._seed = seed
        self._tz = ZoneInfo(site.site.timezone)
        self._rng = random.Random(seed)
        self._faults = faults
        self._force = force
        self._force_start = force_start
        self._normals = DailyNormals(site.normals)
        self._scales = self._trained_scales()
        self._chunk: pd.DataFrame | None = None

    def _trained_scales(self) -> Scales:
        """Use the event strength the training data was calibrated with, if available."""
        meta = self._syn.output_path.with_suffix(".meta.json")
        if meta.is_file():
            return Scales(**json.loads(meta.read_text())["scales"])
        return Scales()

    def _load_chunk(self, ts: datetime) -> None:
        start = pd.Timestamp(ts).tz_convert(self._tz).normalize() - pd.Timedelta(days=1)
        end = start + pd.Timedelta(days=4)
        seed = self._seed + start.toordinal()
        truth, _ = generate_truth(self._site, self._syn, self._scales, start, end, seed, 1)
        sensors = sensor_layer(truth, np.random.default_rng(seed + 1), self._kit_id)
        self._chunk = sensors.set_index("ts")

    def reading(self, ts: datetime) -> dict:
        stamp = pd.Timestamp(ts)
        if self._chunk is None or not (
            self._chunk.index[0] <= stamp <= self._chunk.index[-1] - pd.Timedelta(hours=1)
        ):
            self._load_chunk(ts)
        row = self._chunk.loc[self._chunk.index.asof(stamp)]
        values = {
            name: (None if pd.isna(row[name]) else float(row[name]))
            for name in (
                "temp_bme_c",
                "hum_bme_pct",
                "pressure_hpa",
                "temp_dht_c",
                "hum_dht_pct",
                "wind_speed_ms",
                "wind_gust_ms",
                "rain_mm",
            )
        }
        if self._force:
            self._apply_force(ts, values)
        if self._faults:
            self._inject_fault(values)
        return values

    def _apply_force(self, ts: datetime, values: dict) -> None:
        hazard, level = self._force
        elapsed = ts - self._force_start
        if elapsed < timedelta(0):
            return
        minutes = elapsed.total_seconds() / 60
        if hazard == "wind" and elapsed <= WIND_FORCE:
            target_ms = getattr(self._site.hazards.wind.levels, level) * WIND_FORCE_MARGIN / 3.6
            ramp = min(1.0, minutes / WIND_RAMP_MIN)
            noise = self._rng.uniform(0.97, 1.05)
            values["wind_speed_ms"] = round(
                max(values["wind_speed_ms"], target_ms * ramp * noise), 1
            )
        elif hazard == "heat" and elapsed <= HEAT_FORCE:
            target = self._heat_target(ts, level)
            for name, digits in (("temp_bme_c", 2), ("temp_dht_c", 0)):
                base = values[name]
                if base is not None:
                    raised = max(base, min(target, base + HEAT_RAMP_C_PER_MIN * minutes))
                    values[name] = round(raised, digits)

    def _heat_target(self, ts: datetime, level: str) -> float:
        heat = self._site.hazards.heat
        if level == "red":
            return heat.red_abs_c + HEAT_FORCE_MARGIN_C
        doy = ts.astimezone(self._tz).timetuple().tm_yday
        departure = getattr(heat.departure_c, level)
        normal_max = float(self._normals.tmax_for(doy))
        threshold = max(self._site.heat_abs_threshold_c, normal_max + departure)
        return threshold + HEAT_FORCE_MARGIN_C

    def _inject_fault(self, values: dict) -> None:
        roll = self._rng.random()
        if roll < 0.02 and values["temp_bme_c"] is not None:
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
        "--force", type=parse_force, default=None, help="start a hazard, e.g. wind:red, heat:orange"
    )
    parser.add_argument(
        "--force-minutes-ago",
        type=float,
        default=0.0,
        help="start the forced hazard this many minutes before now (needs --backfill-hours)",
    )
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
        syn = load_synthetic_config(site=site)
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

    now = datetime.now(UTC).replace(microsecond=0)
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    force_start = now - timedelta(minutes=args.force_minutes_ago)
    model = SyntheticWeather(site, syn, args.kit, seed, args.faults, args.force, force_start)
    telemetry_topic = f"weather/kit/{args.kit}/telemetry"
    status_topic = f"weather/kit/{args.kit}/status"

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=args.kit, clean_session=True)
    client.username_pw_set(env.mqtt_kit_username, env.mqtt_kit_password.get_secret_value())
    client.will_set(status_topic, "offline", qos=1, retain=True)
    host, port = args.host or env.mqtt_host, args.port or env.mqtt_port
    client.connect(host, port, keepalive=15 if args.drop_after else 60)
    client.loop_start()
    client.publish(status_topic, "online", qos=1, retain=True).wait_for_publish(5)
    print(
        f"Connected to {host}:{port} as '{args.kit}'; publishing to {telemetry_topic} (seed {seed})"
    )
    if args.force:
        print(f"Forced hazard {args.force[0]}:{args.force[1]} starts at {force_start:%H:%M} UTC")

    sim_time = now - timedelta(hours=args.backfill_hours)
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
