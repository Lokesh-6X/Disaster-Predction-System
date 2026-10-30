import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, query } from '../api/client.js';
import { HazardCard, LevelBadge, RainCard } from '../components/Hazard.jsx';
import { ClockIcon, WarnIcon } from '../components/Icons.jsx';
import SensorCharts from '../components/SensorCharts.jsx';
import { useLive } from '../context/LiveContext.jsx';
import { useNow } from '../hooks/useApi.js';
import {
  EMAIL_STATUS,
  fixed,
  formatAgo,
  formatClock,
  formatIn,
  formatTime,
  HAZARD_NAMES,
  kmh,
  percent,
} from '../utils/format.js';

const RANGES = [
  { label: '24 h', hours: 24 },
  { label: '48 h', hours: 48 },
  { label: '7 d', hours: 168 },
];
const ARROWS = { up: '↑', down: '↓', steady: '→' };
const FLAG_TEXT = {
  spike: 'sudden jump',
  stuck: 'value not changing',
  out_of_range: 'out of range',
  null: 'no value',
};

function flagFor(reading, fields) {
  const flag = reading?.qc_flags?.find((f) => fields.includes(f.split(':')[0]));
  if (!flag) return null;
  const [field, rule] = flag.split(':');
  return `${field.replace(/_/g, ' ')}: ${FLAG_TEXT[rule] ?? rule.replace(/_/g, ' ')}`;
}

function ReadingCard({ label, value, unit, digits = 1, trend, sub, flag }) {
  return (
    <div className={`card reading${flag ? ' flagged' : ''}`}>
      <span className="label">{label}</span>
      <span className="val">
        {fixed(value, digits)}
        <small>{unit}</small>
        {trend && (
          <span className="trend" title={trend}>
            {ARROWS[trend]}
          </span>
        )}
      </span>
      {sub && <span className="sub">{sub}</span>}
      {flag && (
        <span className="qc" title="Flagged by quality control">
          ⚠ {flag}
        </span>
      )}
    </div>
  );
}

function SensorNote({ reading, settings }) {
  if (!reading) return null;
  const limit = settings?.fusion_mismatch?.temp_c ?? 3;
  if (reading.fallback) {
    return (
      <div className="note warn">
        <WarnIcon />
        <span>
          <strong>Sensor check:</strong> BME280 value unusable — using the DHT11 backup for temperature/humidity. 🔁
        </span>
      </div>
    );
  }
  if (reading.temp_bme_c == null || reading.temp_dht_c == null) return null;
  const diff = Math.abs(reading.temp_bme_c - reading.temp_dht_c);
  const mismatch = reading.qc_flags?.some((f) => f.endsWith(':bme_dht_mismatch'));
  return (
    <div className={`note ${mismatch ? 'warn' : 'info'}`}>
      {mismatch && <WarnIcon />}
      <span>
        <strong>Sensor check:</strong> DHT11 and BME280 differ by {fixed(diff)} °C
        {mismatch ? `, more than the ${limit} °C limit.` : `, within the ${limit} °C limit.`} Using BME280.
      </span>
    </div>
  );
}

function RecentAlerts({ tz, cooldownHours }) {
  const { subscribe } = useLive();
  const [alerts, setAlerts] = useState(null);

  useEffect(() => {
    const load = () => api.get(`/api/alerts${query({ page_size: 3 })}`).then((r) => setAlerts(r.items)).catch(() => {});
    load();
    return subscribe((type) => type === 'alert' && load());
  }, [subscribe]);

  const describe = (a) => {
    if (a.email_status === 'sent' && cooldownHours) {
      const until = new Date(new Date(a.created_at).getTime() + cooldownHours * 3600_000);
      return `${EMAIL_STATUS.sent} · repeats paused until ${formatTime(until, tz)}`;
    }
    return EMAIL_STATUS[a.email_status] ?? a.email_status;
  };

  return (
    <section className="section" aria-labelledby="recent-h">
      <div className="row-head">
        <h2 id="recent-h">Recent alerts</h2>
        <Link to="/alerts" style={{ fontSize: 14, minHeight: 44, display: 'inline-flex', alignItems: 'center' }}>
          View all alerts →
        </Link>
      </div>
      <div className="card">
        {alerts === null && <div className="alert-row muted">Loading…</div>}
        {alerts?.length === 0 && (
          <div className="alert-row muted">No alerts yet. Orange and Red risk will appear here and be emailed.</div>
        )}
        {alerts?.map((a) => (
          <div className="alert-row" key={a.id}>
            <LevelBadge level={a.level} small />
            <span style={{ fontWeight: 600, fontSize: 15 }}>
              {HAZARD_NAMES[a.hazard]} · {percent(a.probability)}
            </span>
            <span style={{ color: 'var(--text2)', fontSize: 14, flex: '1 1 200px' }}>{describe(a)}</span>
            <span className="mono small muted">{formatTime(a.created_at, tz)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function DashboardPage() {
  const { system, kit, reading, connected, subscribe, tz } = useLive();
  const now = useNow(1000);
  const [range, setRange] = useState(RANGES[0]);
  const [series, setSeries] = useState(null);
  const kitId = kit?.kit_id;
  const settings = system?.settings;

  useEffect(() => {
    if (!kitId) return undefined;
    let cancelled = false;
    const from = new Date(Date.now() - range.hours * 3600_000).toISOString();
    api
      .get(`/api/readings${query({ kit_id: kitId, from })}`)
      .then((result) => !cancelled && setSeries(result))
      .catch(() => !cancelled && setSeries({ points: [], resolution: 'raw' }));
    return () => {
      cancelled = true;
    };
  }, [kitId, range]);

  // Append live readings to the raw series
  useEffect(
    () =>
      subscribe((type, data) => {
        if (type !== 'reading' || data.kit_id !== kitId) return;
        setSeries((current) => {
          if (!current || current.resolution !== 'raw') return current;
          const cutoff = Date.now() - range.hours * 3600_000;
          const point = { ...data, wind_max_ms: data.wind_speed_ms };
          const points = [...current.points.filter((p) => Date.parse(p.ts) >= cutoff), point];
          return { ...current, points };
        });
      }),
    [subscribe, kitId, range],
  );

  const online = kit?.status === 'online';
  const statusColor = online ? 'var(--green)' : kit?.status === 'offline' ? 'var(--red)' : 'var(--grey)';
  const nextRun = system?.scheduler?.next_run;

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="label" style={{ fontSize: 12 }}>
            {formatClock(now, tz)}
          </span>
          <h1>Next {settings?.horizon_hours ?? 3} hours at a glance</h1>
        </div>
        <div className="pills">
          <span className="pill" style={{ color: 'var(--text)' }}>
            <span className="dot" style={{ background: statusColor }} />
            {kitId?.toUpperCase() ?? 'KIT'} {kit?.status ?? 'unknown'} · {formatAgo(kit?.last_seen, now)}
          </span>
          <span className="pill">
            <ClockIcon />
            {nextRun ? `Next model run ${formatIn(nextRun, now)}` : 'Scheduler not running'}
          </span>
          <span className="pill" title={connected ? 'Live updates connected' : 'Reconnecting — refreshing every 30 s'}>
            <span className="dot" style={{ background: connected ? 'var(--accent)' : 'var(--grey)' }} />
            {connected ? 'Live' : 'Reconnecting'}
          </span>
        </div>
      </header>

      <section className="hazards" aria-label="Hazard outlook">
        <HazardCard hazard="heat" />
        <HazardCard hazard="wind" />
        <RainCard />
      </section>

      <section className="section" aria-labelledby="live-h">
        <div className="row-head">
          <h2 id="live-h">Live readings · {kitId?.toUpperCase() ?? '—'}</h2>
          <span className="mono small muted">
            {reading
              ? `${formatTime(reading.ts, tz)} · every ${Math.round((kit?.interval_s ?? 300) / 60)} min · ${
                  reading.qc_flags.length ? 'QC flags present' : 'QC passed'
                }`
              : 'no readings yet'}
          </span>
        </div>
        <div className="grid-auto">
          <ReadingCard
            label="Temperature"
            value={reading?.temp_c}
            unit=" °C"
            trend={reading?.trend?.temp_c}
            sub={reading?.temp_dht_c != null ? `${reading.fallback ? 'DHT11 (backup)' : 'BME280'} · DHT11 reads ${fixed(reading.temp_dht_c, 0)}` : 'BME280'}
            flag={flagFor(reading, ['temp_bme_c', 'temp_c'])}
          />
          <ReadingCard
            label="Humidity"
            value={reading?.hum_pct}
            unit=" %"
            digits={0}
            trend={reading?.trend?.hum_pct}
            sub={
              reading?.dewpoint_c != null
                ? `Dew point ${fixed(reading.dewpoint_c)} °C · DHT11 reads ${fixed(reading.hum_dht_pct, 0)} %`
                : null
            }
            flag={flagFor(reading, ['hum_bme_pct', 'hum_pct'])}
          />
          <ReadingCard
            label="Pressure"
            value={reading?.pressure_hpa}
            unit=" hPa"
            trend={reading?.trend?.pressure_hpa}
            sub={
              reading?.pressure_change_3h != null
                ? `${reading.pressure_change_3h < 0 ? '↓' : '↑'} ${fixed(Math.abs(reading.pressure_change_3h))} hPa over 3 h`
                : null
            }
            flag={flagFor(reading, ['pressure_hpa'])}
          />
          <ReadingCard
            label="Wind"
            value={reading?.wind_speed_ms}
            unit=" m/s"
            trend={reading?.trend?.wind_speed_ms}
            sub={reading?.wind_speed_ms != null ? `${fixed(kmh(reading.wind_speed_ms), 0)} km/h` : null}
            flag={flagFor(reading, ['wind_speed_ms'])}
          />
          <div className="card reading empty">
            <span className="label">Rainfall</span>
            <span className="val" style={{ color: 'var(--faint)' }}>
              —
            </span>
            <span className="sub" style={{ color: 'var(--muted)' }}>
              Gauge not fitted yet
            </span>
          </div>
        </div>
        <SensorNote reading={reading} settings={settings} />
      </section>

      <section className="section" aria-labelledby="trend-h">
        <div className="row-head" style={{ alignItems: 'center' }}>
          <h2 id="trend-h">Last {range.label.replace(' h', ' hours').replace(' d', ' days')}</h2>
          <div className="seg" role="group" aria-label="Range">
            {RANGES.map((r) => (
              <button key={r.label} type="button" aria-pressed={r === range} onClick={() => setRange(r)}>
                {r.label}
              </button>
            ))}
          </div>
        </div>
        {series ? (
          <SensorCharts
            points={series.points}
            settings={settings}
            tz={tz}
            hourly={series.resolution === 'hourly'}
            multiDay={range.hours > 48}
          />
        ) : (
          <div className="loading">Loading charts…</div>
        )}
      </section>

      <RecentAlerts tz={tz} cooldownHours={settings?.cooldown_hours} />
    </>
  );
}
