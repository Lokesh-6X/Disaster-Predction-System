# System Analysis — Site Weather Hazard Prediction System (v1)

| | |
|---|---|
| **Version** | v1 (prototype) |
| **Status** | Draft — based on the planning discussion |
| **Site** | Karur, Tamil Nadu (inland) |
| **Related** | [`requirements_v1.md`](../requirements_v1.md) · [`design/system_design_v1.md`](../design/system_design_v1.md) · [`frontend_pages.md`](../frontend_pages.md) |
| **Last updated** | 2026-10-31 |

This document analyses the problem, the users, the data and the risks, and records the reasoning behind the v1 decisions. The requirements document states **what** is built and the design document **how**; this document explains **why**.

---

## 1. Problem statement

Campuses and tech parks in India are exposed to local weather hazards — extreme afternoon heat and strong, damaging winds — that affect people working outdoors, events, rooftop equipment and buildings. Public forecasts from IMD are issued for districts, not for a specific site, and are not tied to what is actually happening on the campus at that moment.

A site that installs its own weather-sensing kit can:
- see live conditions at the exact location, and
- get early, site-specific warnings for the next few hours.

**Goal:** build a system that collects readings from an on-site kit, predicts heat and high-wind hazards for the next 3 hours with machine-learning models, and warns the site administrator through a dashboard and email.

---

## 2. Existing situation and its limitations

| Current option | Limitation |
|---|---|
| IMD district forecasts and warnings | Coarse (district level); not specific to the campus; issued a few times a day |
| Weather apps | Based on model grids (tens of km); no local sensor; no site-specific alerts |
| Manual observation | No early warning; depends on someone noticing |
| Stand-alone weather station display | Shows current values only; no prediction or alerts |

**Gap:** no low-cost system that combines a site's own live measurements with automatic short-term hazard prediction and alerts.

---

## 3. Stakeholders and users

| Stakeholder | Interest | v1 role |
|---|---|---|
| Site administrator | Knows conditions and risks; acts on alerts | **Only user** (dashboard + email) |
| Campus occupants (staff, students) | Safety | Indirect — admin passes on warnings |
| Facilities / maintenance team | Protect rooftop equipment, plan outdoor work | Future users |
| Project team | Build, evaluate, extend the system | Developers |
| Project guide / evaluators | Assess the work | Reviewers |

v1 has **one admin user**. Multiple users and roles are planned later.

---

## 4. Scope analysis

### 4.1 Hazards considered

| Hazard | Included in v1 | Reason |
|---|---|---|
| Heat (IMD heat-wave criteria) | ✅ | Measured directly by the kit; builds gradually, so short-term prediction from local data is realistic |
| High wind (local strong winds) | ✅ | Measured by the anemometer; Karur's main wind hazard (monsoon westerlies) builds gradually |
| Heavy rainfall | ❌ (later) | Rain gauge not fitted yet; rain is the hazard a single kit predicts worst |
| Cyclones | ❌ | Large-scale systems; out of scope for a site kit |

### 4.2 Prediction horizon
3 hours ahead, updated every hour. Long enough to act (move an event indoors, secure rooftop items), short enough for local measurements to carry useful signal.

---

## 5. Site analysis — Karur

Approximate values; exact normals to be verified from IMD sources (open decision D8).

| Property | Value |
|---|---|
| Location | ≈ 10.96° N, 78.08° E |
| Elevation | ≈ 120 m |
| Setting | Inland (≈ 150+ km from the coast) → heat threshold 40 °C |
| Timezone | Asia/Kolkata (IST) |

### 5.1 Seasonal hazard profile

| Season | Months | Conditions | Hazard relevance |
|---|---|---|---|
| Summer / pre-monsoon | Mar–May | Hot and dry, afternoons ~37–40 °C, occasional thunderstorms | **Heat** peak; some storm gusts |
| Southwest monsoon | Jun–Sep | Little rain (rain-shadow side), **strong steady westerly winds** | **Wind** season |
| Northeast monsoon | Oct–Dec | Main rain season, cloudy, humid | Low (rain out of scope) |
| Winter | Jan–Feb | Pleasant, light winds | Low |

### 5.2 Implications
- **Wind:** the dominant hazard is steady monsoon wind, which builds over hours — a good fit for a single-kit, 3-hour prediction. Sudden storm gusts (Apr–May) are rarer and harder to predict.
- **Heat:** heat-wave conditions are possible but not frequent, concentrated in April–May afternoons. Red (≥ 45 °C) is expected to be very rare.

---

## 6. Hardware and data analysis

### 6.1 Kit sensors

| Sensor | Measures | Accuracy (typical) | Role |
|---|---|---|---|
| BME280 | Temperature, humidity, pressure | ±1 °C, ±3 % RH, ±1 hPa; fine resolution | **Primary** |
| DHT11 | Temperature, humidity | ±2 °C, ±5 % RH; 1 °C / 1 % resolution | **Fallback only** |
| Anemometer | Wind speed | Depends on model and mounting | Wind hazard |
| Rain gauge (DFRobot SEN0575) | Rainfall | — | Not fitted (future) |

Board: ESP32-class, sending JSON over MQTT every 1–5 minutes. **Firmware is fixed in v1** (no gust measurement, no guaranteed time sync).

### 6.2 Data characteristics
- Volume: ~105,000 readings per year at 5-minute intervals (one kit) — small.
- Expected data problems: sensor spikes, stuck values, missing readings, kit offline periods, DHT11/BME280 disagreement, missing or drifting timestamps.
- Consequence: a **quality-control (QC)** stage is required before data is stored or used for prediction.

### 6.3 Training data availability
No historical data exists from the kit before installation. Options analysed:

| Source | Pros | Cons | Decision |
|---|---|---|---|
| ERA5 reanalysis (Open-Meteo) | 20–30 years, free | ~28 km grid, smooths extremes, differs from a rooftop sensor | Not used in v1 |
| Airport METAR reports | Real observations, half-hourly | Depends on a nearby airport; gaps | Not used |
| External forecasts (NWP) as inputs | Big accuracy gain | Needs internet; not "ML-only" | Not used |
| **Synthetic dataset** in the kit's format | Same format as live data; controllable; tests the full pipeline | Model learns the generator's rules, not real weather | **Used in v1** |
| Kit's own data after installation | Exactly the site and sensor | Needs months/years to cover seasons | **Next version** |

---

## 7. Feasibility study

### 7.1 Technical feasibility
| Aspect | Assessment |
|---|---|
| Hardware | Kit already exists; ESP32 + MQTT is a proven combination |
| Software stack | FastAPI, PostgreSQL, Mosquitto, React, XGBoost — mature, free, well documented, run on Windows |
| ML | Six small binary classifiers on hourly features; trains in seconds to minutes on a laptop |
| Real-time needs | One reading every 1–5 min and one prediction run per hour — very light load |
| **Verdict** | **Feasible** |

### 7.2 Operational feasibility
| Aspect | Assessment |
|---|---|
| Users | One admin; simple web dashboard + email |
| Running | Local PC with start scripts; no cloud or Docker knowledge needed |
| Maintenance | Config-file driven; thresholds and site changed without code |
| **Verdict** | **Feasible**, provided the PC stays on and connected to the kit's network |

### 7.3 Economic feasibility
| Item | Cost |
|---|---|
| Kit | Already available |
| Software | All open source / free |
| Email | Gmail SMTP (free) |
| Hosting | Local PC (existing) |
| Radiation shield (handled in hardware) | Low (~₹500–1500) |
| **Verdict** | **Very low cost** |

### 7.4 Schedule feasibility
Six build phases, each producing a runnable result (see requirements §18). v1 avoids high-effort items (data downloads, model tuning, Docker, multi-user) to keep the schedule realistic.

---

## 8. Critical review and decisions

The original plan was reviewed for weak spots. Each problem, the options considered and the decision taken:

### Problem 1 — Can one kit predict 3 hours ahead?
- **Issue:** weather often arrives from outside the site; a single point sensor has limited warning, especially for thunderstorm rain and gusts.
- **Options:** kit-only; kit + external forecasts (hybrid); shorter horizon.
- **Decision:** kit + ML model only; **rain removed from v1**; heat and wind kept with a 3 h horizon.
- **Why acceptable:** heat builds predictably; Karur's main wind hazard (monsoon westerlies) builds gradually.

### Problem 1a — Training data
- **Issue:** no historical kit data; minute-level historical data does not exist for the site.
- **Decision:** v1 trains on a **synthetic dataset** that mimics the kit's real-time data exactly (format, interval, Karur climate tuned with IMD normals, hazard events, sensor faults). Features are **hourly** in v1; minute-level features later.
- **Accepted consequence:** v1 predictions may be inaccurate; the next version retrains on real kit data.

### Problem 2 — Synthetic data vs. the real kit
- **Issue:** distribution shift — the real kit's levels and patterns will differ from synthetic data.
- **Decision:** accepted for v1. Mitigations: IMD normals in the generator; store all real data, QC flags and predictions (with model version) permanently for next-version training.

### Problem 3 — Labels and levels
- **Issue:** the original plan had two conflicting colour systems (intensity bands and probability bands).
- **Decision:** **IMD standard intensity bands**; one binary model per level (3 levels × 2 hazards = 6 models); the badge shows the highest level with probability ≥ 50 %.
- **Class imbalance:** no special handling in v1 (no class weighting, random split, no baseline). Reported scores are therefore optimistic and refer to synthetic data only.
- **Model choice:** **XGBoost only**, default settings. Comparing Logistic Regression / Random Forest, Optuna tuning and probability calibration (in the original plan) are left out of v1. XGBoost suits hourly tabular features, handles missing values natively, trains quickly and gives feature importance.

### Problem 4 — Daily heat-wave criteria vs. hourly prediction
- **Issue:** IMD heat-wave criteria use the daily maximum vs. the normal daily maximum.
- **Decision:** label = max temperature in the next 3 h vs. the **normal daily max** for that date (IMD monthly normals interpolated to daily).

### Problem 5 — DHT11 accuracy and mounting
- **Issue:** DHT11 is much less accurate than BME280; sun exposure can add 5–10 °C.
- **Decision:** BME280 primary; DHT11 **fallback only**, large disagreement flagged; fallback shown on the dashboard. Mounting and radiation shielding **handled in hardware**.

### Problem 6 — Smaller gaps
| Item | Decision |
|---|---|
| Gust measurement (firmware cannot change) | Wind label = **peak reported wind speed** in the next 3 h; `wind_gust_ms` kept optional for future firmware |
| Data gaps | Interpolate ≤ 30 min; skip prediction if > 25 % of last 24 h missing or no data in last hour |
| Clock sync | Reject readings > 10 min in the future; missing `ts` → arrival time, flagged |
| Baselines | Not in v1 |

### Other decisions
| Topic | Decision |
|---|---|
| Site identity | No `site_id` (one site per deployment); `kit_id` kept for future multi-kit |
| MQTT topics | `weather/kit/{kit_id}/telemetry`, `.../status` with Last-Will |
| Config | `config/site.yaml` + `config/synthetic.yaml`; secrets in `.env`; thresholds file-only |
| Alerts | Email to the admin for Orange/Red; 3 h cooldown; escalation sends immediately |
| Users | One admin (JWT); more users later |
| Deployment | Local Windows PC, no Docker; PostgreSQL; Gmail SMTP + optional Mailpit |
| Dashboard | 5 pages, light/dark mode, responsive; charts show BME280 and DHT11; design from Claude Design (`docs/design/ui_reference_v1.html`) |

---

## 9. Functional analysis

### 9.1 Use cases

| ID | Actor | Use case | Outcome |
|---|---|---|---|
| UC-01 | Kit | Send reading | Reading validated, QC-checked, stored, shown live |
| UC-02 | Kit | Report status / disconnect | Kit shown online/offline |
| UC-03 | Scheduler | Run hourly prediction | Heat and wind levels stored and shown |
| UC-04 | System | Raise alert | Orange/Red → email to admin (with cooldown) |
| UC-05 | Admin | Log in / log out | Access to dashboard |
| UC-06 | Admin | View live dashboard | Current readings, hazard levels, 24 h charts |
| UC-07 | Admin | View history and export CSV | Charts for a date range; CSV file |
| UC-08 | Admin | View alerts | Alert list with email status |
| UC-09 | Admin | View kit and system health | Kit status, data quality, system status, settings |
| UC-10 | Developer | Generate data and train models | New model version registered |

```
                 ┌────────────────────────────────────────────┐
                 │   Site Weather Hazard Prediction System    │
   ┌──────┐      │                                            │
   │ Kit  │──────┼──► (UC-01 Send reading)                    │
   └──────┘──────┼──► (UC-02 Report status)                   │
                 │                                            │
 ┌───────────┐   │                                            │
 │ Scheduler │───┼──► (UC-03 Run prediction) ──► (UC-04 Raise alert) ──┼──► Email
 └───────────┘   │                                            │
   ┌───────┐     │                                            │
   │ Admin │─────┼──► (UC-05 Log in)                          │
   │       │─────┼──► (UC-06 Live dashboard)                  │
   │       │─────┼──► (UC-07 History / CSV)                   │
   │       │─────┼──► (UC-08 Alerts)                          │
   │       │─────┼──► (UC-09 Kit & system)                    │
   └───────┘     │                                            │
 ┌───────────┐   │                                            │
 │ Developer │───┼──► (UC-10 Generate data & train)           │
 └───────────┘   └────────────────────────────────────────────┘
```

### 9.2 Data flow — context (level 0)

```
            readings, status                          dashboard pages, live updates
  ┌─────┐ ─────────────────────►  ┌──────────────┐  ─────────────────────────────►  ┌───────┐
  │ Kit │                         │   Hazard     │                                  │ Admin │
  └─────┘                         │  Prediction  │  ◄─────────────────────────────  └───────┘
                                  │   System     │      login, queries                  ▲
                                  └──────┬───────┘                                      │
                                         │ alert emails                                 │
                                         └──────────────────────────────────────────────┘
```

### 9.3 Data flow — level 1

```
 Kit ──► [1 Ingest & QC] ──► (D1 Readings) ──► [3 Predict] ──► (D2 Predictions) ──► [4 Alert] ──► (D3 Alerts)
              │                    ▲                ▲                 │                  │
              ▼                    │                │                 │                  ▼
        (D4 Kits/status)           │          (D5 Models)            │               Email ──► Admin
                                   │                ▲                 │
                                   │                │                 ▼
                                   │      [2 Train (offline)]    [5 Serve dashboard] ◄──► Admin
                                   │                ▲                 ▲
                                   │                │                 │
                             (synthetic data) ──────┘     D1, D2, D3, D4
```

---

## 10. Non-functional analysis

| Quality | Need | Approach |
|---|---|---|
| Timeliness | Live values within seconds | WebSocket push (target ≤ 5 s) |
| Reliability | Survive broker/DB restarts, kit outages | Auto-reconnect; offline detection; insufficient-data handling |
| Data integrity | Keep everything for future training | Store raw + fused values and QC flags; no deletion |
| Security | Admin-only access | JWT login, hashed password, secrets in `.env` |
| Usability | Clear at a glance, day or night, on a phone | Colour + text levels, light/dark mode, responsive layout |
| Maintainability | Change site/thresholds without code | YAML config; shared ML core code; documented modules |
| Extensibility | More kits, rain, users, real-data models | `kit_id` everywhere; rain fields reserved; users table; model registry |

---

## 11. Risk analysis

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | v1 predictions inaccurate on real data (synthetic training) | High | Medium | Accepted for v1; store real data; retrain in next version |
| R2 | Peak reported wind speed is lower than true gusts → wind levels under-triggered | Medium | Medium | Thresholds configurable; review band frequencies with real data |
| R3 | Sensor exposure (sun, enclosure) causes false heat alerts | Medium | High | Handled in hardware (radiation shield); QC; DHT cross-check |
| R4 | Kit clock drift / missing timestamps | Medium | Low | Arrival-time fallback; future-time rejection; flags |
| R5 | Kit offline or network loss | Medium | Medium | Offline detection; insufficient-data rule; no false alerts |
| R6 | Too many / too few alerts | Medium | Medium | Cooldown + escalation rule; thresholds and cut-off configurable; `alerts.enabled` switch |
| R7 | Gmail SMTP blocks or fails | Low | Medium | App password; failures logged and retried next hour; dashboard still shows alerts |
| R8 | Local PC turned off / sleeps | Medium | High | Document "keep PC on"; services auto-start; future server deployment |
| R9 | Windows-specific issues (event loop, service setup) | Medium | Low | Known fix in `backend/run.py`; step-by-step README |
| R10 | IMD normals or thresholds entered wrongly | Low | Medium | Verify from IMD sources before training (D8); values in config |
| R11 | Model scores misread as real accuracy (random split, synthetic data) | Medium | Medium | Clear note in evaluation metadata and report |

---

## 12. Assumptions and constraints

### Assumptions
- The kit can reach the PC's MQTT broker over the local network.
- The kit sends readings every 1–5 minutes in the agreed JSON format.
- The PC running the system stays on and has internet access for email.
- IMD monthly normals for Karur / Tiruchirappalli represent the site's climate well enough for the generator.
- Mounting and radiation shielding are done correctly in hardware.

### Constraints
- Firmware cannot be changed in v1.
- One site, one kit, one admin.
- No external weather data as model inputs.
- No Docker; runs locally on Windows.
- Rain gauge not fitted.

---

## 13. Known limitations of v1

1. Models are trained on synthetic data; real-world accuracy is unknown until the next version.
2. No true gust measurement; wind levels are based on peak reported wind speed.
3. Sudden thunderstorm gusts have little warning from a single kit.
4. No rainfall prediction.
5. Evaluation uses a random split without class weighting or baselines, so scores are optimistic.
6. Single admin; thresholds changed only by editing config.

---

## 14. Roadmap beyond v1

| Version | Planned additions |
|---|---|
| Next version | Retrain/fine-tune on real kit data; time-based evaluation; multiple kits per site |
| Later | Rain gauge and heavy-rain prediction; minute-level features; firmware gust measurement; multiple users and roles; threshold editing from the dashboard; server deployment |
