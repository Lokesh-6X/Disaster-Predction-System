# System Design — Site Weather Hazard Prediction System (v1)

| | |
|---|---|
| **Version** | v1 (prototype) |
| **Status** | Draft |
| **Implements** | [`docs/requirements_v1.md`](../requirements_v1.md) |
| **UI reference** | [`ui_reference_v1.html`](ui_reference_v1.html) (Claude Design) + [`docs/frontend_pages.md`](../frontend_pages.md) |
| **Last updated** | 2026-10-31 |

This document describes **how** v1 is built: components, modules, data model, algorithms, interfaces and runtime. The requirements document says **what** must be built; requirement IDs are referenced in brackets, e.g. [FR-QC-04].

---

## 1. Design principles

1. **One code path for synthetic and real data.** The synthetic generator emits the kit's payload format; QC, fusion, aggregation and features are shared by training and live inference.
2. **Config over code.** Everything site-specific lives in `config/*.yaml`; secrets in `.env`.
3. **Keep everything.** Raw readings, flags, predictions and alerts are never deleted — they are the training data for the next version.
4. **Simple to run on one Windows PC.** One backend process, one frontend dev server, one broker, one database. No Docker.
5. **Ready for multiple kits.** Every row is keyed by `kit_id`, even though v1 has one kit.

---

## 2. Architecture

### 2.1 Runtime components

```
┌─────────────┐  MQTT (1884)  ┌──────────────┐
│ Kit / kit   │──────────────►│  Mosquitto   │
│ simulator   │               │  (service)   │
└─────────────┘               └──────┬───────┘
                                     │ subscribe weather/kit/+/#
                                     ▼
┌──────────────────────── FastAPI backend process (8000) ────────────────────────┐
│                                                                                │
│  ┌──────────────┐   ┌──────────┐   ┌───────────────┐   ┌───────────────────┐   │
│  │ MQTT task    │──►│ QC +     │──►│ Readings repo │──►│ WebSocket hub     │───┼──► Browser
│  │ (aiomqtt)    │   │ fusion   │   │ (DB insert)   │   │ /ws/live          │   │
│  └──────────────┘   └──────────┘   └───────────────┘   └─────────▲─────────┘   │
│                                                                  │             │
│  ┌──────────────┐   ┌──────────┐   ┌───────────────┐   ┌─────────┴─────────┐   │
│  │ Scheduler    │──►│ Feature  │──►│ Model runner  │──►│ Alert engine      │───┼──► SMTP
│  │ (hourly)     │   │ builder  │   │ (6 XGBoost)   │   │ (cooldown/escal.) │   │
│  └──────────────┘   └──────────┘   └───────────────┘   └───────────────────┘   │
│                                                                                │
│  ┌──────────────┐   ┌──────────────────────────────┐                           │
│  │ Kit watchdog │   │ REST API (JWT)               │◄──────────────────────────┼─── Browser
│  │ (every 60 s) │   │ /api/...                     │                           │
│  └──────────────┘   └──────────────────────────────┘                           │
└───────────────────────────────────┬────────────────────────────────────────────┘
                                    ▼
                           ┌─────────────────┐
                           │  PostgreSQL     │
                           │  (5432)         │
                           └─────────────────┘

┌──────────── Offline ML pipeline (CLI) ────────────┐
│ generate → qc/fuse → aggregate → labels/features  │
│ → train (6 models) → evaluate → registry (v{N})   │
└───────────────────────────────────────────────────┘
                 │ ml/models/active → loaded by backend at start-up
```

### 2.2 Process model

- **Single backend process** (Uvicorn, one worker). Inside it, background asyncio tasks run:
  - MQTT subscriber task
  - Kit watchdog task (offline detection)
  - APScheduler `AsyncIOScheduler` (hourly prediction job)
- One worker is required because the WebSocket hub, QC buffers and scheduler live in memory.
- **Windows note:** `aiomqtt` needs a selector event loop; on Windows the backend sets `asyncio.WindowsSelectorEventLoopPolicy()` before Uvicorn starts (done in `backend/run.py`, which the start script uses instead of the bare `uvicorn` command).

### 2.3 Technology choices

| Concern | Library | Why |
|---|---|---|
| Web/API | FastAPI, Uvicorn | Async, Pydantic models, auto OpenAPI docs |
| MQTT client | aiomqtt (paho-based) | Async, fits the FastAPI event loop |
| Validation/config | Pydantic v2, pydantic-settings, PyYAML | Same models validate payloads and config |
| Database | PostgreSQL 16 + SQLAlchemy 2 (async) + asyncpg | Robust; easy to add TimescaleDB later |
| Migrations | Alembic | Versioned schema changes for the next version |
| Scheduler | APScheduler 3.x | Cron-style hourly job with timezone |
| Email | aiosmtplib + Jinja2 templates | Async SMTP; HTML + text email |
| Auth | PyJWT (HS256), bcrypt | Simple, standard |
| ML | pandas, NumPy, XGBoost, scikit-learn, pyarrow | Training, metrics, Parquet files |
| Frontend | React 18 + Vite, React Router, Recharts | As required |
| Tests | pytest, pytest-asyncio; Vitest for the frontend | |

> Email: Gmail SMTP with an app password for real alerts; Mailpit (`localhost:1025`) as an optional local test inbox, selected via `.env`.

---

## 3. Repository and module layout

```
config/
  site.yaml                 # site, kits, hazards, qc, prediction, alerts, normals
  synthetic.yaml            # generator settings
backend/
  run.py                    # sets Windows loop policy, starts uvicorn
  alembic/                  # migrations
  app/
    main.py                 # FastAPI app, lifespan (start/stop tasks)
    settings.py             # .env (pydantic-settings) + YAML loading/validation
    db.py                   # engine, session factory
    models.py               # SQLAlchemy ORM tables
    schemas.py              # API request/response models
    mqtt/
      subscriber.py         # connect, subscribe, dispatch
      payload.py            # TelemetryPayload model, topic parsing
    ingest/
      pipeline.py           # validate → timestamp rules → QC → fuse → store → broadcast
      kit_status.py         # status topic, watchdog, status log
    inference/
      scheduler.py          # APScheduler job registration
      runner.py             # sufficiency → features → models → levels → store
      model_store.py        # loads active model version from ml/models
    alerts/
      engine.py             # trigger, cooldown, escalation
      emailer.py            # SMTP send
      templates/            # alert_email.html, alert_email.txt
    api/
      auth.py  kits.py  readings.py  predictions.py  alerts.py  system.py  ws.py
    ws/
      hub.py                # connected clients, broadcast
    security.py             # password hashing, JWT create/verify, dependencies
ml/
  core/                     # SHARED by backend and ML pipeline
    qc.py                   # QC rules (pure functions)
    fusion.py               # BME/DHT fusion
    normals.py              # IMD monthly normals → daily normals
    aggregate.py            # 5-min → hourly
    features.py             # hourly → feature matrix
    labels.py               # hourly → 6 binary labels
    levels.py               # probabilities → level
  synthetic/
    generator.py            # Karur synthetic dataset
  train.py  evaluate.py  registry.py
  cli.py                    # `python -m ml.cli generate|build|train|evaluate|activate`
  data/                     # generated data (git-ignored)
  models/                   # v1/, v2/, … and `active` (version pointer)
frontend/                   # React app (section 12)
tools/
  kit_simulator.py
scripts/
  start_backend.ps1  start_frontend.ps1  start_simulator.ps1  init_db.ps1
docs/
  requirements_v1.md  frontend_pages.md  mqtt_contract.md
  design/system_design_v1.md  design/ui_reference_v1.html
tests/
  backend/  ml/
.env.example
README.md
```

**Key rule:** `ml/core` has no database or web dependencies. The backend imports it, so live inference uses exactly the same QC, fusion, aggregation and feature code as training [FR-ML-02].

---

## 4. Configuration design

### 4.1 `config/site.yaml` (shape and defaults)

```yaml
site:
  name: "Karur Campus"
  latitude: 10.96
  longitude: 78.08
  elevation_m: 120
  timezone: "Asia/Kolkata"
  coastal: false

kits:
  - kit_id: "kit01"
    description: "Block A rooftop"
    latitude: 10.96
    longitude: 78.08
    anemometer_height_m: 3.0
    enabled: true
    notes: "Radiation shield fitted"

hazards:
  wind:                       # peak reported wind speed, km/h
    levels: { yellow: 30, orange: 40, red: 60 }
  heat:
    abs_threshold_c: 40       # 37 if coastal
    coastal_abs_threshold_c: 37
    departure_c: { yellow: 4.5, orange: 6.5 }
    red_abs_c: 45
  rain:
    enabled: false

qc:
  ranges:
    temp_c:      [0, 55]
    hum_pct:     [0, 100]
    pressure_hpa: [950, 1050]
    wind_ms:     [0, 60]
  spike_per_min:              # max allowed change per minute
    temp_c: 1.0
    hum_pct: 4.0
    pressure_hpa: 0.6
  stuck_minutes: 60
  fusion_mismatch: { temp_c: 3.0, hum_pct: 10.0 }
  future_ts_tolerance_min: 10

prediction:
  run_cron_minute: 0
  horizon_hours: 3
  history_hours: 48
  show_level_cutoff: 0.50

data_sufficiency:
  max_interp_gap_min: 30
  max_missing_share_24h: 0.25
  require_data_within_min: 60

kit_status:
  offline_after_min: 10

alerts:
  enabled: true
  levels: ["orange", "red"]
  cooldown_hours: 3

normals:                      # IMD 30-year monthly normals (to verify, D8)
  source: "IMD normals — Karur / Tiruchirappalli"
  tmax_c:  [ ... 12 values Jan..Dec ... ]
  tmin_c:  [ ... ]
  rh_morning_pct: [ ... ]
  rh_evening_pct: [ ... ]
  wind_kmh: [ ... ]
  mslp_hpa: [ ... ]
```

> The `qc` section adds explicit, configurable QC limits behind [FR-QC-01..03]. The `normals` values are filled in from IMD sources before Phase 3 (D8).

### 4.2 `config/synthetic.yaml`

```yaml
start_date: "2022-01-01"
years: 3
interval_min: 5
seed: 42
kit_id: "kit01"
target_hazard_hour_share: [0.03, 0.05]
events:
  heat_spells_per_year: 4        # Apr–May mainly
  wind_spells_per_year: 10       # Jun–Sep mainly
  storms_per_year: 8             # Mar–May afternoons
faults:
  enabled: true
  spike_prob: 0.001              # per reading per variable
  stuck_runs_per_year: 6
  gap_runs_per_year: 20          # 10–60 min
  offline_runs_per_year: 4       # 1–12 h
  bme_failure_runs_per_year: 3   # BME null → exercises DHT fallback
output: "ml/data/synthetic/karur_v1.parquet"
```

### 4.3 `.env`

```
DATABASE_URL=postgresql+asyncpg://weather:***@localhost:5432/weather
MQTT_HOST=localhost
MQTT_PORT=1884
MQTT_USERNAME=
MQTT_PASSWORD=
ADMIN_USERNAME=admin
ADMIN_PASSWORD=***            # used only to create the admin on first start
ADMIN_EMAIL=admin@example.com
JWT_SECRET=***
JWT_EXPIRE_HOURS=8
SMTP_HOST=smtp.gmail.com      # or localhost (Mailpit) for testing
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
SMTP_STARTTLS=true
FRONTEND_URL=http://localhost:5173
CORS_ORIGINS=http://localhost:5173
```

### 4.4 Loading and validation [FR-CFG-04]

`settings.py` defines Pydantic models for both YAML files and the `.env`. At start-up the backend loads and validates them; any error stops start-up with a message naming the file, key and problem. The ML CLI uses the same loader.

---

## 5. Data model

PostgreSQL schema (created by Alembic). All timestamps are `timestamptz` stored in UTC.

### 5.1 Tables

**`kits`**
| Column | Type | Notes |
|---|---|---|
| `kit_id` | text PK | e.g. `kit01` |
| `description` | text | from config |
| `latitude`, `longitude` | double | |
| `anemometer_height_m` | real | |
| `fw_version` | text | last reported |
| `status` | text | `online` / `offline` / `unknown` |
| `last_seen` | timestamptz | last reading received |
| `updated_at` | timestamptz | |

Rows are upserted from `site.yaml` at start-up.

**`kit_status_log`**
| Column | Type |
|---|---|
| `id` | bigserial PK |
| `kit_id` | text FK → kits |
| `ts` | timestamptz |
| `status` | text |
| `source` | text (`mqtt_status` / `watchdog`) |

**`readings`**
| Column | Type | Notes |
|---|---|---|
| `id` | bigserial PK | |
| `kit_id` | text FK | |
| `ts` | timestamptz | reading time (kit or arrival) |
| `ts_source` | text | `kit` / `arrival` |
| `received_at` | timestamptz | |
| `temp_bme_c`, `hum_bme_pct`, `pressure_hpa` | real null | raw |
| `temp_dht_c`, `hum_dht_pct` | real null | raw |
| `wind_speed_ms`, `wind_gust_ms`, `rain_mm` | real null | raw |
| `temp_c`, `hum_pct` | real null | fused |
| `fallback` | boolean | DHT11 used for fused value |
| `qc_flags` | text[] | e.g. `{temp_bme:spike, ts_missing}` |
| `fw_version` | text null | |

Constraints/indexes: `UNIQUE (kit_id, ts)`; index on `(kit_id, ts DESC)`.

**`predictions`**
| Column | Type | Notes |
|---|---|---|
| `id` | bigserial PK | |
| `kit_id` | text FK | |
| `run_at` | timestamptz | hour boundary the prediction is for |
| `hazard` | text | `wind` / `heat` |
| `status` | text | `ok` / `insufficient_data` |
| `p_yellow`, `p_orange`, `p_red` | real null | after monotonic fix |
| `level` | text null | `green` / `yellow` / `orange` / `red` |
| `valid_until` | timestamptz | `run_at + 3 h` |
| `model_version` | text null | e.g. `v1` |
| `fallback_used` | boolean | |
| `context` | jsonb | e.g. normal max today, missing share, features snapshot |
| `created_at` | timestamptz | |

Constraint: `UNIQUE (kit_id, hazard, run_at)` (a manual re-run overwrites).

**`alerts`**
| Column | Type | Notes |
|---|---|---|
| `id` | bigserial PK | |
| `prediction_id` | bigint FK → predictions | |
| `kit_id`, `hazard`, `level` | text | |
| `probability` | real | probability of the alerted level |
| `valid_until` | timestamptz | |
| `email_status` | text | `sent` / `cooldown` / `failed` / `disabled` |
| `error` | text null | SMTP error text |
| `created_at`, `sent_at` | timestamptz | |

> `disabled` records alerts raised while `alerts.enabled = false` [FR-ALT-06].

**`users`**
| Column | Type |
|---|---|
| `id` | serial PK |
| `username` | text unique |
| `email` | text |
| `password_hash` | text |
| `role` | text (`admin`) |
| `created_at` | timestamptz |

### 5.2 Volume
One kit at 5 min ≈ 105,000 readings/year, 17,520 predictions/year — trivial for PostgreSQL [NFR-09].

---

## 6. Ingestion design

### 6.1 Flow [FR-ING-01..04, FR-QC-01..05]

```
MQTT message
  │
  ├─ topic weather/kit/{kit_id}/status ──► kit_status.handle_status()
  │
  └─ topic weather/kit/{kit_id}/telemetry
        1. kit_id from topic; unknown/disabled kit → log, drop
        2. JSON parse → TelemetryPayload (Pydantic); invalid → log, drop
        3. Timestamp rules
             ts > now + 10 min      → log, drop
             ts missing             → ts = now, flag ts_missing, ts_source = arrival
        4. QC (ml.core.qc) using the kit's recent-history buffer
        5. Fusion (ml.core.fusion) → temp_c, hum_pct, fallback, mismatch flag
        6. INSERT … ON CONFLICT (kit_id, ts) DO NOTHING
             duplicate → stop here
        7. Update kits.last_seen, fw_version; if status ≠ online → online + log
        8. Append to history buffer
        9. WebSocket broadcast {type: "reading"}
```

### 6.2 Recent-history buffer
Per kit, an in-memory deque of the last 90 minutes of raw readings, filled from the database at start-up. Used by the spike and stuck checks so they work across restarts.

### 6.3 QC rules (`ml/core/qc.py`)

Pure functions over a reading and its history; flags are strings `"<field>:<rule>"`.

| Rule | Applies to | Logic |
|---|---|---|
| `out_of_range` | each sensor field | value outside `qc.ranges` |
| `spike` | temp, hum, pressure (BME and DHT) | `abs(Δvalue) / Δminutes > qc.spike_per_min[var]` vs previous valid reading (only if Δminutes ≤ 15) |
| `stuck` | each sensor field except wind = 0 | all readings in the last `stuck_minutes` have the identical value (and ≥ 6 readings exist) |
| `null` | each sensor field | value missing |
| `ts_missing` | reading | no `ts` in payload |

### 6.4 Fusion (`ml/core/fusion.py`) [FR-QC-04]

```
for (bme, dht, out) in [(temp_bme, temp_dht, temp_c), (hum_bme, hum_dht, hum_pct)]:
    if bme usable (not null, no out_of_range/spike/stuck flag):
        out = bme
        if dht usable and abs(bme - dht) > mismatch: flag bme_dht_mismatch
    elif dht usable:
        out = dht; fallback = True
    else:
        out = null
```

Pressure has no fallback (BME280 only); wind has one sensor.

### 6.5 Kit status [FR-ING-04]
- `status` topic payload `online` / `offline` → update `kits.status`, insert into `kit_status_log`, broadcast `kit_status`.
- Watchdog every 60 s: if `now − last_seen > offline_after_min` and status is `online` → set `offline` (source `watchdog`).
- A new telemetry reading from an offline kit sets it `online`.

---

## 7. Synthetic data generator

`ml/synthetic/generator.py` [FR-SYN-01..06]. All randomness comes from one `numpy.random.Generator(seed)`.

### 7.1 Daily normals (`ml/core/normals.py`)
Monthly IMD normals (12 values) are placed at mid-month and interpolated to every day of the year with a periodic cubic spline, so values are smooth and wrap around Dec → Jan. Output: `tmax_normal(doy)`, `tmin_normal(doy)`, `rh_normal(doy, morning/evening)`, `wind_normal(doy)`, `mslp_normal(doy)`.
The same `tmax_normal` is used for heat labels and the departure feature.

### 7.2 Signal model (5-min time steps, local time for daily shapes)

| Variable | Construction |
|---|---|
| **Temperature (true)** | `Tmin_d + (Tmax_d − Tmin_d) · shape(hour)` where `Tmax_d = tmax_normal + spell_anom + daily_AR(1)`; `shape` rises from ~06:00 to a peak ~14:30 and decays exponentially overnight; plus small AR(1) 5-min noise |
| **Humidity** | Daily dew point from normals (derived from normal RH and T) + daily AR(1) anomaly; `RH = f(T, Td)` (Magnus formula), clipped 5–100 %. Gives the natural inverse daily cycle |
| **Pressure (station)** | `mslp_normal − elevation correction (~14 hPa at 120 m)` + semi-diurnal tide `1.5·cos(2π(h − 10)/12)` (peaks ~10:00 and ~22:00) + slow AR(1) synoptic term + storm dips |
| **Wind speed** | `wind_normal(doy)` × diurnal factor (min ~06:00, max ~15:00) × positive random noise (gamma/Weibull-like) + wind-spell boost + storm spikes |

### 7.3 Events [FR-SYN-04]

| Event | When | Effect |
|---|---|---|
| Heat spell | Mainly Apr–May; 3–7 days | `spell_anom` +3 to +7 °C on Tmax, ramp up/down over a day; RH slightly lower |
| Wind spell | Mainly Jun–Sep; 1–5 days | Wind ×1.5–2.5, strongest in afternoons |
| Pre-monsoon storm | Mar–May, 14:00–19:00 | 60–90 min before: pressure −1.5 to −3 hPa; at onset: temperature −5 to −8 °C, RH +20–30 %, pressure jump +1–2 hPa, wind spike to 12–20 m/s for 15–45 min, then recovery over 1–3 h |

Event counts/amplitudes come from `synthetic.yaml`. After generation, the generator computes the label shares using `ml/core/labels.py`, and if the combined hazard-hour share is outside the target range (3–5 %), it rescales event amplitudes and regenerates (max 5 iterations, deterministic with the seed). Achieved shares are written to `<output>.meta.json`.

### 7.4 Sensor layer [FR-SYN-05]

| Sensor | Model |
|---|---|
| BME280 temp / hum / pressure | true + Gaussian noise (σ 0.1 °C, 0.8 %, 0.1 hPa) |
| DHT11 temp / hum | true + slow-drifting bias (±1 °C, ±3 %) + noise (σ 0.8 °C, 2 %), then **rounded to whole numbers**; occasional 1–6 h disagreement episodes (bias ±3–4 °C) |
| Anemometer | true wind + small noise, clipped ≥ 0, rounded to 0.1 m/s |

### 7.5 Faults
Applied last, on the sensor layer: random spikes, stuck runs (value frozen 1–3 h), gaps (rows removed, 10–60 min), offline periods (rows removed, 1–12 h), BME failures (BME fields null, 1–6 h). Each fault is recorded in `<output>.faults.csv` so QC can be tested against ground truth.

### 7.6 Output
Parquet with exactly the telemetry fields + `kit_id`, `ts` (UTC), plus metadata/fault files. ~315,000 rows.

---

## 8. Kit simulator

`tools/kit_simulator.py` [FR-SIM-01] — uses the generator's signal model to publish live readings.

| Option | Purpose |
|---|---|
| `--kit kit01` | kit id / topic |
| `--interval 5m` (or `60s`) | sending interval |
| `--speed 1` | time acceleration (e.g. 60 = one hour per minute) |
| `--start-date` | simulated date (e.g. a May afternoon) |
| `--force wind:red` / `heat:orange` | inject a hazard event now |
| `--no-ts` | omit `ts` (tests arrival-time rule) |
| `--faults` | enable live fault injection |
| `--drop` | disconnect without clean close → Last-Will `offline` |

On connect it publishes retained `online` to the status topic, with `offline` registered as Last-Will.

---

## 9. ML pipeline

### 9.1 Steps (`python -m ml.cli …`)

| Command | Does |
|---|---|
| `generate` | Build synthetic dataset (section 7) |
| `build` | QC + fusion (offline, same functions) → hourly aggregation → features + labels → `ml/data/train_v{N}.parquet` |
| `train` | Train 6 models → `ml/models/v{N}/` |
| `evaluate` | Metrics + feature importance into `metadata.json`, print summary |
| `activate v{N}` | Point `ml/models/active` at a version |

### 9.2 Hourly aggregation (`ml/core/aggregate.py`)
For each hour *h* = [h, h+1) per kit, using **fused** values and excluding readings with `out_of_range`/`spike`/`stuck` flags on that variable:

| Column | Aggregation |
|---|---|
| `temp_mean`, `temp_max`, `temp_min` | of `temp_c` |
| `hum_mean` | of `hum_pct` |
| `pressure_mean`, `pressure_last` | of `pressure_hpa` |
| `wind_mean`, `wind_max` | of `wind_speed_ms` |
| `n_readings`, `expected_readings` | for coverage |
| `fallback_any` | any fused value from DHT11 |

Hours with no data are `NaN`; gaps ≤ 30 min are linearly interpolated on the 5-min series **before** aggregation [FR-INF-02].

### 9.3 Labels (`ml/core/labels.py`) [FR-ML-01]
For prediction time *t* (an hour boundary), window = (t, t + 3 h] on the 5-min fused series:

```
peak_wind_kmh = max(wind_speed_ms) * 3.6
tmax          = max(temp_c)
departure     = tmax − tmax_normal(date_local(t))
abs_thr       = coastal ? 37 : 40

wind_yellow = peak_wind_kmh ≥ 30
wind_orange = peak_wind_kmh ≥ 40
wind_red    = peak_wind_kmh ≥ 60

heat_red    = tmax ≥ 45
heat_orange = (tmax ≥ abs_thr and departure ≥ 6.5) or heat_red
heat_yellow = (tmax ≥ abs_thr and departure ≥ 4.5) or heat_red
```

If the window has < 75 % of expected readings, labels are `NaN` and the row is dropped from training.

### 9.4 Features (`ml/core/features.py`) [FR-ML-02]
Input: hourly table up to and including the hour ending at *t*. Output: one row per *t*.

| Group | Features |
|---|---|
| Current | `temp_mean`, `temp_max`, `temp_min`, `hum_mean`, `pressure_mean`, `wind_mean`, `wind_max` (last hour) |
| Derived | `dewpoint` (Magnus), `departure = temp_max − tmax_normal(date)`, `tmax_normal` |
| Lags | `temp_mean`, `hum_mean`, `pressure_mean`, `wind_max` at 1, 2, 3, 6, 12, 24 h |
| Tendencies | 1 h and 3 h differences of temp, hum, pressure, wind |
| Rolling (6/12/24 h) | mean, min, max, std of temp, hum, pressure, wind_max |
| Time | `sin/cos(2π·hour_local/24)`, `sin/cos(2π·doy/365.25)` |
| Quality | `coverage_24h` (share of expected readings) |

`feature_list` (ordered names) is saved with each model version; inference refuses to run if the live feature names do not match.

### 9.5 Training [FR-ML-03]
- One `XGBClassifier` per label (6 total), library default hyper-parameters, `random_state` from config.
- Random 80/20 split (`train_test_split`, seed, stratified on the label).
- No class weighting, no time-based split, no baseline (v1 decision).
- Models saved in XGBoost JSON format: `ml/models/v{N}/{hazard}_{level}.json`.

### 9.6 Evaluation [FR-ML-04]
On the 20 % split per model: precision, recall, F1 (at 0.5), PR-AUC, Brier score, positive rate, top-15 feature importances (gain). Written to `metadata.json` with the note *"synthetic data, random split — not real-world accuracy"*.

### 9.7 Registry [FR-ML-05]

```
ml/models/
  active                 # text file containing "v1"
  v1/
    wind_yellow.json  wind_orange.json  wind_red.json
    heat_yellow.json  heat_orange.json  heat_red.json
    metadata.json        # version, created_at, data file + hash, config snapshot,
                         # feature_list, label definitions, metrics
```

The backend's `model_store` loads the active version at start-up; `GET /api/system` reports it.

---

## 10. Inference design

### 10.1 Schedule [FR-INF-01]
APScheduler cron job: `minute = 0`, timezone `Asia/Kolkata`, `misfire_grace_time = 300 s`, `max_instances = 1`. Manual trigger: `POST /api/predictions/run`.

### 10.2 Run steps (`inference/runner.py`)

```
for kit in enabled kits:
    t = current hour boundary (UTC)
    df = readings for kit in [t − 48 h, t]
    sufficiency:
        missing_share_24h = 1 − received/expected over [t − 24 h, t]
        latest gap        = t − last reading ts
        if missing_share_24h > 0.25 or latest gap > 60 min:
            store predictions (wind, heat) with status = insufficient_data
            broadcast; skip alerts; continue
    hourly = aggregate(interpolate_small_gaps(df))
    x = build_features(hourly, t)                     # 1 row
    for hazard in (wind, heat):
        p = [model[hazard, lvl].predict_proba(x) for lvl in (yellow, orange, red)]
        p_orange = min(p_orange, p_yellow); p_red = min(p_red, p_orange)   # monotonic
        level = highest lvl with p ≥ 0.50, else green
        upsert prediction (status ok, valid_until = t + 3 h, model_version,
                           fallback_used = any fallback in last 24 h,
                           context = {tmax_normal, missing_share, …})
        broadcast {type: "prediction"}
        alert_engine.evaluate(prediction)
```

Target run time well under 60 s [NFR-05] (one row, six small models).

### 10.3 Level selection (`ml/core/levels.py`)
Shared function used by inference and the History page export, so colours are computed in one place.

---

## 11. Alert engine

### 11.1 Logic [FR-ALT-01..06]

```
RANK = {green: 0, yellow: 1, orange: 2, red: 3}

evaluate(prediction):
    if prediction.status != ok or prediction.level not in config.alerts.levels:
        return
    last = latest alert for (kit, hazard) with email_status = sent
           and created_at > now − cooldown_hours
    if not config.alerts.enabled:
        status = disabled
    elif last is None or RANK[level] > RANK[last.level]:
        try: send email → status = sent
        except SMTPError as e: status = failed, error = str(e)
    else:
        status = cooldown
    insert alert row; broadcast {type: "alert"}
```

- Cooldown is per kit **and** hazard: wind and heat alerts are independent.
- Escalation (Orange → Red) sends immediately; Red after Red within 3 h is `cooldown`.
- A `failed` send does not start a cooldown (the next hour retries).

### 11.2 Email
- Sent with aiosmtplib (STARTTLS for Gmail; plain for Mailpit).
- Subject: `[ORANGE] Wind risk at Karur Campus — next 3 h`.
- Body (HTML + plain-text, Jinja2): site and kit, level, probabilities per level, valid until (IST), latest readings (temperature, humidity, pressure, wind km/h), model version, fallback note, dashboard link (`FRONTEND_URL`), note that v1 models are trained on synthetic data.

---

## 12. Frontend design

### 12.1 Visual design
The **Claude Design HTML, `docs/design/ui_reference_v1.html`, is the visual reference** (layout, spacing, typography, colours). Design tokens (colours, radii, font sizes) are copied from it into `src/styles/tokens.css`. Behaviour and data follow the requirements [FR-UI-00].

### 12.2 Structure

```
frontend/
  index.html
  vite.config.js            # dev proxy /api and /ws → localhost:8000
  src/
    main.jsx  App.jsx        # router, providers
    api/
      client.js              # fetch wrapper: base URL, JWT header, 401 → logout
      endpoints.js           # one function per REST endpoint
    hooks/
      useAuth.js             # login/logout, token in memory + sessionStorage
      useTheme.js            # light/dark/system, persisted in localStorage
      useLive.js             # WebSocket connect, reconnect with backoff, dispatch
      usePolling.js          # fallback refresh when socket is down
    context/
      AuthContext.jsx  ThemeContext.jsx  LiveDataContext.jsx
    pages/
      LoginPage.jsx  DashboardPage.jsx  HistoryPage.jsx  AlertsPage.jsx  KitSystemPage.jsx
    components/
      layout/   TopBar.jsx  NavMenu.jsx  ProtectedRoute.jsx
      hazard/   HazardCard.jsx  LevelBadge.jsx  ProbabilityBar.jsx
      sensors/  SensorCard.jsx  QcBadge.jsx  TrendArrow.jsx
      charts/   TimeSeriesChart.jsx  WindChart.jsx  RiskTimeline.jsx
      common/   DateRangePicker.jsx  DataTable.jsx  Pagination.jsx  StatusDot.jsx
    utils/
      time.js                # UTC → IST formatting
      units.js               # m/s → km/h
      levels.js              # level → label/colour token
    styles/
      tokens.css  global.css
```

JavaScript (not TypeScript) to keep the codebase simple for v1.

### 12.3 Routing

| Path | Page | Auth |
|---|---|---|
| `/login` | Login | public |
| `/` | Live Dashboard | admin |
| `/history` | History | admin |
| `/alerts` | Alerts | admin |
| `/kit` | Kit & System | admin |

### 12.4 Data flow
- **Initial load** of each page uses REST.
- **Live updates** come from `/ws/live` through `LiveDataContext`:
  - `reading` → update sensor cards, append to 24 h chart series (drop points older than 24 h)
  - `kit_status` → top bar status dot
  - `prediction` → hazard cards
  - `alert` → toast notification + Alerts page refresh if open
- If the socket drops: reconnect with backoff (1, 2, 5, 10, 30 s) and poll `/api/readings/latest` every 30 s until it is back.

### 12.5 Theme [FR-UI-01]
- `data-theme="light" | "dark"` on `<html>`; tokens defined for both.
- Default follows `prefers-color-scheme`; the toggle stores `light`/`dark`/`system` in `localStorage`.
- Hazard level colours have light and dark variants with text contrast ≥ 4.5:1; levels also carry a text label (never colour alone).
- Recharts colours read from CSS variables so charts switch with the theme.

### 12.6 Responsive
Breakpoints: ≥ 1024 px desktop (2-column hazard cards, 4 sensor cards in a row, 2×2 charts); 640–1023 px tablet; < 640 px mobile (single column, ☰ menu, tables become stacked cards).

---

## 13. API design

### 13.1 Conventions
- JSON, UTC ISO-8601 timestamps; the frontend converts to IST.
- Wind in **m/s** in the API (as stored); the frontend shows km/h.
- Errors: `{"detail": "message"}` with standard HTTP codes (400, 401, 404, 422, 500).
- Auth: `Authorization: Bearer <jwt>` on all routes except `/api/auth/login` and `/api/health`.

### 13.2 Example responses

`POST /api/auth/login`
```json
{ "access_token": "eyJ…", "token_type": "bearer", "expires_at": "2026-10-31T16:00:00Z" }
```

`GET /api/readings/latest?kit_id=kit01`
```json
{
  "kit_id": "kit01", "ts": "2026-10-31T09:01:00Z", "ts_source": "kit",
  "temp_c": 36.4, "hum_pct": 42.0, "pressure_hpa": 1004.2, "wind_speed_ms": 6.7,
  "temp_bme_c": 36.4, "hum_bme_pct": 42.0, "temp_dht_c": 37.0, "hum_dht_pct": 45.0,
  "wind_gust_ms": null, "rain_mm": null, "fallback": false,
  "qc_flags": ["wind_speed:spike"],
  "trend": { "temp_c": "up", "hum_pct": "down", "pressure_hpa": "down", "wind_speed_ms": "up" }
}
```

`GET /api/predictions/latest?kit_id=kit01`
```json
{
  "run_at": "2026-10-31T08:30:00Z",
  "items": [
    { "hazard": "wind", "status": "ok", "level": "yellow",
      "p": { "yellow": 0.72, "orange": 0.41, "red": 0.04 },
      "valid_until": "2026-10-31T11:30:00Z", "model_version": "v1", "fallback_used": false },
    { "hazard": "heat", "status": "ok", "level": "green",
      "p": { "yellow": 0.18, "orange": 0.06, "red": 0.0 },
      "valid_until": "2026-10-31T11:30:00Z", "model_version": "v1", "fallback_used": false,
      "context": { "tmax_normal_c": 37.2 } }
  ]
}
```

`GET /api/quality?kit_id=kit01&hours=24`
```json
{ "received": 286, "expected": 288, "gaps": [{ "from": "…", "to": "…", "minutes": 10 }],
  "flags": { "spike": 2, "stuck": 0, "out_of_range": 0, "bme_dht_mismatch": 1 },
  "fallback_minutes": 0 }
```

`GET /api/readings?kit_id=&from=&to=` returns raw 5-min points for ranges ≤ 7 days and hourly aggregates (mean/min/max) for longer ranges, so 30-day charts stay fast.

`GET /api/readings/export.csv` streams CSV: readings joined with the prediction (level + probabilities) of the hour they fall in.

### 13.3 WebSocket `/ws/live?token=<jwt>`
Invalid/expired token → close code 4401. Server → client messages:

```json
{ "type": "reading",    "data": { …same as readings/latest… } }
{ "type": "kit_status", "data": { "kit_id": "kit01", "status": "offline", "ts": "…" } }
{ "type": "prediction", "data": { …one item from predictions/latest… } }
{ "type": "alert",      "data": { "hazard": "wind", "level": "orange", "probability": 0.58,
                                  "email_status": "sent", "created_at": "…" } }
```

Server sends a ping every 30 s; clients that fail are dropped from the hub.

---

## 14. Security

- Admin created on first start from `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` if no user exists; password hashed with bcrypt (cost 12). Changing the `.env` password later does not overwrite the stored hash.
- JWT HS256 signed with `JWT_SECRET`, expiry `JWT_EXPIRE_HOURS` (8). Frontend keeps the token in memory and `sessionStorage` (cleared when the browser tab closes).
- Login rate limit: 5 failed attempts per minute per IP → 429.
- CORS limited to `CORS_ORIGINS`.
- Mosquitto: v1 runs on localhost; username/password can be enabled via `.env` before connecting the real kit over the network.
- `.env`, `ml/data/`, logs are git-ignored [NFR-08].

---

## 15. Error handling and logging

| Situation | Behaviour |
|---|---|
| Broker unavailable | MQTT task retries with backoff (1 → 30 s); `/api/health` shows `mqtt: down` |
| Database unavailable | Ingestion logs and drops the message (kit keeps sending); health shows `db: down`; reconnect automatic [NFR-07] |
| Invalid payload | Logged with topic and reason (rate-limited log), not stored |
| No active model | Predictions stored as `insufficient_data` with context `no_model`; error logged |
| Prediction job error | Logged with traceback; next hour runs normally |
| SMTP failure | Alert `failed` with error; retried next hour |

Logging: Python `logging`, console + `logs/backend.log` (rotating, 5 × 5 MB), format `time level module message` [NFR-06].

---

## 16. Testing strategy [NFR-10]

| Level | What |
|---|---|
| Unit (`tests/ml`) | QC rules (each flag), fusion cases, normals interpolation, aggregation, label thresholds (boundary values 29.9/30/60 km/h, 40 °C with 4.4/4.5/6.5 departure, 45 °C), feature builder (no future leakage), level selection + monotonic fix |
| Unit (`tests/backend`) | Payload validation, timestamp rules, alert cooldown/escalation/failed/disabled, JWT |
| Integration | Simulator → Mosquitto → backend → DB (requires local broker + DB); forced `wind:red` → prediction → email in Mailpit |
| Generator | Same seed → identical output; hazard share within 3–5 %; injected faults detected by QC |
| Frontend | Vitest for utils (time, units, levels); manual check of pages in light/dark and mobile widths |

---

## 17. Local runtime

| Component | Address | Started by |
|---|---|---|
| Mosquitto (project's own) | `localhost:1884` | `scripts/start_broker.ps1` |
| PostgreSQL | `localhost:5432` | Windows service |
| Backend | `http://localhost:8000` (docs at `/docs`) | `scripts/start_backend.ps1` |
| Frontend | `http://localhost:5173` | `scripts/start_frontend.ps1` |
| Simulator | — | `scripts/start_simulator.ps1` |
| Mailpit (optional) | SMTP `localhost:1025`, UI `localhost:8025` | `mailpit.exe` |

First-time setup (detailed in README): install Python 3.11+, Node.js 20+, PostgreSQL, Mosquitto → create DB → copy `.env.example` to `.env` → `scripts/init_db.ps1` (Alembic migrations) → `python -m ml.cli generate build train evaluate activate v1` → start backend, frontend, simulator.

---

## 18. Traceability

| Requirement area | Design section | Main modules |
|---|---|---|
| FR-CFG | 4 | `backend/app/settings.py`, `config/` |
| FR-MQTT | 6, 8, `docs/mqtt_contract.md` | `mqtt/`, `tools/kit_simulator.py` |
| FR-ING, FR-QC | 6 | `ingest/`, `ml/core/qc.py`, `ml/core/fusion.py` |
| FR-DB | 5 | `models.py`, `alembic/` |
| FR-SYN, FR-SIM | 7, 8 | `ml/synthetic/`, `tools/` |
| FR-ML | 9 | `ml/core/`, `ml/train.py`, `ml/evaluate.py`, `ml/registry.py` |
| FR-INF | 10 | `inference/`, `ml/core/levels.py` |
| FR-ALT | 11 | `alerts/` |
| FR-AUTH | 14 | `security.py`, `api/auth.py` |
| FR-API | 13 | `api/`, `ws/hub.py` |
| FR-UI | 12 | `frontend/src/` |
| NFR | 2.2, 15, 16, 17 | `run.py`, `scripts/`, `tests/` |

---

## 19. Design decisions and open points

| # | Decision / point | Status |
|---|---|---|
| 1 | Single Uvicorn worker with in-process MQTT, scheduler and WebSocket hub | Decided |
| 2 | Shared `ml/core` package for QC, features, labels, levels | Decided |
| 3 | PostgreSQL without TimescaleDB; hourly aggregates by query | Decided |
| 4 | Explicit `qc` section in `site.yaml` (limits configurable) | Added by design — reflect in requirements |
| 5 | Alert status `disabled` when alerts are switched off | Added by design — reflect in requirements |
| 6 | History API returns hourly aggregates for ranges > 7 days | Added by design |
| 7 | JavaScript (not TypeScript) for the frontend | Proposed |
| 8 | Gmail SMTP for real alerts, Mailpit as optional test inbox | Decided |
| 9 | IMD normals values and exact thresholds | Pending D8 (before Phase 3) |
| 10 | Claude Design HTML saved as `docs/design/ui_reference_v1.html` | Decided |
