"""Synthetic Karur dataset in the kit's MQTT format (FR-SYN-01..06, design §7).

Three layers:

1. **Truth** — the weather itself: daily cycles and seasons from the climate
   normals, day-to-day variability, heat spells, monsoon wind spells,
   pre-monsoon storms and north-east-monsoon depressions.
2. **Sensors** — what the kit would report: BME280 noise, DHT11 bias and
   whole-number rounding, anemometer noise.
3. **Faults** — spikes, stuck values, BME280 failures, gaps and offline periods.

Event strength is calibrated so that hazard hours (Yellow or worse, either
hazard) make up the share set in ``synthetic.yaml``. Everything is driven by
one seed, so the same configuration always produces the same data.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.signal import lfilter

from ml.core.labels import make_labels
from ml.core.normals import DailyNormals

FW_VERSION = "synthetic-v1"
PRESSURE_DROP_PER_M = 0.12  # hPa per metre of elevation, near sea level
MAX_DAILY_TMAX_C = 47.0
MAX_CALIBRATION_ROUNDS = 8
# Share of the hazard-hour target given to each hazard
WIND_SHARE_OF_TARGET = 0.75
HEAT_SHARE_OF_TARGET = 0.25


@dataclass
class Scales:
    """Calibration multipliers for event strength."""

    wind: float = 1.0
    heat: float = 1.0


@dataclass
class SyntheticResult:
    readings: pd.DataFrame  # kit payload format + kit_id (NaN = null)
    truth: pd.DataFrame  # true weather on the 5-min grid, before sensors and faults
    events: pd.DataFrame
    faults: pd.DataFrame
    scales: Scales
    shares: dict = field(default_factory=dict)


# ---------------------------------------------------------------- helpers


def daily_shape(hour: np.ndarray) -> np.ndarray:
    """0 at about 06:00, 1 at about 14:30, smooth decay overnight."""
    hour = np.asarray(hour, dtype=float)
    rising = (1 - np.cos(np.pi * (hour - 6) / 8.5)) / 2
    fraction = ((hour - 14.5) % 24) / 15.5
    falling = (1 + np.cos(np.pi * fraction)) / 2
    return np.where((hour >= 6) & (hour <= 14.5), rising, falling)


def ar1(rng: np.random.Generator, n: int, phi: float, sd: float) -> np.ndarray:
    """Autocorrelated noise with stationary standard deviation ``sd``."""
    shocks = rng.normal(0, sd * np.sqrt(1 - phi**2), n)
    shocks[0] = rng.normal(0, sd)
    return lfilter([1.0], [1.0, -phi], shocks)


def dewpoint(temp_c, rh_pct):
    gamma = np.log(np.clip(rh_pct, 1, 100) / 100) + 17.625 * temp_c / (243.04 + temp_c)
    return 243.04 * gamma / (17.625 - gamma)


def relative_humidity(temp_c, dewpoint_c):
    rh = 100 * np.exp(
        17.625 * dewpoint_c / (243.04 + dewpoint_c) - 17.625 * temp_c / (243.04 + temp_c)
    )
    return np.clip(rh, 5, 100)


def _period(site, syn) -> tuple[pd.Timestamp, pd.Timestamp]:
    tz = ZoneInfo(site.site.timezone)
    start = pd.Timestamp(syn.start_date).tz_localize(tz)
    return start, start + pd.DateOffset(years=syn.years)


# ------------------------------------------------------------- truth layer


def _place_events(rng, syn, days: pd.DatetimeIndex, scales: Scales, tz) -> dict:
    """Event schedules on the daily index; returns arrays and an event list."""
    n_days = len(days)
    heat_anom = np.zeros(n_days)
    wind_boost = np.ones(n_days)
    storms: list[dict] = []
    depressions: list[dict] = []
    events: list[dict] = []

    def day_index(year: int, doy: int) -> int:
        date = pd.Timestamp(year=year, month=1, day=1, tz=tz) + pd.Timedelta(days=doy - 1)
        return (date - days[0]).days

    for year in range(days[0].year, days[-1].year + 1):
        for i in range(round(syn.events.heat_spells_per_year)):
            extreme = i == 0  # one very hot spell a year gives the model Red examples
            if extreme or rng.random() < 0.8:
                doy = int(rng.integers(91, 152))  # April–May
            else:
                doy = int(rng.choice([rng.integers(60, 91), rng.integers(152, 171)]))
            start, length = day_index(year, doy), int(rng.integers(3, 8))
            amplitude = (rng.uniform(6.5, 8.0) if extreme else rng.uniform(4.0, 6.5)) * scales.heat
            profile = np.full(length, amplitude)
            profile[[0, -1]] *= 0.6
            lo, hi = max(start, 0), min(start + length, n_days)
            if lo < hi:
                heat_anom[lo:hi] = np.maximum(heat_anom[lo:hi], profile[lo - start : hi - start])
                events.append(
                    {"type": "heat_spell", "start": days[lo], "days": hi - lo, "size": amplitude}
                )

        for _ in range(round(syn.events.wind_spells_per_year)):
            start = day_index(year, int(rng.integers(152, 259)))  # June – mid-September
            length = int(rng.integers(1, 6))
            boost = rng.uniform(0.6, 1.6)
            lo, hi = max(start, 0), min(start + length, n_days)
            if lo < hi:
                wind_boost[lo:hi] = np.maximum(wind_boost[lo:hi], 1 + boost)
                events.append(
                    {"type": "wind_spell", "start": days[lo], "days": hi - lo, "size": boost}
                )

        for _ in range(round(syn.events.storms_per_year)):
            index = day_index(year, int(rng.integers(60, 152)))  # March–May
            if not 0 <= index < n_days:
                continue
            onset = days[index] + pd.Timedelta(hours=float(rng.uniform(14, 19)))
            storm = {
                "onset": onset.tz_convert("UTC"),
                "pressure_drop": rng.uniform(1.5, 3.0),
                "pressure_rebound": rng.uniform(1.0, 2.0),
                "temp_drop": rng.uniform(5.0, 8.0),
                "dewpoint_rise": rng.uniform(1.0, 3.0),
                "wind_peak_ms": rng.uniform(15.0, 22.0),  # 54–79 km/h: most reach Red
                "wind_minutes": rng.uniform(15, 45),
            }
            storms.append(storm)
            events.append(
                {"type": "storm", "start": onset, "days": 0, "size": storm["wind_peak_ms"] * 3.6}
            )

        for _ in range(round(syn.events.depressions_per_year)):
            index = day_index(year, int(rng.integers(274, 362)))  # October–December
            if not 0 <= index < n_days:
                continue
            start = days[index] + pd.Timedelta(hours=float(rng.uniform(0, 24)))
            depression = {
                "start": start.tz_convert("UTC"),
                "hours": rng.uniform(24, 48),
                "wind_peak_ms": rng.uniform(11.0, 20.0),  # 40–72 km/h
                "pressure_drop": rng.uniform(4.0, 8.0),
                "dewpoint_rise": rng.uniform(1.0, 2.5),
                "temp_drop": rng.uniform(1.0, 3.0),  # cloud cover
            }
            depressions.append(depression)
            events.append(
                {
                    "type": "depression",
                    "start": start,
                    "days": round(depression["hours"] / 24, 1),
                    "size": depression["wind_peak_ms"] * 3.6,
                }
            )

    return {
        "heat_anom": heat_anom,
        "wind_boost": wind_boost,
        "storms": storms,
        "depressions": depressions,
        "events": events,
    }


def _apply_storms(storms, times: pd.DatetimeIndex, temp, dew, pressure, wind, rng) -> None:
    """Add storm signatures in place (gradual enough to pass the QC spike check)."""
    t_ns = times.as_unit("ns").asi8  # pandas may store microseconds; Timestamp.value is ns
    for s in storms:
        onset = s["onset"].value
        if t_ns[-1] < onset - 90 * 60e9 or t_ns[0] > onset + 360 * 60e9:
            continue
        lo = np.searchsorted(t_ns, onset - 90 * 60e9)
        hi = np.searchsorted(t_ns, onset + 360 * 60e9)
        m = (t_ns[lo:hi] - onset) / 60e9  # minutes from onset

        drop, rebound = s["pressure_drop"], s["pressure_rebound"]
        dp = np.select(
            [m < 0, m < 20, m < 200],
            [
                -drop * (m + 90) / 90,
                -drop + (drop + rebound) * m / 20,
                rebound * (1 - (m - 20) / 180),
            ],
            0.0,
        )
        pressure[lo:hi] += dp

        cooling = np.where(m < 0, 0.0, np.where(m < 20, m / 20, np.exp(-(m - 20) / 60)))
        temp[lo:hi] -= s["temp_drop"] * cooling
        dew[lo:hi] += s["dewpoint_rise"] * cooling

        d = s["wind_minutes"]
        gust = np.select(
            [m < 0, m < 5, m < 5 + d, m < 20 + d],
            [0.0, m / 5, 1.0, 1 - (m - 5 - d) / 15],
            0.0,
        )
        burst = s["wind_peak_ms"] * gust * rng.uniform(0.85, 1.0, len(m))
        wind[lo:hi] = np.maximum(wind[lo:hi], burst)


DEPRESSION_RAMP_H = 6


def _apply_depressions(depressions, times, temp, dew, pressure, wind, rng) -> None:
    """NE-monsoon depressions: wind and moisture build over hours and last 1–2 days."""
    t_ns = times.as_unit("ns").asi8
    for d in depressions:
        begin = d["start"].value
        end = begin + d["hours"] * 3600e9
        if t_ns[-1] < begin or t_ns[0] > end:
            continue
        lo, hi = np.searchsorted(t_ns, begin), np.searchsorted(t_ns, end)
        h = (t_ns[lo:hi] - begin) / 3600e9  # hours from start
        strength = np.clip(h / DEPRESSION_RAMP_H, 0, 1) * np.clip(
            (d["hours"] - h) / DEPRESSION_RAMP_H, 0, 1
        )
        pressure[lo:hi] -= d["pressure_drop"] * strength
        temp[lo:hi] -= d["temp_drop"] * strength
        dew[lo:hi] += d["dewpoint_rise"] * strength
        sustained = d["wind_peak_ms"] * strength * rng.gamma(20, 0.05, len(h))
        wind[lo:hi] = np.maximum(wind[lo:hi], sustained)


def generate_truth(
    site,
    syn,
    scales: Scales,
    start: pd.Timestamp,
    end: pd.Timestamp,
    seed: int,
    interval_min: int = 5,
) -> tuple[pd.DataFrame, list[dict]]:
    """True weather every ``interval_min`` minutes in [start, end) (local-time bounds)."""
    tz = ZoneInfo(site.site.timezone)
    rng = np.random.default_rng(seed)
    normals = DailyNormals(site.normals)

    times = pd.date_range(
        start.tz_convert("UTC"), end.tz_convert("UTC"), freq=f"{interval_min}min", inclusive="left"
    )
    days = pd.date_range(
        start.normalize() - pd.Timedelta(days=1), end.normalize() + pd.Timedelta(days=1), freq="D"
    )
    n_days = len(days)
    doy = days.dayofyear.to_numpy()

    placed = _place_events(rng, syn, days, scales, tz)
    heat = placed["heat_anom"]

    tmax_d = normals.tmax_c[doy - 1] + ar1(rng, n_days, 0.7, 1.0) + heat
    tmin_d = normals.tmin_c[doy - 1] + ar1(rng, n_days, 0.7, 0.7) + 0.4 * heat
    # Karur's record is about 44 °C; allow a little above it so Red (≥ 45 °C) examples exist
    tmax_d = np.clip(tmax_d, tmin_d + 3, MAX_DAILY_TMAX_C)
    dew_anom = ar1(rng, n_days, 0.75, 1.2) - 0.3 * heat
    dew_morning = dewpoint(normals.tmin_c[doy - 1], normals.rh_morning_pct[doy - 1]) + dew_anom
    dew_evening = (
        dewpoint(normals.tmax_c[doy - 1] - 1.5, normals.rh_evening_pct[doy - 1]) + dew_anom
    )
    synoptic = ar1(rng, n_days, 0.85, 1.2)
    wind_factor = np.exp(ar1(rng, n_days, 0.6, 0.25)) * placed["wind_boost"]

    local = times.tz_convert(tz)
    hour = (local.hour + local.minute / 60).to_numpy()
    j = ((local.normalize() - days[0]).days).to_numpy()
    shape = daily_shape(hour)
    morning, afternoon = hour < 6, hour > 14.5
    hi_index = np.where(morning, j - 1, j)
    lo_index = np.where(afternoon, j + 1, j)

    temp = tmin_d[lo_index] + (tmax_d[hi_index] - tmin_d[lo_index]) * shape
    temp += lfilter([1.0], [1.0, -0.95], rng.normal(0, 0.25 * np.sqrt(1 - 0.95**2), len(times)))
    dew = dew_morning[lo_index] + (dew_evening[hi_index] - dew_morning[lo_index]) * shape

    # Daily values joined smoothly: interpolate between local noons
    day_pos = j + (hour - 12) / 24
    smooth = lambda daily: np.interp(day_pos, np.arange(n_days), daily)  # noqa: E731
    pressure = (
        smooth(normals.mslp_hpa[doy - 1])
        - site.site.elevation_m * PRESSURE_DROP_PER_M
        + 1.2 * np.cos(2 * np.pi * (hour - 10) / 12)
        + smooth(synoptic)
    )
    wind = (
        smooth(normals.wind_kmh[doy - 1])
        / 3.6
        * smooth(wind_factor)
        * (0.55 + 0.65 * shape)
        * rng.gamma(10, 0.1, len(times))
        * scales.wind
    )

    _apply_storms(placed["storms"], times, temp, dew, pressure, wind, rng)
    _apply_depressions(placed["depressions"], times, temp, dew, pressure, wind, rng)
    dew = np.minimum(dew, temp - 0.1)

    truth = pd.DataFrame(
        {
            "temp_c": temp,
            "hum_pct": relative_humidity(temp, dew),
            "pressure_hpa": pressure,
            "wind_speed_ms": wind,
        },
        index=pd.DatetimeIndex(times, name="slot"),
    )
    return truth, placed["events"]


# ------------------------------------------------------------ sensor layer


def sensor_layer(truth: pd.DataFrame, rng: np.random.Generator, kit_id: str) -> pd.DataFrame:
    """What the kit reports for the true weather (no faults)."""
    n = len(truth)
    days = (truth.index - truth.index[0]).days.to_numpy()
    n_days = days.max() + 2
    dht_temp_bias = np.clip(ar1(rng, n_days, 0.9, 0.6), -1, 1)
    dht_hum_bias = np.clip(ar1(rng, n_days, 0.9, 2.0), -3, 3)
    fraction = days + (truth.index.hour.to_numpy() / 24)
    temp_bias = np.interp(fraction, np.arange(n_days), dht_temp_bias)
    hum_bias = np.interp(fraction, np.arange(n_days), dht_hum_bias)

    temp, hum = truth["temp_c"].to_numpy(), truth["hum_pct"].to_numpy()
    dht_temp = temp + temp_bias + rng.normal(0, 0.8, n)

    # Occasional longer DHT11 disagreement episodes (about 4 a year, 1–6 h)
    slots_per_hour = 12
    for _ in range(max(1, round(4 * n / (365 * 24 * slots_per_hour)))):
        start = int(rng.integers(0, n))
        length = int(rng.integers(1, 7)) * slots_per_hour
        dht_temp[start : start + length] += rng.choice([-1, 1]) * rng.uniform(3, 4.5)

    return pd.DataFrame(
        {
            "ts": truth.index,
            "kit_id": kit_id,
            "temp_bme_c": np.round(temp + rng.normal(0, 0.1, n), 2),
            "hum_bme_pct": np.round(np.clip(hum + rng.normal(0, 0.8, n), 0, 100), 1),
            "pressure_hpa": np.round(truth["pressure_hpa"].to_numpy() + rng.normal(0, 0.1, n), 2),
            "temp_dht_c": np.round(dht_temp),
            "hum_dht_pct": np.round(np.clip(hum + hum_bias + rng.normal(0, 2, n), 0, 100)),
            "wind_speed_ms": np.round(
                np.clip(truth["wind_speed_ms"].to_numpy() + rng.normal(0, 0.2, n), 0, None), 1
            ),
            "wind_gust_ms": np.nan,
            "rain_mm": np.nan,
            "fw_version": FW_VERSION,
        }
    )


# ------------------------------------------------------------- fault layer

SPIKE_SIZES = {
    "temp_bme_c": (8, 15),
    "hum_bme_pct": (25, 40),
    "pressure_hpa": (5, 12),
    "temp_dht_c": (8, 15),
    "hum_dht_pct": (25, 40),
}
BME_FIELDS = ["temp_bme_c", "hum_bme_pct", "pressure_hpa"]


def fault_layer(
    readings: pd.DataFrame, faults_cfg, rng: np.random.Generator, interval_min: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Inject faults; returns (readings, fault log)."""
    frame = readings.copy()
    n = len(frame)
    per_hour = 60 // interval_min
    years = n / (365.25 * 24 * per_hour)
    ts = frame["ts"]
    log: list[dict] = []

    def runs(per_year: float, min_slots: int, max_slots: int):
        for _ in range(round(per_year * years)):
            start = int(rng.integers(0, max(1, n - max_slots)))
            yield start, min(n, start + int(rng.integers(min_slots, max_slots + 1)))

    def record(kind, field_name, start, end):
        log.append(
            {"type": kind, "field": field_name, "start": ts.iat[start], "end": ts.iat[end - 1]}
        )

    for name, (low, high) in SPIKE_SIZES.items():
        hits = np.flatnonzero(rng.random(n) < faults_cfg.spike_prob)
        column = frame.columns.get_loc(name)
        digits = 0 if "dht" in name else 2  # the DHT11 only reports whole numbers
        for i in hits:
            jump = rng.choice([-1, 1]) * rng.uniform(low, high)
            frame.iat[i, column] = round(frame.iat[i, column] + jump, digits)
            record("spike", name, i, i + 1)

    for start, end in runs(faults_cfg.stuck_runs_per_year, 1 * per_hour, 3 * per_hour):
        name = str(rng.choice(BME_FIELDS))
        frame.iloc[start:end, frame.columns.get_loc(name)] = frame[name].iat[start]
        record("stuck", name, start, end)

    for start, end in runs(faults_cfg.bme_failure_runs_per_year, 1 * per_hour, 6 * per_hour):
        frame.iloc[start:end, [frame.columns.get_loc(c) for c in BME_FIELDS]] = np.nan
        record("bme_failure", "bme280", start, end)

    drop = np.zeros(n, dtype=bool)
    for start, end in runs(
        faults_cfg.gap_runs_per_year, max(1, 10 // interval_min), 60 // interval_min
    ):
        drop[start:end] = True
        record("gap", "all", start, end)
    for start, end in runs(faults_cfg.offline_runs_per_year, 1 * per_hour, 12 * per_hour):
        drop[start:end] = True
        record("offline", "all", start, end)

    return frame.loc[~drop].reset_index(drop=True), pd.DataFrame(log)


# -------------------------------------------------------------- calibration


def hazard_shares(truth: pd.DataFrame, site) -> dict:
    grid = truth.resample("5min").mean()  # labels work on the 5-min grid
    labels = make_labels(grid, site, site.prediction.horizon_hours)
    yellow_any = (labels["wind_yellow"] == 1) | (labels["heat_yellow"] == 1)
    shares = {
        name: float(labels[name].mean())
        for name in (
            "wind_yellow",
            "wind_orange",
            "wind_red",
            "heat_yellow",
            "heat_orange",
            "heat_red",
        )
    }
    shares["hazard_any"] = float(yellow_any.mean())
    shares["positive_hours"] = {
        name: int(labels[name].sum())
        for name in (
            "wind_yellow",
            "wind_orange",
            "wind_red",
            "heat_yellow",
            "heat_orange",
            "heat_red",
        )
    }
    return shares


def calibrate(site, syn, start, end) -> tuple[Scales, pd.DataFrame, list[dict], dict]:
    """Adjust event strength until hazard hours fall in the configured share range."""
    low, high = syn.target_hazard_hour_share
    middle = (low + high) / 2
    wind_target, heat_target = middle * WIND_SHARE_OF_TARGET, middle * HEAT_SHARE_OF_TARGET
    scales = Scales()
    for _ in range(MAX_CALIBRATION_ROUNDS):
        truth, events = generate_truth(site, syn, scales, start, end, syn.seed, syn.interval_min)
        shares = hazard_shares(truth, site)
        wind_ok = abs(shares["wind_yellow"] / wind_target - 1) < 0.35
        heat_ok = abs(shares["heat_yellow"] / heat_target - 1) < 0.5
        if low <= shares["hazard_any"] <= high and wind_ok and heat_ok:
            break
        scales.wind *= float(
            np.clip((wind_target / max(shares["wind_yellow"], 1e-4)) ** 0.3, 0.6, 1.6)
        )
        heat_ratio = heat_target / max(shares["heat_yellow"], 1e-4)
        scales.heat *= float(np.clip(heat_ratio**0.25, 0.75, 1.3))
    return scales, truth, events, shares


# ------------------------------------------------------------------ public


def generate(site, syn) -> SyntheticResult:
    start, end = _period(site, syn)
    scales, truth, events, shares = calibrate(site, syn, start, end)
    rng = np.random.default_rng(syn.seed + 1)  # separate stream: sensors and faults
    readings = sensor_layer(truth, rng, syn.kit_id)
    faults = pd.DataFrame(columns=["type", "field", "start", "end"])
    if syn.faults.enabled:
        readings, faults = fault_layer(readings, syn.faults, rng, syn.interval_min)
    readings["ts"] = readings["ts"].dt.tz_convert("UTC")
    return SyntheticResult(
        readings=readings,
        truth=truth,
        events=pd.DataFrame(events),
        faults=faults,
        scales=scales,
        shares=shares,
    )


def save(result: SyntheticResult, output: Path, site, syn) -> dict:
    """Write readings (Parquet), fault log (CSV) and metadata (JSON)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    result.readings.to_parquet(output, index=False)
    result.faults.to_csv(output.with_suffix(".faults.csv"), index=False)
    result.events.to_csv(output.with_suffix(".events.csv"), index=False)
    meta = {
        "rows": len(result.readings),
        "start": str(result.readings["ts"].min()),
        "end": str(result.readings["ts"].max()),
        "kit_id": syn.kit_id,
        "seed": syn.seed,
        "interval_min": syn.interval_min,
        "scales": asdict(result.scales),
        "hazard_shares": result.shares,
        "target_hazard_hour_share": list(syn.target_hazard_hour_share),
        "events": result.events["type"].value_counts().to_dict() if len(result.events) else {},
        "faults": result.faults["type"].value_counts().to_dict() if len(result.faults) else {},
        "normals_source": site.normals.source,
    }
    output.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2, default=str))
    return meta
