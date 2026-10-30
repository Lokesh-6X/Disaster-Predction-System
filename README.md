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
| 3. Synthetic data + ML | ⏳ next |
| 4. Inference + alerts | — |
| 5. API + dashboard | — |
| 6. Real kit | — |

---

## Prerequisites (Windows)

| Tool | Version | Notes |
|---|---|---|
| Python | 3.13 | `py -3.13` must work |
| Node.js | 20+ | for the frontend (Phase 5) |
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

## Running

Use a separate PowerShell window for each:

```powershell
.\scripts\start_broker.ps1        # MQTT broker on localhost:1884
.\scripts\start_backend.ps1       # API on http://127.0.0.1:8000  (docs: /docs, health: /api/health)
.\scripts\start_simulator.ps1     # simulated kit01, one reading every 5 min
```

On first start the backend syncs kits from `site.yaml` and creates the admin user from `.env`. Logs go to the console and `logs\backend.log`.

### Kit simulator options

| Example | Effect |
|---|---|
| `start_simulator.ps1 --interval 10s` | Faster readings for testing |
| `start_simulator.ps1 --backfill-hours 48 --speed 600` | Fill the last 48 h quickly, then continue live |
| `start_simulator.ps1 --faults` | Occasional spikes and BME280 failures (tests QC and DHT11 fallback) |
| `start_simulator.ps1 --no-ts` | Omit timestamps (server uses arrival time) |
| `start_simulator.ps1 --drop-after 3` | Vanish after 3 readings — the broker's Last-Will marks the kit offline |
| `start_simulator.ps1 --count 10` | Stop cleanly after 10 readings |

Ctrl+C stops it cleanly (status `offline`).

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
| Reading rejected: timestamp in the future | The kit's clock is ahead by more than 10 min |
