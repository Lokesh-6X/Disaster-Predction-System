# Frontend Pages — Site Weather Hazard Prediction System (v1)

Wireframes and page descriptions for the admin dashboard. Layout only; colours and styling are decided at build time.

## Scope (v1)

- One site (Karur, inland), one kit (`kit01`).
- Hazards: **Wind** and **Heat** (rain is a future version).
- One admin user (JWT login).
- Light and dark mode (follows system setting, toggle in the top bar, choice remembered).
- Responsive layout (desktop and mobile).
- Live updates via WebSocket `/ws/live`.

### Risk levels (IMD standard bands)

| Level  | Wind (peak reported wind speed, next 3 h) | Heat (max temp next 3 h vs normal daily max) |
|--------|-------------------------------------------|----------------------------------------------|
| Green  | < 30 km/h                                 | Below heat-wave criteria                     |
| Yellow | ≥ 30 km/h                                 | ≥ 40 °C and +4.5 to +6.4 °C above normal     |
| Orange | ≥ 40 km/h                                 | ≥ 40 °C and ≥ +6.5 °C above normal           |
| Red    | ≥ 60 km/h                                 | ≥ 45 °C                                      |

The badge shows the highest level whose predicted probability is **≥ 50%**.

---

## Page list

1. Login
2. Live Dashboard (home)
3. History
4. Alerts
5. Kit & System

---

## 1. Login

- Username + password → JWT session.
- Auto-logout when the session expires.
- Theme toggle available before login.

```
┌──────────────────────────────────────────────┐
│                                   [☀/🌙]      │
│                                              │
│          ⛅ Site Weather Hazard System        │
│                 Karur Campus                 │
│                                              │
│        ┌──────────────────────────────┐      │
│        │ Username                     │      │
│        └──────────────────────────────┘      │
│        ┌──────────────────────────────┐      │
│        │ Password                 👁   │      │
│        └──────────────────────────────┘      │
│        [          Sign in             ]      │
│                                              │
│        ⚠ Invalid username or password        │
└──────────────────────────────────────────────┘
```

---

## Shared top bar (all pages after login)

- Site name, navigation, kit online/offline status with last-seen time, current time (IST), theme toggle, logout.
- On mobile the navigation collapses into a ☰ menu.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ ⛅ Karur Campus │ Dashboard  History  Alerts  Kit & System │                        │
│                 🟢 kit01 online · 2 min ago │ 14:32 IST │ [☀/🌙] [Logout]          │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Live Dashboard (home)

### Sections

**Hazard risk cards (Wind, Heat)**
- Risk badge (Green / Yellow / Orange / Red) with label.
- Probability for each level.
- "Valid until" time (prediction time + 3 h) and model version.
- Heat card shows the normal daily max for today for context.
- 🔁 marker when the DHT11 fallback sensor was used for the prediction.
- If data was insufficient: "⚪ Insufficient data — no prediction this hour."

**Live sensor cards**
- Temperature, Humidity, Pressure, Wind speed.
- Current value, trend arrow (↑ ↓), time of reading.
- Temperature and humidity also show the DHT11 value.
- QC-flagged values greyed out with ⚠ (hover shows the reason).

**Live charts (last 24 h, updated via WebSocket)**
- Temperature — BME280 and DHT11 lines.
- Humidity — BME280 and DHT11 lines.
- Pressure.
- Wind speed — with 30 / 40 / 60 km/h band lines.
- Legend items can be clicked to hide/show a line.

```
┌──────────────────────────── HAZARD RISK (next 3 h) ────────────────────────────┐
│ ┌─────────────── 💨 WIND ───────────────┐ ┌─────────────── 🌡 HEAT ─────────────┐ │
│ │  ██ YELLOW · Gusty wind               │ │  ██ GREEN · Normal                 │ │
│ │  ≥30 km/h   ███████░░░  72%           │ │  Heat wave    ██░░░░░░░░  18%      │ │
│ │  ≥40 km/h   ████░░░░░░  41%           │ │  Severe       █░░░░░░░░░   6%      │ │
│ │  ≥60 km/h   █░░░░░░░░░   4%           │ │  Extreme      ░░░░░░░░░░   0%      │ │
│ │  Valid until 17:00 · model v1.0       │ │  Normal max today: 37.2 °C         │ │
│ │                                       │ │  Valid until 17:00 · model v1.0    │ │
│ └───────────────────────────────────────┘ └────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────── LIVE READINGS ─────────────────────────────────────┐
│ ┌ Temperature ─┐ ┌ Humidity ───┐ ┌ Pressure ───┐ ┌ Wind speed ─┐                │
│ │ 36.4 °C  ↑   │ │ 42 %    ↓   │ │ 1004.2 hPa ↓│ │ 24 km/h  ↑  │                │
│ │ DHT11: 37 °C │ │ DHT11: 45 % │ │             │ │             │                │
│ │ 14:31        │ │ 14:31       │ │ 14:31       │ │ 14:31 ⚠     │                │
│ └──────────────┘ └─────────────┘ └─────────────┘ └─────────────┘                │
│  ⚠ = QC flag (hover for reason)    🔁 = fallback sensor (DHT11) in use           │
└────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────── LAST 24 HOURS (live) ──────────────────────────────┐
│ Temperature (°C)  ── BME280 ── DHT11     Humidity (%)  ── BME280 ── DHT11       │
│  40┤        ╭─╮                            80┤╮                                 │
│  30┤   ╭───╯  ╰──╮                         50┤ ╰──╮      ╭─                     │
│  20┤──╯          ╰──                       20┤     ╰────╯                       │
│                                                                                │
│ Pressure (hPa)                           Wind speed (km/h)                      │
│ 1008┤──╮    ╭──                           60┤- - - - - - - - - - Red            │
│ 1004┤   ╰──╯                              40┤- - - - - - - - - - Orange         │
│ 1000┤                                     30┤- - - - ╭╮ - - - - - Yellow        │
│                                            0┤───────╯  ╰──                      │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. History

- Date range presets (24 h, 7 days, 30 days) and custom range.
- Choose which charts to show.
- Same charts as the dashboard (BME280 and DHT11 lines), from stored data.
- Predicted risk timeline: one coloured cell per hour for each hazard.
- **Download CSV** of readings (with QC flags) and predictions for the selected range.

```
┌──────────────────────────────── HISTORY ───────────────────────────────────────┐
│ Range: [Last 24h] [7 days] [30 days] [Custom: 01-10-2026 → 31-10-2026]          │
│ Show:  ☑ Temperature ☑ Humidity ☑ Pressure ☑ Wind ☑ Predicted risk             │
│                                                          [⬇ Download CSV]       │
├────────────────────────────────────────────────────────────────────────────────┤
│ Temperature  ── BME280 ── DHT11                                                 │
│ Humidity     ── BME280 ── DHT11                                                 │
│ Pressure                                                                        │
│ Wind speed   (band lines 30 / 40 / 60 km/h)                                     │
├────────────────────────────────────────────────────────────────────────────────┤
│ Predicted risk timeline (colour per hour)                                       │
│ Wind  ▒▒▒▒▒▒▒▒██▓▓▒▒▒▒▒▒▒▒▒▒▓▓▓▒▒▒▒                                             │
│ Heat  ▒▒▒▒▒▒▒▒▒▒▒▒▓▓▓▓▒▒▒▒▒▒▒▒▒▒▒▒▒                                             │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Alerts

- Table of all alerts (Orange and Red), newest first.
- Columns: time, hazard, level, probability, valid until, email status.
- Email status: ✅ Sent · ⏸ Cooldown (not re-sent) · ❌ Failed.
- Filters: hazard, level, date range. Pagination.

```
┌──────────────────────────────── ALERTS ────────────────────────────────────────┐
│ Filter: Hazard [All ▾]   Level [All ▾]   Date [Last 30 days ▾]                  │
├──────────────┬────────┬───────────┬──────────────┬───────────┬─────────────────┤
│ Time (IST)   │ Hazard │ Level     │ Probability  │ Valid to  │ Email           │
├──────────────┼────────┼───────────┼──────────────┼───────────┼─────────────────┤
│ 31-10 14:00  │ Wind   │ 🟠 Orange │ 58% ≥40 km/h │ 17:00     │ ✅ Sent         │
│ 31-10 13:00  │ Wind   │ 🟠 Orange │ 52% ≥40 km/h │ 16:00     │ ⏸ Cooldown     │
│ 28-10 15:00  │ Heat   │ 🔴 Red    │ 61% Extreme  │ 18:00     │ ✅ Sent         │
│ 28-10 12:00  │ Heat   │ 🟠 Orange │ 55% Severe   │ 15:00     │ ❌ Failed       │
├──────────────┴────────┴───────────┴──────────────┴───────────┴─────────────────┤
│                                         ◀ Prev   Page 1 of 4   Next ▶           │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Kit & System

- **Kit:** ID, status, last seen, firmware version, location, elevation, sensors fitted, 7-day online/offline strip.
- **Data quality (last 24 h):** readings received vs expected, gaps, QC flag counts, DHT11 fallback time.
- **System:** last/next prediction run, model version, MQTT / database / email health.
- **Active settings (read-only):** thresholds, show-level cut-off, alert levels, cooldown.

```
┌──────────────────────────────── KIT ───────────────────────────────────────────┐
│ kit01 · 🟢 Online · last seen 14:31 IST · firmware 1.2.0                         │
│ Location: Block A rooftop · lat 10.96, lon 78.08 · elevation 120 m               │
│ Sensors: BME280 ✅ · DHT11 ✅ · Anemometer ✅ · Rain gauge — not fitted           │
│ Online/offline (last 7 days): ██████████▁██████████████████                      │
├──────────────────────────────── DATA QUALITY (last 24 h) ──────────────────────┤
│ Readings received: 286 / 288    Gaps: 1 (10 min)                                 │
│ QC flags: spike 2 · stuck 0 · out-of-range 0 · BME/DHT mismatch 1                │
│ Fallback (DHT11) used: 0 min                                                     │
├──────────────────────────────── SYSTEM ────────────────────────────────────────┤
│ Last prediction run: 14:00 ✅ · Next: 15:00 · Models: v1.0 (synthetic)           │
│ MQTT broker: ✅ connected · Database: ✅ · Email: ✅ last sent 14:00              │
├──────────────────────────────── ACTIVE SETTINGS (read-only) ───────────────────┤
│ Wind bands: 30 / 40 / 60 km/h · Heat: ≥40 °C, +4.5 / +6.5 °C, ≥45 °C            │
│ Show-level cut-off: 50% · Alert levels: Orange, Red · Cooldown: 3 h              │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## Open questions

1. Add, remove or move anything on these pages?
2. Show extra derived values such as dew point or "feels like" temperature?
3. Alerts table: keep cooldown/failed entries, or show only sent alerts?
