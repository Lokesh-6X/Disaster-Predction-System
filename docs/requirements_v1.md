# Requirements — Site Weather Hazard Prediction System (v1)

| | |
|---|---|
| **Version** | v1 (prototype) |
| **Status** | Draft — agreed in planning discussion |
| **Site** | Karur, Tamil Nadu (inland) |
| **Last updated** | 2026-10-31 |

Requirement IDs (e.g. `FR-ING-03`) are used for traceability during build and testing.
**Must** = required for v1. **Should** = wanted, can slip if time is short.

---

## 1. Purpose

Build a system that receives live readings from a weather-sensing kit installed at a site, predicts **heat** and **high-wind** hazards for the **next 3 hours** using machine-learning models, and shows readings, predictions and alerts on an admin-only website, with **email alerts** for serious risk.

v1 is a **working prototype**. Its goals are:

1. A complete, running end-to-end pipeline (kit → server → ML → dashboard → email).
2. Collecting clean, well-labelled **real kit data** that the next version will be trained on.

Prediction accuracy is **not** a v1 goal. v1 models are trained on synthetic data and may be inaccurate.

---

## 2. Scope

### 2.1 In scope (v1)

- One site, one kit (`kit01`).
- Hazards: **Heat** and **High wind**.
- Prediction horizon 3 h, predictions run every hour.
- Models trained on a **synthetic dataset** that mimics the kit's real-time data.
- Email alerts to the single admin.
- Admin-only web dashboard (single admin account).
- Everything runs **locally on Windows** (no Docker).

### 2.2 Out of scope (planned for later versions)

| Item | Planned for |
|---|---|
| Heavy-rainfall prediction, rain gauge (DFRobot SEN0575) | Later version |
| Retraining / fine-tuning on real kit data | Next version |
| Multiple kits per site (data model is ready: keyed by `kit_id`) | Next version |
| Multiple users / roles | Later version |
| Minute-level ML features | Later version |
| External forecast data (NWP), ERA5, airport data | Not planned |
| Class weighting, time-based split, baseline comparison | Not in v1 |
| Comparing other models (Logistic Regression, Random Forest), Optuna tuning, probability calibration | Not in v1 — XGBoost only, default settings |
| Editing thresholds from the dashboard | Later version |
| Docker deployment | Not in v1 |
| Firmware changes (true gust measurement, NTP) | Not in v1 — firmware is fixed |

---

## 3. Definitions

| Term | Meaning |
|---|---|
| **Kit** | ESP32-class board with BME280 (temp/humidity/pressure), DHT11 (temp/humidity) and an anemometer (wind speed). |
| **Reading** | One telemetry message from the kit. |
| **QC** | Quality control — automatic checks that flag bad readings. |
| **Fallback** | Using DHT11 values when the BME280 value is unusable. |
| **Normal daily max** | Expected maximum temperature for a calendar day, from IMD 30-year monthly normals interpolated to daily values. |
| **Departure** | Temperature minus the normal daily max for that date. |
| **Peak wind** | Highest reported `wind_speed` in a time window (used in place of a true gust). |
| **Level** | Risk colour: Green, Yellow, Orange, Red. |
| **IST / UTC** | All data is stored in UTC and shown in IST (Asia/Kolkata). |

---

## 4. System overview

```
 Kit (ESP32) ──MQTT──► Mosquitto (port 1884)
                              │
                              ▼
                 FastAPI backend (localhost:8000)
                  ├─ MQTT ingestion → validation → QC → database
                  ├─ Hourly scheduler → features → 6 XGBoost models → predictions
                  ├─ Alert engine → email (SMTP)
                  ├─ REST API + WebSocket /ws/live
                  └─ JWT auth (single admin)
                              │
                              ▼
                 React dashboard (localhost:5173)

 Offline (ML pipeline):
   synthetic generator → labels → features → training → model registry
```

### 4.1 Technology

| Part | Technology |
|---|---|
| Broker | Mosquitto — the project's own instance on port 1884, login + ACL required |
| Backend | Python 3.11+, FastAPI, Uvicorn, async MQTT client, Pydantic |
| Database | PostgreSQL |
| ML | pandas, NumPy, XGBoost, scikit-learn |
| Frontend | React + Vite, Recharts |
| Email | Gmail SMTP (app password); Mailpit as optional local test inbox |

---

## 5. Configuration

### FR-CFG-01 — Site config file (Must)
`config/site.yaml` holds all site-specific settings so a new location needs no code change:

| Section | Contents |
|---|---|
| `site` | `name`, `latitude` (≈10.96), `longitude` (≈78.08), `elevation_m` (≈120), `timezone` (Asia/Kolkata), `coastal` (false) |
| `kits` | List of kits: `kit_id`, `description`, `latitude`, `longitude`, `anemometer_height_m`, `enabled`, mounting notes |
| `hazards.wind` | Level thresholds in km/h: Yellow 30, Orange 40, Red 60 |
| `hazards.heat` | Absolute threshold 40 °C (37 °C if coastal), departure Yellow +4.5 °C, Orange +6.5 °C, Red absolute 45 °C |
| `hazards.rain` | `enabled: false` (placeholder) |
| `qc` | Range limits, spike limits (per minute), stuck duration, BME/DHT mismatch limits, future-timestamp tolerance |
| `prediction` | Show-level probability cut-off (0.50), horizon (3 h), run interval (60 min), feature history (48 h) |
| `data_sufficiency` | Max interpolated gap (30 min), max missing share of last 24 h (25 %), require data in last 60 min |
| `kit_status` | Offline after no data for 10 min |
| `alerts` | `enabled` (true), levels that email (Orange, Red), cooldown (3 h) |
| `normals` | IMD monthly normal max/min temperature (and humidity, wind) for Karur / Tiruchirappalli |

### FR-CFG-02 — Synthetic data config (Must)
`config/synthetic.yaml`: years (3), interval (5 min), start date, random seed, hazard rate target (3–5 % of hours), fault injection on/off and rates.

### FR-CFG-03 — Secrets (Must)
Secrets live in `.env` (never committed): database URL, admin username/password, admin email address, JWT secret, SMTP host/port/user/password. An `.env.example` with placeholders is provided.

### FR-CFG-04 — Validation (Must)
The backend validates both config files at start-up and refuses to start with a clear error if they are invalid.

---

## 6. MQTT contract

Full contract in `docs/mqtt_contract.md`.

### FR-MQTT-01 — Topics (Must)
| Topic | Purpose |
|---|---|
| `weather/kit/{kit_id}/telemetry` | Readings (QoS 1) |
| `weather/kit/{kit_id}/status` | `online` / `offline` (retained; `offline` set as Last-Will) |

The backend subscribes to `weather/kit/+/telemetry` and `weather/kit/+/status`. `kit_id` is taken from the topic.

### FR-MQTT-02 — Payload (Must)
JSON object:

| Field | Type | Required | Notes |
|---|---|---|---|
| `ts` | string (ISO 8601, UTC) | No | If missing, arrival time is used and flagged |
| `temp_bme_c` | number | Yes* | °C |
| `hum_bme_pct` | number | Yes* | % |
| `pressure_hpa` | number | Yes* | hPa (station pressure) |
| `temp_dht_c` | number | Yes* | °C |
| `hum_dht_pct` | number | Yes* | % |
| `wind_speed_ms` | number | Yes* | m/s, as reported by the kit |
| `wind_gust_ms` | number \| null | No | Reserved for future firmware |
| `rain_mm` | number \| null | No | `null` until rain gauge is fitted |
| `fw_version` | string | No | Firmware version |

\* A field may be `null` if the sensor failed; the reading is still stored and flagged.

### FR-MQTT-03 — Sending interval (Must)
The system accepts any interval from 1 to 5 minutes without configuration changes.

---

## 7. Ingestion and quality control

### FR-ING-01 — Subscriber (Must)
An async MQTT subscriber runs inside the backend, reconnects automatically, and logs connection state.

### FR-ING-02 — Validation (Must)
Each message is parsed with a Pydantic model. Malformed JSON or wrong types are rejected and logged (not stored as readings). Unknown `kit_id`s are logged and ignored.

### FR-ING-03 — Timestamp rules (Must)
- `ts` more than **10 min in the future** → reading rejected and logged.
- `ts` missing → arrival time used, flag `ts_missing`.
- Duplicate (`kit_id`, `ts`) → ignored.

### FR-QC-01 — Range checks (Must)
Values outside plausible ranges are flagged `out_of_range` (defaults, configurable):

| Variable | Range |
|---|---|
| Temperature | 0 – 55 °C |
| Humidity | 0 – 100 % |
| Pressure | 950 – 1050 hPa |
| Wind speed | 0 – 60 m/s |

### FR-QC-02 — Spike check (Must)
A change between consecutive readings larger than a configured limit (e.g. temperature > 5 °C in 5 min, pressure > 3 hPa in 5 min) is flagged `spike`.

### FR-QC-03 — Stuck-sensor check (Must)
The same value repeated for ≥ 60 min is flagged `stuck` (wind speed of exactly 0 is excluded, since calm is valid).

### FR-QC-04 — Sensor fusion (Must)
- **BME280 is primary** for temperature and humidity.
- If the BME280 value is missing or flagged, the **DHT11** value is used and the reading is marked `fallback`.
- If both are available and differ by **> 3 °C** or **> 10 % RH**, flag `bme_dht_mismatch`.
- The fused values (`temp_c`, `hum_pct`) are stored alongside the raw values.

### FR-QC-05 — Flags stored, not deleted (Must)
Flagged readings are stored with their flags. Nothing is discarded, so future training can filter as needed.

### FR-ING-04 — Kit status (Must)
- Status messages update the kit's online/offline state.
- A kit with no reading for **10 min** is marked offline even without a Last-Will.
- Status changes are stored (for the 7-day online/offline strip) and pushed over the WebSocket.

---

## 8. Data storage

### FR-DB-01 — Tables (Must)

| Table | Contents |
|---|---|
| `kits` | `kit_id`, description, location, mounting info, `fw_version`, `last_seen`, `status` |
| `kit_status_log` | `kit_id`, time, status (online/offline) |
| `readings` | `kit_id`, `ts`, raw values (BME, DHT, wind, gust, rain), fused `temp_c` / `hum_pct`, QC flags, `ts_source` (kit/arrival), received time |
| `predictions` | run time, `kit_id`, hazard, per-level probabilities, final level, valid-until, model version, `fallback_used`, `status` (ok / insufficient_data) |
| `alerts` | time, `kit_id`, hazard, level, probability, valid-until, email status (sent / cooldown / failed / disabled), error message |
| `users` | username, password hash, email, role (admin) — one row in v1 |

### FR-DB-02 — Indexing (Must)
`readings` is indexed on (`kit_id`, `ts`). Hourly aggregates are computed by query (no TimescaleDB required).

### FR-DB-03 — Retention (Must)
All readings, QC flags, predictions and alerts are kept **permanently** (no automatic deletion).

---

## 9. Synthetic dataset

### FR-SYN-01 — Same format as the kit (Must)
The generator produces rows with exactly the MQTT payload fields (plus `kit_id`), so the same code path handles synthetic and real data.

### FR-SYN-02 — Size and resolution (Must)
3 years at 5-minute intervals (~315,000 rows), output as CSV or Parquet in `ml/data/synthetic/`.

### FR-SYN-03 — Realistic Karur climate (Must)
- Monthly levels tuned to **IMD climate normals** (Karur / Tiruchirappalli).
- Daily cycle: minimum near sunrise, maximum 14:00–16:00 IST; humidity opposite to temperature.
- Seasons: hot dry Mar–May; windy Jun–Sep (steady westerlies); humid Oct–Dec; mild Jan–Feb.
- Pressure: semi-diurnal tide (~±1.5 hPa) plus slow synoptic changes.
- Wind: calmer mornings, windier afternoons; stronger in Jun–Sep.
- Multi-day weather spells (hot spells, windy spells), not a repeating curve.

### FR-SYN-04 — Hazard events (Must)
- Heat spells mainly in April–May.
- Steady strong-wind periods mainly in Jun–Sep.
- Occasional pre-monsoon storm events: pressure dip, humidity jump, temperature drop, wind spike.
- Combined hazard hours ≈ 3–5 % of all hours.

### FR-SYN-05 — Sensor behaviour (Must)
- Random noise on all values.
- DHT11: 1 °C / 1 % resolution, ±2 °C / ±5 % error, occasional disagreement with BME280.
- Injected faults (configurable): spikes, stuck values, missing readings, offline periods.

### FR-SYN-06 — Reproducible (Must)
The same seed and config produce the same dataset.

### FR-SIM-01 — Kit simulator (Must)
`tools/kit_simulator.py` publishes live readings to the broker in the kit's format (using the same generator), with options for interval, speed-up, forcing a hazard (e.g. "Red wind now") and simulating offline / Last-Will.

---

## 10. Machine learning

### FR-ML-01 — Labels (Must)
Labels are computed for each hour *t* from the readings in (*t*, *t* + 3 h]. Levels are **cumulative** ("this level or worse"):

**Wind** — peak wind = max `wind_speed` in the window, in km/h:

| Model | Event |
|---|---|
| `wind_yellow` | peak wind ≥ 30 km/h |
| `wind_orange` | peak wind ≥ 40 km/h |
| `wind_red` | peak wind ≥ 60 km/h |

**Heat** — Tmax = max fused temperature in the window; departure = Tmax − normal daily max for that date:

| Model | Event |
|---|---|
| `heat_yellow` | (Tmax ≥ 40 °C and departure ≥ 4.5 °C) or Tmax ≥ 45 °C |
| `heat_orange` | (Tmax ≥ 40 °C and departure ≥ 6.5 °C) or Tmax ≥ 45 °C |
| `heat_red` | Tmax ≥ 45 °C |

(Thresholds read from `site.yaml`; 37 °C replaces 40 °C if `coastal: true`.)

### FR-ML-02 — Features (Must)
Built from **hourly** aggregates of the kit's readings (fused values), using only what the kit measures:

- Current hourly values: temperature, humidity, pressure, wind mean, wind max.
- Derived: dew point; departure from normal daily max.
- Lags: 1, 2, 3, 6, 12, 24 h.
- Tendencies: 1 h and 3 h change (temperature, pressure, humidity, wind).
- Rolling stats over 6, 12, 24 h: mean, min, max, std.
- Time encodings: hour of day and day of year as sine/cosine.

The **same feature code** is used for training and live inference.

### FR-ML-03 — Models (Must)
- Six binary XGBoost classifiers (3 levels × 2 hazards), default hyper-parameters.
- Random train/test split (80/20).
- No class weighting, no time-based split, no baseline comparison (v1 decision).

### FR-ML-04 — Evaluation report (Should)
For each model, record precision, recall, F1, PR-AUC, Brier score and top feature importances in the model's metadata. The report states that scores come from synthetic data with a random split and do not reflect real-world accuracy.

### FR-ML-05 — Model registry (Must)
- Each training run saves to `ml/models/v{N}/`: the 6 model files plus `metadata.json` (version, date, data source, config snapshot, feature list, metrics).
- An `active` pointer selects the version used for inference.
- Every prediction records the model version.

### FR-ML-06 — Reproducible pipeline (Must)
One command each for: generate data, build labels/features, train, evaluate.

---

## 11. Inference

### FR-INF-01 — Schedule (Must)
Predictions run **every hour at minute 00 (IST)** for each enabled kit. A manual "run now" trigger exists for testing.

### FR-INF-02 — Data sufficiency (Must)
Before predicting:
- Gaps ≤ 30 min are filled by linear interpolation.
- If > 25 % of the last 24 h is missing, **or** there is no data in the last 60 min → no prediction; store status `insufficient_data`, show it on the dashboard, send no alerts.

### FR-INF-03 — Output (Must)
- Six probabilities are produced. Probabilities are made monotonic per hazard (P(Orange) ≤ P(Yellow), P(Red) ≤ P(Orange)).
- **Level** = highest level whose probability ≥ **0.50**; otherwise Green.
- Valid-until = run time + 3 h.
- If any input hour used DHT11 fallback, `fallback_used = true`.

### FR-INF-04 — Publish (Must)
Predictions are stored, pushed over the WebSocket, and passed to the alert engine.

---

## 12. Alerts

### FR-ALT-01 — Trigger (Must)
An alert is created when a hazard's level is **Orange or Red** (configurable).

### FR-ALT-02 — Recipient (Must)
Email is sent to the **admin's email address** (from `.env`).

### FR-ALT-03 — Cooldown and escalation (Must)
- After an email for a hazard, no further email for the **same or lower level** of that hazard for **3 h**; such alerts are recorded with status `cooldown`.
- A **higher** level (Orange → Red) is emailed immediately.

### FR-ALT-04 — Email content (Must)
Subject: `[<Level>] <Hazard> risk at <Site> — next 3 h`.
Body: site and kit, level, probabilities per level, valid-until (IST), latest readings, model version, fallback/insufficient-data notes, link to the dashboard.

### FR-ALT-05 — Failures (Must)
SMTP failures are logged, recorded as `failed` with the error, and do not stop the pipeline.

### FR-ALT-06 — Switch (Must)
`alerts.enabled` in config turns email sending on/off (default **on**). Alerts are still recorded when off, with email status `disabled`.

---

## 13. Authentication

### FR-AUTH-01 — Single admin (Must)
One admin account, created on first start from `.env`. The password is stored hashed (bcrypt).

### FR-AUTH-02 — JWT (Must)
`POST /api/auth/login` returns a JWT (default expiry 8 h). All API endpoints except login and health require it. The WebSocket requires the token on connect.

### FR-AUTH-03 — Future users (Should)
The `users` table and role field support adding users later without schema redesign.

---

## 14. API

### FR-API-01 — REST endpoints (Must)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/login` | Log in, get JWT |
| GET | `/api/health` | Backend, broker, DB, email health |
| GET | `/api/kits` | Kits with status and last seen |
| GET | `/api/kits/{kit_id}/status-history?days=7` | Online/offline history |
| GET | `/api/readings/latest?kit_id=` | Latest reading with flags |
| GET | `/api/readings?kit_id=&from=&to=` | Readings in a range (raw + fused + flags) |
| GET | `/api/readings/export.csv?kit_id=&from=&to=` | CSV download (readings + predictions) |
| GET | `/api/predictions/latest?kit_id=` | Latest prediction per hazard |
| GET | `/api/predictions?kit_id=&from=&to=` | Prediction history |
| GET | `/api/alerts?hazard=&level=&from=&to=&page=` | Alerts, paginated |
| GET | `/api/quality?kit_id=&hours=24` | Data-quality summary |
| GET | `/api/system` | Last/next run, active model, settings (read-only) |
| POST | `/api/predictions/run` | Manual prediction run (testing) |

### FR-API-02 — WebSocket (Must)
`/ws/live` pushes messages of types `reading`, `kit_status`, `prediction`, `alert`.

### FR-API-03 — Docs (Should)
FastAPI's automatic OpenAPI docs are available at `/docs`.

---

## 15. Frontend

### FR-UI-00 — Design reference (Must)
The visual design follows the **HTML design reference created in Claude Design**, saved at `docs/design/ui_reference_v1.html`. Page structure and content follow `docs/frontend_pages.md`. Where the two differ, the design reference wins on look and layout; this document wins on behaviour and data.

### FR-UI-01 — General (Must)
- React + Vite + Recharts.
- **Light and dark mode**: follows system setting by default, toggle in top bar, choice remembered.
- **Responsive** (desktop and mobile; menu collapses to ☰ on mobile).
- Times shown in IST; wind shown in km/h.
- Hazard colours readable in both themes.

### FR-UI-02 — Top bar (Must)
Site name, navigation, kit online/offline with last-seen time, current IST time, theme toggle, logout.

### FR-UI-03 — Login page (Must)
Username, password (show/hide), error message, redirect to dashboard on success, auto-logout on token expiry.

### FR-UI-04 — Live Dashboard (Must)
- Two hazard cards (Wind, Heat): level badge, probability per level, valid-until, model version, fallback marker; heat card shows today's normal max; "insufficient data" state.
- Live sensor cards: temperature, humidity, pressure, wind speed with trend arrow, time, QC ⚠ (hover reason); temperature/humidity show DHT11 value.
- 24 h live charts: temperature and humidity (**BME280 and DHT11 lines**), pressure, wind speed with 30/40/60 km/h band lines; legend toggles lines.

### FR-UI-05 — History (Must)
Date range presets (24 h / 7 d / 30 d) and custom range; chart selection; same charts from stored data; predicted-risk timeline per hazard; **CSV download**.

### FR-UI-06 — Alerts (Must)
Table (time, hazard, level, probability, valid-until, email status: Sent / Cooldown / Failed), filters (hazard, level, date), pagination.

### FR-UI-07 — Kit & System (Must)
Kit details and 7-day online/offline strip; data-quality summary (received vs expected, gaps, QC flag counts, fallback time); system status (last/next run, model version, broker/DB/email health); read-only active settings.

---

## 16. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-01 | Runs locally on **Windows 11** without Docker: Mosquitto service, database, backend (`localhost:8000`), frontend (`localhost:5173`). |
| NFR-02 | PowerShell start scripts: `start_backend.ps1`, `start_frontend.ps1`, `start_simulator.ps1`. |
| NFR-03 | `README.md` with step-by-step Windows setup (installs, `.env`, database init, training, running). |
| NFR-04 | A reading appears on the dashboard within **5 s** of being published. |
| NFR-05 | An hourly prediction run completes within **60 s**. |
| NFR-06 | Backend logs to console and a rotating log file (ingestion errors, QC, runs, alerts). |
| NFR-07 | Backend survives broker or database restarts (automatic reconnect). |
| NFR-08 | No secrets in source code or config files committed to the repo. |
| NFR-09 | Storage of one kit at 5-min interval (~105,000 rows/year) handled without special tuning. |
| NFR-10 | Unit tests for QC rules, label rules, feature builder, level selection and alert cooldown. |

---

## 17. Repository layout

```
config/            site.yaml, synthetic.yaml
backend/           ingestion, QC, DB, API, WebSocket, scheduler, alerts, auth
ml/                synthetic generator, labels, features, training, evaluation, registry
  data/            generated datasets (not committed)
  models/          model versions (v1, v2, …)
frontend/          React + Vite app
tools/             kit_simulator.py
docs/              requirements_v1.md, mqtt_contract.md, frontend_pages.md, design/
scripts/           PowerShell start scripts
.env.example
README.md
```

---

## 18. Build phases

| Phase | Deliverable | Done when |
|---|---|---|
| 1. Foundation | Repo layout, config files + validation, `.env.example`, MQTT contract doc, README skeleton | Config loads and validates |
| 2. Ingestion | MQTT subscriber, validation, QC, DB tables, kit status, kit simulator | Simulator data appears in DB with correct flags |
| 3. Synthetic data + ML | Generator, labels, features, 6 models, registry, evaluation | `v1` models saved with metadata |
| 4. Inference + alerts | Scheduler, sufficiency check, predictions, alert engine, email | Forced hazard in simulator → prediction → email received |
| 5. API + dashboard | Auth, REST, WebSocket, 5 pages per design reference | All pages work live with the simulator |
| 6. Real kit | Connect real kit, verify contract and end-to-end flow | Real readings, predictions and alerts flow end-to-end |

---

## 19. Acceptance criteria (v1)

1. The kit simulator (and later the real kit) publishes readings that are validated, QC-flagged and stored.
2. The dashboard shows live readings and kit online/offline status, updating without page reload.
3. Every hour, predictions for Wind and Heat are produced, stored and shown with level and probabilities.
4. Insufficient data results in "insufficient data", not a prediction or alert.
5. A forced Orange/Red hazard produces an email to the admin; repeats within 3 h are suppressed; escalation emails immediately.
6. Only the logged-in admin can access the dashboard and API.
7. History page charts any date range and exports CSV.
8. Light/dark mode and mobile layout work on all pages.
9. All readings, flags, predictions and alerts are retained for next-version training.

---

## 20. Open decisions

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Database: PostgreSQL or SQLite | **Decided: PostgreSQL** (no TimescaleDB) |
| D2 | Email provider | **Decided: Gmail SMTP (app password) for real alerts, Mailpit as optional test inbox** |
| D3 | Installed tools: Python version, Node.js, Mosquitto | To confirm |
| D4 | Firmware details: wind value instantaneous or averaged; actual sending interval; does the kit send `ts` | Contract handles all cases |
| D5 | Frontend: extra derived values (dew point, "feels like")? | Not in v1 unless requested |
| D6 | Alerts table: show cooldown/failed rows or sent only? | Show all with status |
| D7 | File name/location of the Claude Design HTML reference | **Decided: `docs/design/ui_reference_v1.html`** |
| D8 | Exact IMD thresholds and Karur normals | Verify against IMD sources before Phase 3 |
