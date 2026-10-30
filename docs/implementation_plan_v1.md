# Implementation Plan — Site Weather Hazard Prediction System (v1)

| | |
|---|---|
| **Version** | v1 (prototype) |
| **Status** | Draft — ready to start on "start building" |
| **Inputs** | [`analysis/analysis_v1.md`](analysis/analysis_v1.md) · [`requirements_v1.md`](requirements_v1.md) · [`design/system_design_v1.md`](design/system_design_v1.md) · [`frontend_pages.md`](frontend_pages.md) · `design/ui_reference_v1.html` (Claude Design, to be added) |
| **Last updated** | 2026-10-31 |

This plan turns the design into ordered, checkable tasks. Each phase ends with something that **runs** and a **checkpoint** where the admin/project owner reviews the result before the next phase starts.

Task size: **S** = a few hours · **M** = about a day · **L** = several days (rough guide only).

---

## 1. Overview

| Phase | Goal | Depends on | Size | Checkpoint result |
|---|---|---|---|---|
| 0 | Local environment ready | — | S | All tools installed and verified |
| 1 | Foundation | 0 | M | Config loads and validates; repo skeleton in place |
| 2 | Ingestion | 1 | L | Simulator data stored in PostgreSQL with QC flags; kit status works |
| 3 | Synthetic data + ML | 1 (2 for shared QC) | L | Synthetic dataset + 6 trained models registered as `v1` |
| 4 | Inference + alerts | 2, 3 | M | Hourly predictions stored; forced hazard → email in Mailpit |
| 5 | API + dashboard | 2, 4, UI reference | L | All 5 pages working live with the simulator |
| 6 | Real kit + hand-over | 5 | M | Real kit data → predictions → alerts end-to-end; README complete |

```
Phase 0 ─► Phase 1 ─┬─► Phase 2 ─┬─► Phase 4 ─► Phase 5 ─► Phase 6
                    └─► Phase 3 ─┘
```

Phase 3 can start once the shared `ml/core` QC/fusion code from Phase 2 exists (task 2.4).

---

## 2. Working conventions

- **Language/versions:** Python 3.11+, Node.js 20+, PostgreSQL 16, Mosquitto 2.x.
- **Python env:** one virtual environment at `.venv/` for backend + ML; dependencies in `requirements.txt` (pinned).
- **Frontend:** `frontend/` with its own `package.json`.
- **Style:** `ruff` for Python lint/format; Prettier for frontend.
- **Version control:** the folder is not yet a git repository — initialise git in Phase 1 (with the owner's go-ahead) and commit at the end of each task group.
- **Secrets:** only in `.env` (git-ignored); `.env.example` committed.
- **Tests:** written in the same phase as the code they cover; `pytest` must pass before a checkpoint.
- **Docs:** update `README.md` at every phase with how to run what was built.

---

## 3. Phase 0 — Local environment

| # | Task | Size | Done when |
|---|---|---|---|
| 0.1 | Install Python 3.11+ and verify `python --version` | S | Version printed |
| 0.2 | Install Node.js 20 LTS and verify `node -v`, `npm -v` | S | Versions printed |
| 0.3 | Install PostgreSQL 16 (Windows installer); create role `weather` and database `weather` | S | `psql -U weather -d weather -c "select 1"` works |
| 0.4 | Install Mosquitto 2.x. The Windows service on 1883 belongs to another project, so v2 runs its own broker on **1884** (`scripts/setup_broker.ps1`, `scripts/start_broker.ps1`) with logins and an ACL | S | Authenticated publish/subscribe works on 1884; anonymous and cross-kit publishing are refused |
| 0.5 | (Optional) Download Mailpit `.exe` | S | Mailpit UI opens at `localhost:8025` |
| 0.6 | Create Gmail app password for the admin's sending account | S | Credentials available for `.env` |

**Checkpoint 0:** all tools respond; owner confirms Gmail account to use.

---

## 4. Phase 1 — Foundation

| # | Task | Files | Size |
|---|---|---|---|
| 1.1 | Create repo skeleton per design §3 (empty packages, `__init__.py`) | `backend/`, `ml/`, `tools/`, `scripts/`, `tests/`, `frontend/` (placeholder) | S |
| 1.2 | `.gitignore`, git init, first commit | `.gitignore` | S |
| 1.3 | Python env + pinned dependencies | `requirements.txt`, `requirements-dev.txt` | S |
| 1.4 | `config/site.yaml` with all sections (design §4.1); IMD normals as placeholders marked `TODO-D8` | `config/site.yaml` | S |
| 1.5 | `config/synthetic.yaml` (design §4.2) | `config/synthetic.yaml` | S |
| 1.6 | `.env.example` (design §4.3) | `.env.example` | S |
| 1.7 | Settings loader: Pydantic models for both YAML files + `.env`; clear error messages | `backend/app/settings.py` | M |
| 1.8 | MQTT contract document (topics, payload table, examples, status/Last-Will, interval) | `docs/mqtt_contract.md` | S |
| 1.9 | Minimal FastAPI app with lifespan + `GET /api/health`; `backend/run.py` with Windows selector loop policy | `backend/app/main.py`, `backend/run.py` | S |
| 1.10 | Start scripts (backend only for now) | `scripts/start_backend.ps1` | S |
| 1.11 | README skeleton: prerequisites, setup, run backend | `README.md` | S |
| 1.12 | Tests: valid config loads; each invalid case gives a clear error | `tests/backend/test_settings.py` | S |

**Verify**
```powershell
pytest tests/backend/test_settings.py
.\scripts\start_backend.ps1      # then open http://localhost:8000/api/health and /docs
```

**Checkpoint 1:** owner reviews config files and MQTT contract.

---

## 5. Phase 2 — Ingestion

| # | Task | Files | Size |
|---|---|---|---|
| 2.1 | Database engine/session; ORM models for all tables (design §5.1) | `backend/app/db.py`, `backend/app/models.py` | M |
| 2.2 | Alembic setup + initial migration; `init_db.ps1` | `backend/alembic/`, `scripts/init_db.ps1` | S |
| 2.3 | Start-up sync: upsert `kits` from config; create admin user from `.env` if none | `backend/app/main.py`, `backend/app/security.py` (hashing only) | S |
| 2.4 | **Shared QC + fusion** (pure functions, design §6.3–6.4) | `ml/core/qc.py`, `ml/core/fusion.py` | M |
| 2.5 | Payload model + topic parsing | `backend/app/mqtt/payload.py` | S |
| 2.6 | Ingestion pipeline: timestamp rules → QC (history buffer) → fusion → insert (ON CONFLICT) → kit last_seen | `backend/app/ingest/pipeline.py` | M |
| 2.7 | MQTT subscriber task with reconnect/backoff | `backend/app/mqtt/subscriber.py` | M |
| 2.8 | Kit status: status-topic handler, watchdog task, status log | `backend/app/ingest/kit_status.py` | S |
| 2.9 | WebSocket hub (broadcast only; endpoint auth comes in Phase 5) | `backend/app/ws/hub.py` | S |
| 2.10 | Kit simulator (basic): live readings using a simple daily-cycle model; `--interval`, `--speed`, `--no-ts`, `--drop`; Last-Will | `tools/kit_simulator.py`, `scripts/start_simulator.ps1` | M |
| 2.11 | Logging setup (console + rotating file) | `backend/app/main.py` / `logging` config | S |
| 2.12 | Tests: QC rules (each flag), fusion cases, payload validation, timestamp rules, duplicate handling | `tests/ml/test_qc.py`, `tests/ml/test_fusion.py`, `tests/backend/test_ingest.py` | M |

**Verify**
```powershell
.\scripts\init_db.ps1
.\scripts\start_backend.ps1
.\scripts\start_simulator.ps1 -Interval 60s -Speed 1
psql -U weather -d weather -c "select ts, temp_c, hum_pct, qc_flags, fallback from readings order by ts desc limit 5"
```
Then: stop the simulator abruptly → kit becomes `offline` (Last-Will or watchdog within 10 min).

**Checkpoint 2:** readings arriving with correct values and flags; online/offline transitions logged.

---

## 6. Phase 3 — Synthetic data + ML

| # | Task | Files | Size |
|---|---|---|---|
| 3.1 | **Verify IMD normals and thresholds (D8)**; fill `normals` in `site.yaml` with source noted | `config/site.yaml` | S |
| 3.2 | Daily normals (periodic spline interpolation) | `ml/core/normals.py` | S |
| 3.3 | Synthetic generator — signal model: temperature, humidity (dew point), pressure, wind (design §7.2) | `ml/synthetic/generator.py` | L |
| 3.4 | Generator — events: heat spells, wind spells, pre-monsoon storms (design §7.3) | same | M |
| 3.5 | Generator — sensor layer (BME noise, DHT11 rounding/bias) and faults with fault log (design §7.4–7.5) | same | M |
| 3.6 | Hourly aggregation incl. ≤ 30 min interpolation | `ml/core/aggregate.py` | M |
| 3.7 | Labels: 6 cumulative labels (design §9.3) | `ml/core/labels.py` | S |
| 3.8 | Generator hazard-share calibration loop (3–5 %) + `.meta.json` | `ml/synthetic/generator.py` | S |
| 3.9 | Features (design §9.4) + saved `feature_list` | `ml/core/features.py` | M |
| 3.10 | Level selection + monotonic fix | `ml/core/levels.py` | S |
| 3.11 | Training (6 XGBoost models, random stratified 80/20) | `ml/train.py` | S |
| 3.12 | Evaluation (precision, recall, F1, PR-AUC, Brier, importances) | `ml/evaluate.py` | S |
| 3.13 | Registry: `v{N}/`, `metadata.json`, `active` pointer | `ml/registry.py` | S |
| 3.14 | CLI: `generate`, `build`, `train`, `evaluate`, `activate` | `ml/cli.py` | S |
| 3.15 | Upgrade simulator to use the generator's signal model and `--force wind:red` etc. | `tools/kit_simulator.py` | S |
| 3.16 | Tests: normals wrap-around, aggregation, label boundaries (29.9/30/60 km/h; 40 °C with 4.4/4.5/6.5; 45 °C), no future leakage in features, level selection, generator reproducibility, QC catches injected faults | `tests/ml/` | M |

**Verify**
```powershell
python -m ml.cli generate
python -m ml.cli build
python -m ml.cli train
python -m ml.cli evaluate
python -m ml.cli activate v1
pytest tests/ml
```
Check `ml/data/synthetic/karur_v1.parquet.meta.json` for hazard shares and `ml/models/v1/metadata.json` for metrics.

**Checkpoint 3:** owner reviews a few generated days (plots of a May heat spell, a July windy day, a storm) and the evaluation summary.

---

## 7. Phase 4 — Inference + alerts

| # | Task | Files | Size |
|---|---|---|---|
| 4.1 | Model store: load active version, check feature list | `backend/app/inference/model_store.py` | S |
| 4.2 | Inference runner: sufficiency → aggregate → features → 6 probabilities → monotonic → level → upsert predictions | `backend/app/inference/runner.py` | M |
| 4.3 | Hourly APScheduler job (minute 0, IST) | `backend/app/inference/scheduler.py` | S |
| 4.4 | Manual run trigger (temporary dev endpoint, protected in Phase 5) | `backend/app/api/predictions.py` | S |
| 4.5 | Emailer (aiosmtplib; Gmail STARTTLS or Mailpit) | `backend/app/alerts/emailer.py` | S |
| 4.6 | Email templates (HTML + text) | `backend/app/alerts/templates/` | S |
| 4.7 | Alert engine: trigger, cooldown, escalation, failed, disabled | `backend/app/alerts/engine.py` | M |
| 4.8 | Broadcast `prediction` and `alert` over the hub | runner/engine | S |
| 4.9 | Tests: sufficiency rule, runner with a stub model, cooldown/escalation/failed/disabled cases | `tests/backend/test_inference.py`, `tests/backend/test_alerts.py` | M |

**Verify**
```powershell
# Mailpit mode in .env (SMTP_HOST=localhost, SMTP_PORT=1025)
.\scripts\start_simulator.ps1 -Speed 60 -Force wind:red
# trigger a run
Invoke-RestMethod -Method Post http://localhost:8000/api/predictions/run
```
Expected: prediction rows for wind and heat; one `sent` alert email visible in Mailpit; a second run within 3 h → `cooldown`; stopping the simulator for > 1 h → `insufficient_data`.
Then switch `.env` to Gmail and confirm one real email arrives.

**Checkpoint 4:** owner receives a real alert email and reviews its content.

---

## 8. Phase 5 — API + dashboard

**Prerequisite:** `docs/design/ui_reference_v1.html` from Claude Design is in place.

### 5A — Backend API

| # | Task | Files | Size |
|---|---|---|---|
| 5.1 | JWT create/verify, auth dependency, login endpoint, login rate limit | `backend/app/security.py`, `backend/app/api/auth.py` | M |
| 5.2 | REST endpoints (requirements FR-API-01; design §13) | `backend/app/api/*.py`, `backend/app/schemas.py` | L |
| 5.3 | History: raw points ≤ 7 days, hourly aggregates beyond; CSV export streaming | `backend/app/api/readings.py` | M |
| 5.4 | WebSocket `/ws/live` with token check and ping | `backend/app/api/ws.py` | S |
| 5.5 | CORS, protect manual-run endpoint | `backend/app/main.py` | S |
| 5.6 | Tests: auth required, login success/failure, endpoint shapes, CSV headers | `tests/backend/test_api.py` | M |

### 5B — Frontend

| # | Task | Files | Size |
|---|---|---|---|
| 5.7 | Vite + React app, router, dev proxy, start script | `frontend/`, `scripts/start_frontend.ps1` | S |
| 5.8 | **Extract design tokens** (colours incl. hazard levels, fonts, spacing) from `ui_reference_v1.html` for light and dark | `src/styles/tokens.css`, `global.css` | M |
| 5.9 | Theme context + toggle (system/light/dark, persisted) | `src/context/ThemeContext.jsx`, `src/hooks/useTheme.js` | S |
| 5.10 | API client, auth context, protected routes, login page | `src/api/`, `src/context/AuthContext.jsx`, `src/pages/LoginPage.jsx` | M |
| 5.11 | Live data context: WebSocket + reconnect + polling fallback | `src/context/LiveDataContext.jsx`, `src/hooks/useLive.js` | M |
| 5.12 | Layout: top bar, nav, mobile menu | `src/components/layout/` | S |
| 5.13 | Dashboard: hazard cards, sensor cards, 24 h charts (BME + DHT lines, wind bands) | `src/pages/DashboardPage.jsx`, `src/components/hazard/`, `sensors/`, `charts/` | L |
| 5.14 | History page: range picker, charts, risk timeline, CSV download | `src/pages/HistoryPage.jsx` | M |
| 5.15 | Alerts page: table, filters, pagination, status badges | `src/pages/AlertsPage.jsx` | M |
| 5.16 | Kit & System page: kit info, 7-day strip, data quality, system health, settings | `src/pages/KitSystemPage.jsx` | M |
| 5.17 | Responsive pass (desktop / tablet / mobile) and light/dark pass on every page | all | M |
| 5.18 | Tests: utils (time IST, km/h, levels) with Vitest | `frontend/src/utils/*.test.js` | S |

**Verify**
```powershell
.\scripts\start_backend.ps1
.\scripts\start_frontend.ps1      # http://localhost:5173
.\scripts\start_simulator.ps1 -Speed 60
```
Walk through acceptance criteria 1–8 (requirements §19) in the browser, in both themes and at mobile width.

**Checkpoint 5:** owner reviews all pages against the Claude Design reference.

---

## 9. Phase 6 — Real kit + hand-over

| # | Task | Size |
|---|---|---|
| 6.1 | Confirm firmware facts (D4): wind value type, sending interval, `ts` present | S |
| 6.2 | Re-run `scripts/setup_broker.ps1 -Lan` so the broker listens on the network; open Windows firewall port 1884 | S |
| 6.3 | Point the kit at the broker; compare a few payloads with the MQTT contract | S |
| 6.4 | Update `site.yaml` with the real kit location, mounting height, notes | S |
| 6.5 | Run 24–48 h: check QC flag rates, fallback use, gaps, offline detection | M |
| 6.6 | Check predictions and alerts on real data; adjust QC limits if real data shows false flags | S |
| 6.7 | Auto-start: Mosquitto + PostgreSQL as services; backend auto-start on login (Task Scheduler) | S |
| 6.8 | Finalise README (full setup, running, troubleshooting) and update docs with any changes | M |
| 6.9 | Full acceptance run (requirements §19, criteria 1–9) | S |

**Checkpoint 6 (v1 done):** real kit data flowing end-to-end; all acceptance criteria met; data collection for the next version under way.

---

## 10. Requirement coverage

| Requirement area | Phase / tasks |
|---|---|
| FR-CFG | 1.4–1.7, 1.12 |
| FR-MQTT | 1.8, 2.5, 2.7, 6.3 |
| FR-ING, FR-QC | 2.4, 2.6–2.8, 2.12 |
| FR-DB | 2.1–2.3 |
| FR-SYN, FR-SIM | 2.10, 3.3–3.5, 3.8, 3.15 |
| FR-ML | 3.1–3.14, 3.16 |
| FR-INF | 4.1–4.4 |
| FR-ALT | 4.5–4.8 |
| FR-AUTH | 2.3, 5.1 |
| FR-API | 5.2–5.5 |
| FR-UI | 5.7–5.18 |
| NFR | 1.9–1.11, 2.11, 5.17, 6.7–6.8 |

---

## 11. Risks to the plan

| Risk | Effect | Response |
|---|---|---|
| Synthetic generator takes longer than expected (3.3–3.5) | Phase 3 slips | Build the signal model first, events next, faults last; train on a simpler dataset if needed |
| Windows install/service issues (Phase 0, 6.7) | Delays setup | README troubleshooting section; Mailpit fallback for email |
| UI reference not ready at Phase 5 | Frontend blocked | Do 5A (API) first; start 5B from `frontend_pages.md` and restyle when the HTML arrives |
| IMD normals not found quickly (3.1) | Generator inputs uncertain | Use Tiruchirappalli normals; mark as provisional in config |
| Real kit payload differs from contract (6.3) | Ingestion rejects data | Payload model accepts optional fields; adjust contract and mapping in one place |
| Gmail blocks SMTP | No real emails | Retry with app password settings; use Mailpit for demo; record `failed` status |

---

## 12. Open items before or during the build

| Item | Needed by |
|---|---|
| D3 — tools installed on the PC (Python, Node.js, PostgreSQL, Mosquitto) | Phase 0 |
| Gmail sending account + app password | Phase 4 |
| D8 — verified IMD normals and thresholds | Phase 3 (task 3.1) |
| `docs/design/ui_reference_v1.html` | Phase 5B |
| D4 — firmware details | Phase 6 |
