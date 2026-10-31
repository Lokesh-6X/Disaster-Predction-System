# MQTT Contract — Kit → Server (v1)

| | |
|---|---|
| **Version** | 1.0 |
| **Requirements** | FR-MQTT-01..03 ([`requirements_v1.md`](requirements_v1.md)) |
| **Broker** | This project's Mosquitto, port **1884**, login required |
| **Last updated** | 2026-10-31 |

This is the agreement between the kit firmware (and the kit simulator) and the backend. Any kit that follows it works without backend changes.

---

## 1. Connection

| Setting | Value |
|---|---|
| Host | IP address of the PC running the broker (`localhost` for the simulator) |
| Port | `1884` |
| Username | the kit's `kit_id` (e.g. `kit01`) |
| Password | `MQTT_KIT_PASSWORD` from `.env` |
| Client ID | the kit's `kit_id` (must be unique per connection) |
| Keep-alive | 60 s (recommended) |
| Clean session | `true` |

The broker only lets a kit publish under its own `kit_id` (see `config/mosquitto/acl`).

---

## 2. Topics

| Topic | Direction | QoS | Retained | Payload |
|---|---|---|---|---|
| `weather/kit/{kit_id}/telemetry` | kit → server | 1 | no | JSON reading (section 3) |
| `weather/kit/{kit_id}/status` | kit → server | 1 | **yes** | `online` or `offline` (plain text) |

`{kit_id}` must match a kit in `config/site.yaml`: letters, digits, `_` or `-`, at most 32 characters.

The backend subscribes to `weather/kit/+/telemetry` and `weather/kit/+/status`.

---

## 3. Telemetry payload

UTF-8 JSON object, one reading per message.

| Field | Type | Unit | Required | Notes |
|---|---|---|---|---|
| `ts` | string | ISO 8601, UTC | no | e.g. `"2026-10-31T09:05:00Z"`. If missing, the server uses the arrival time and flags the reading `ts_missing`. Readings more than 10 min in the future are rejected. |
| `temp_bme_c` | number \| null | °C | yes* | BME280 temperature |
| `hum_bme_pct` | number \| null | % RH | yes* | BME280 humidity |
| `pressure_hpa` | number \| null | hPa | yes* | BME280 station pressure (not sea-level) |
| `temp_dht_c` | number \| null | °C | yes* | DHT11 temperature |
| `hum_dht_pct` | number \| null | % RH | yes* | DHT11 humidity |
| `wind_speed_ms` | number \| null | m/s | yes* | Wind speed as reported by the kit |
| `wind_gust_ms` | number \| null | m/s | no | Reserved for future firmware; omit or `null` |
| `rain_mm` | number \| null | mm | no | `null` until the rain gauge is fitted |
| `fw_version` | string | — | no | Firmware version, e.g. `"1.2.0"` |

\* The key should be present; send `null` when that sensor failed to read. The reading is still stored and flagged.

Unknown extra fields are ignored. `kit_id` is taken from the topic, not the payload.

### Example

```json
{
  "ts": "2026-10-31T09:05:00Z",
  "temp_bme_c": 36.42,
  "hum_bme_pct": 41.8,
  "pressure_hpa": 1004.21,
  "temp_dht_c": 37,
  "hum_dht_pct": 45,
  "wind_speed_ms": 6.7,
  "wind_gust_ms": null,
  "rain_mm": null,
  "fw_version": "1.2.0"
}
```

### Example — BME280 failed, no timestamp

```json
{
  "temp_bme_c": null,
  "hum_bme_pct": null,
  "pressure_hpa": null,
  "temp_dht_c": 35,
  "hum_dht_pct": 48,
  "wind_speed_ms": 3.1
}
```

---

## 4. Sending interval

Any interval from **1 to 5 minutes** is accepted without configuration changes. The kit should keep the interval steady; the server calculates data coverage from the readings it receives.

### Current kit firmware (`kit01`, confirmed 2026-10-31 — decision D4)

| Fact | Value | Effect on the server |
|---|---|---|
| Sending interval | every **3 minutes** | Every 5-min slot gets at least one reading; the Kits page expects 480 readings per 24 h |
| `wind_speed_ms` | **1-minute average**, taken once per reading | "Peak wind" is the highest 1-min average among the readings, so short gusts are smoothed out and wind levels are reached less often than with true gusts |
| `ts` | **not sent** (no NTP clock on the kit) | Arrival time is used; every reading is flagged `ts_missing` — expected, not an error |
| Offline buffering | **none** — readings taken while offline are lost | Arrival time is always close to measurement time; outages show as gaps |

---

## 5. Status and Last-Will

1. When connecting, the kit registers a **Last-Will**: topic `weather/kit/{kit_id}/status`, payload `offline`, QoS 1, retained.
2. Right after connecting, the kit publishes `online` to the same topic (QoS 1, retained).
3. On a clean shutdown the kit publishes `offline` before disconnecting.
4. If the kit loses power or network, the broker publishes the Last-Will `offline` after the keep-alive expires.

The server also marks a kit **offline** if no telemetry arrives for 10 minutes (`kit_status.offline_after_min`), even without a Last-Will.

---

## 6. Server-side handling (summary)

| Situation | Result |
|---|---|
| Invalid JSON / wrong types | Rejected and logged; not stored |
| Unknown or disabled `kit_id` | Logged and ignored |
| `ts` > 10 min in the future | Rejected and logged |
| `ts` missing | Stored with arrival time, flag `ts_missing` |
| Duplicate (`kit_id`, `ts`) | Ignored |
| Value out of range, spike, stuck | Stored with a QC flag |
| BME280 value unusable | DHT11 value used, reading marked `fallback` |

---

## 7. Changing the contract

Additions of **optional** fields are backwards compatible. Renaming or removing fields, or changing units or topics, requires a new contract version and coordinated firmware and backend changes.
