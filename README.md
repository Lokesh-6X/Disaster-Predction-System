# Site Weather Hazard Prediction System (v1)

A site weather kit (ESP32 + BME280 + DHT11 + anemometer) sends readings over MQTT to a FastAPI backend. Every hour, XGBoost models predict **heat** and **high-wind** risk for the next 3 hours. Readings, predictions and alerts appear on an admin-only React dashboard, and Orange/Red risk is emailed to the admin.

v1 is a prototype for one site (Karur) and one kit; its models are trained on synthetic data.

| Document | Purpose |
|---|---|
| [docs/analysis/analysis_v1.md](docs/analysis/analysis_v1.md) | Why — problem, feasibility, decisions, risks |
| [docs/requirements_v1.md](docs/requirements_v1.md) | What — requirements |
| [docs/design/system_design_v1.md](docs/design/system_design_v1.md) | How — system design |
| [docs/implementation_plan_v1.md](docs/implementation_plan_v1.md) | Build phases and tasks |
| [docs/mqtt_contract.md](docs/mqtt_contract.md) | Kit ↔ server message format |
| [docs/frontend_pages.md](docs/frontend_pages.md), [docs/design/ui_reference_v1.html](docs/design/ui_reference_v1.html) | Dashboard pages and visual design |

## Build status

| Phase | Status |
|---|---|
| 0. Local environment | ✅ |
| 1. Foundation (config, MQTT contract, backend skeleton, broker) | ✅ |
| 2. Ingestion (MQTT → QC → PostgreSQL, kit status, simulator) | ✅ |
| 3. Synthetic data + ML (generator, labels, features, 6 XGBoost models, registry) | ✅ |
| 4. Inference + alerts (hourly scheduler, predictions, email alerts) | ✅ |
| 5. API + dashboard (login, REST, WebSocket, 5 pages, light/dark) | ✅ |
| 6. Real kit | ⏳ next |

---

## Prerequisites (Windows)

| Tool | Version | Notes |
|---|---|---|
| Python | 3.13 | `py -3.13` must work |
| Node.js | 20+ | for the dashboard (`frontend/`) |
| PostgreSQL | 16 or 17 | running as a Windows service |
| Mosquitto | 2.x | installed in `C:\Program Files\mosquitto`. This project runs **its own broker on port 1884**; any existing Mosquitto service on 1883 is left alone |
| Mailpit | optional | local test inbox for alert emails |

## First-time setup

Run these from the project folder in PowerShell.

**1. Python environment**
```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

**2. Settings**

Copy `.env.example` to `.env` and replace every `change-me` value with a real secret (`JWT_SECRET` needs at least 32 characters). Set `ADMIN_EMAIL` to the admin's address. The backend refuses to start while placeholders remain.

Site settings (location, kit, thresholds, alerts) are in `config/site.yaml`; synthetic-data settings in `config/synthetic.yaml`.

**3. Database**
```powershell
.\scripts\init_db.ps1
```
Creates the database user and database from `.env`, then applies the schema migrations. It asks for the PostgreSQL superuser (`postgres`) password; the password is not stored. After pulling new migrations, run `.\scripts\init_db.ps1 -MigrateOnly` (no superuser needed).

**4. MQTT broker**
```powershell
.\scripts\setup_broker.ps1        # creates config\mosquitto\mosquitto.conf and passwd from .env
```
Run it again whenever MQTT usernames or passwords in `.env` change.

**5. Models**
```powershell
.venv\Scripts\python.exe -m ml.cli all
```
Generates the synthetic Karur dataset, builds features and labels, trains the six models and makes the new version active (about 30 s). See [ML pipeline](#ml-pipeline) for the individual steps.

## Running

Use a separate PowerShell window for each:

```powershell
.\scripts\start_broker.ps1        # MQTT broker on localhost:1884
.\scripts\start_backend.ps1       # API on http://127.0.0.1:8000  (docs: /docs, health: /api/health)
.\scripts\start_frontend.ps1      # dashboard on http://localhost:5173
.\scripts\start_simulator.ps1     # simulated kit01, one reading every 5 min
```

On first start the backend syncs kits from `site.yaml` and creates the admin user from `.env`. Logs go to the console and `logs\backend.log`.

### Dashboard

Open **http://localhost:5173** and sign in with `ADMIN_USERNAME` (or `ADMIN_EMAIL`) and `ADMIN_PASSWORD` from `.env`. The admin is created on the backend's first start; changing `ADMIN_PASSWORD` later does not change the stored password.

| Page | Shows |
|---|---|
| Dashboard | Heat and wind risk for the next 3 h, live readings (BME280 and DHT11), 24 h / 48 h / 7 d charts, recent alerts |
| History | Any date range, risk timeline, CSV download |
| Alerts | All alerts with email status and whether the hazard actually happened |
| Kits | Kit details, sensor health, data quality, system status, active settings, **Run prediction now** |

The theme button (sidebar or login page) switches system / light / dark. The design follows `docs/design/ui_reference_v1.html`. The dev server forwards `/api` and `/ws` to the backend, so only port 5173 is used in the browser.

### Kit simulator options

| Example | Effect |
|---|---|
| `start_simulator.ps1 --interval 10s` | Faster readings for testing |
| `start_simulator.ps1 --backfill-hours 48 --speed 600` | Fill the last 48 h quickly, then continue live |
| `start_simulator.ps1 --faults` | Occasional spikes and BME280 failures (tests QC and DHT11 fallback) |
| `start_simulator.ps1 --no-ts` | Omit timestamps (server uses arrival time) |
| `start_simulator.ps1 --drop-after 3` | Vanish after 3 readings — the broker's Last-Will marks the kit offline |
| `start_simulator.ps1 --count 10` | Stop cleanly after 10 readings |
| `start_simulator.ps1 --backfill-hours 48 --speed 100000 --count 576 --force wind:orange --force-minutes-ago 200` | Fill 48 h of history containing a sustained Orange wind spell that started 200 min ago, then stop (see [Alerts](#predictions-and-alerts)) |

The simulator uses the same weather model as the training data. `--force wind:LEVEL` builds up over an hour and holds for 4 more; `--force heat:LEVEL` ramps up and holds for 3 hours. Ctrl+C stops it cleanly (status `offline`).

## Predictions and alerts

The backend predicts every hour at **HH:00:30 IST** (`/api/health` shows the next run). Orange and Red risk is emailed to `ADMIN_EMAIL`; repeats of the same or a lower level for that hazard are paused for 3 hours, and a higher level is sent at once.

**Email settings (`.env`):**

| Use | Settings |
|---|---|
| Local test (default) | `SMTP_HOST=localhost`, `SMTP_PORT=1025`, `SMTP_STARTTLS=false`; run `.venv\Scripts\python.exe tools\mail_sink.py` — emails are saved to `logs\mail\*.eml` |
| Gmail | `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_STARTTLS=true`, `SMTP_USER=<gmail address>`, `SMTP_PASSWORD=<16-character app password>`, `SMTP_FROM=<same gmail address>` |

Restart the backend after changing `.env`.

**Try an alert now** (broker, backend, dashboard and — for local email — the mail server running):
```powershell
.\scripts\start_simulator.ps1 --backfill-hours 48 --speed 100000 --count 576 --force wind:orange --force-minutes-ago 200
```
Then on the dashboard's **Kits** page click **Run prediction now**. It predicts for the current hour at once; Orange/Red risk raises an alert (shown as a pop-up and on the Alerts page) and an email. If an alert for that hazard was emailed in the last 3 hours it is recorded as *cooldown* instead.

## ML pipeline

| Command | Does |
|---|---|
| `python -m ml.cli generate` | Synthetic dataset → `ml/data/synthetic/karur_v1.parquet` (+ `.meta.json`, `.events.csv`, `.faults.csv`) |
| `python -m ml.cli build` | QC + fusion → 5-min grid → hourly → 95 features + 6 labels → `ml/data/datasets/` |
| `python -m ml.cli train [--activate]` | Train and evaluate 6 XGBoost models → `ml/models/v{N}/` |
| `python -m ml.cli evaluate [vN]` | Show a version's metrics and top features |
| `python -m ml.cli activate vN` | Use version `vN` for live predictions |
| `python -m ml.cli all` | All of the above, activating the new version |

Run them with `.venv\Scripts\python.exe` from the project folder. Settings: `config/synthetic.yaml` (dataset) and `config/site.yaml` (thresholds, normals). Scores come from synthetic data with a random split and do **not** reflect real-world accuracy.

## Tests and lint

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
```

Database tests create and drop a temporary schema in the local database; they are skipped if PostgreSQL or `.env` is not available.

## Project layout

```
config/        site.yaml, synthetic.yaml, mosquitto/acl
backend/       FastAPI app (run.py starts it)
ml/            synthetic data, shared QC/features/labels (ml/core), training, model registry
frontend/      React dashboard (Phase 5)
tools/         kit simulator (Phase 2)
scripts/       PowerShell setup and start scripts
tests/         pytest tests
docs/          analysis, requirements, design, plan, MQTT contract
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `Configuration error — backend not started` | The message names the file and setting; fix it in `.env` or `config/*.yaml` |
| `Connection Refused: not authorised` from MQTT | Use port 1884 and the usernames/passwords from `.env`; re-run `scripts\setup_broker.ps1` after changing them |
| Port 1884 already in use | Another broker instance is running; close it or change `MQTT_PORT` in `.env` and re-run `setup_broker.ps1` |
| `psql not found` | Add `C:\Program Files\PostgreSQL\17\bin` to PATH |
| `Database not ready ... Retrying` in the backend log | Start PostgreSQL and run `scripts\init_db.ps1` (or `-MigrateOnly`) |
| Health shows `"mqtt": "disconnected"` | Start the broker with `scripts\start_broker.ps1` |
| Health shows `"model": "missing"` | Run `.venv\Scripts\python.exe -m ml.cli all`, then restart the backend |
| Predictions say `insufficient_data` | Less than 75 % of the last 24 h, or no reading in the last hour — check the kit/simulator |
| Alert `failed` in the database | Check the SMTP settings; with Gmail use an app password, not the account password |
| Reading rejected: timestamp in the future | The kit's clock is ahead by more than 10 min |
