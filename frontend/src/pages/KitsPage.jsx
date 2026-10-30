import { useEffect, useState } from 'react';
import { api, query } from '../api/client.js';
import { ChipIcon } from '../components/Icons.jsx';
import { useLive } from '../context/LiveContext.jsx';
import { useApi, useNow } from '../hooks/useApi.js';
import { fixed, formatAgo, formatDateTime, formatIn, formatTime } from '../utils/format.js';

const TAGS = {
  ok: ['t-ok', 'OK'],
  warn: ['t-warn', 'CHECK'],
  fault: ['t-bad', 'FAULT'],
  not_fitted: ['t-off', 'NOT FITTED'],
};

function SensorRow({ name, description, health }) {
  const [className, text] = TAGS[health?.status] ?? ['t-off', '—'];
  const off = health?.status === 'not_fitted';
  return (
    <div className={`sensor${off ? ' off' : ''}`}>
      <span className="nm" style={off ? { color: 'var(--muted)' } : undefined}>
        {name}
      </span>
      <span className="ds" style={off ? { color: 'var(--muted)' } : undefined}>
        {description}
        {health?.detail ? ` · ${health.detail}` : ''}
      </span>
      <span className={`tag ${className}`}>{health?.status === 'warn' && health.drift_c ? `DRIFT ${fixed(health.drift_c)} °C` : text}</span>
    </div>
  );
}

function Stat({ label, value, sub }) {
  return (
    <div className="card stat">
      <span className="label">{label}</span>
      <span className="n" style={{ fontSize: 26 }}>
        {value}
      </span>
      {sub && <span className="d">{sub}</span>}
    </div>
  );
}

function Health({ ok }) {
  return (
    <dd>
      <span className={`tag ${ok ? 't-ok' : 't-bad'}`}>{ok ? 'OK' : 'DOWN'}</span>
    </dd>
  );
}

function RunNowButton() {
  const { refresh } = useLive();
  const [state, setState] = useState({ busy: false, message: null });
  const run = async () => {
    setState({ busy: true, message: null });
    try {
      const result = await api.post('/api/predictions/run');
      const summary = result.items.map((p) => `${p.hazard} ${p.status === 'ok' ? p.level : 'insufficient data'}`).join(', ');
      setState({ busy: false, message: `Done: ${summary || 'no enabled kits'}` });
      refresh();
    } catch (err) {
      setState({ busy: false, message: err.message });
    }
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <button type="button" className="btn-ghost" onClick={run} disabled={state.busy}>
        {state.busy ? 'Running…' : 'Run prediction now'}
      </button>
      {state.message && <span className="small muted">{state.message}</span>}
    </div>
  );
}

export default function KitsPage() {
  const { kit, system, subscribe, tz } = useLive();
  const now = useNow(1000);
  const kitId = kit?.kit_id;
  const quality = useApi(kitId ? `/api/quality${query({ kit_id: kitId })}` : null);
  const history = useApi(kitId ? `/api/kits/${kitId}/status-history` : null);
  const { reload } = quality;
  useEffect(() => subscribe((type) => type === 'kit_status' && reload()), [subscribe, reload]);

  const q = quality.data;
  const s = system?.settings;
  const email = system?.components?.email;
  const online = kit?.status === 'online';
  const gapMinutes = q?.gaps.reduce((sum, g) => sum + g.minutes, 0) ?? 0;

  return (
    <>
      <header className="page-head" style={{ alignItems: 'flex-end' }}>
        <div className="titles">
          <span className="label" style={{ fontSize: 12 }}>
            Devices
          </span>
          <h1>Kits</h1>
        </div>
        <button type="button" className="btn-ghost" disabled style={{ borderStyle: 'dashed' }}>
          + Register kit (coming later)
        </button>
      </header>

      {kit && (
        <article className="card kit">
          <div style={{ flex: '1 1 280px', display: 'flex', flexDirection: 'column', gap: 18 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <div style={{ width: 56, height: 56, borderRadius: 14, background: 'var(--active)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <ChipIcon />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <h2 className="mono" style={{ fontSize: 24 }}>
                  {kit.kit_id.toUpperCase()}
                </h2>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 14, color: 'var(--text2)' }}>
                  <span className="dot" style={{ background: online ? 'var(--green)' : kit.status === 'offline' ? 'var(--red)' : 'var(--grey)' }} />
                  {kit.status[0].toUpperCase() + kit.status.slice(1)} · last reading {formatAgo(kit.last_seen, now)}
                </span>
              </div>
            </div>
            <dl>
              <dt>Location</dt>
              <dd>{kit.description || '—'}</dd>
              <dt>Coordinates</dt>
              <dd className="mono">
                {fixed(kit.latitude, 3)}°N, {fixed(kit.longitude, 3)}°E
              </dd>
              <dt>Anemometer</dt>
              <dd>{kit.anemometer_height_m ? `${kit.anemometer_height_m} m above roof/ground` : '—'}</dd>
              <dt>Board</dt>
              <dd>ESP32</dd>
              <dt>Firmware</dt>
              <dd className="mono">{kit.fw_version || '—'}</dd>
              <dt>Interval</dt>
              <dd>{kit.interval_s >= 120 ? `${Math.round(kit.interval_s / 60)} min` : `${kit.interval_s} s`}</dd>
              <dt>Uptime</dt>
              <dd>{history.data ? `${fixed(history.data.uptime_pct)}% · last ${history.data.days} days` : '—'}</dd>
              <dt>MQTT topic</dt>
              <dd className="mono" style={{ fontSize: 13 }}>
                {kit.telemetry_topic}
              </dd>
              {kit.notes && (
                <>
                  <dt>Notes</dt>
                  <dd>{kit.notes}</dd>
                </>
              )}
            </dl>
          </div>
          <div style={{ flex: '2 1 420px', display: 'flex', flexDirection: 'column', gap: 12 }}>
            <h3>Sensor health · last 24 h</h3>
            <SensorRow name="BME280" description="Temp · humidity · pressure — primary" health={q?.sensors.bme280} />
            <SensorRow name="DHT11" description="Temp · humidity — backup & cross-check" health={q?.sensors.dht11} />
            <SensorRow name="Anemometer" description="Wind speed" health={q?.sensors.anemometer} />
            <SensorRow name="Rain gauge" description="DFRobot SEN0575 — planned" health={q?.sensors.rain_gauge ?? { status: 'not_fitted' }} />
            {history.data && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                <h3>Data received · last {history.data.days} days</h3>
                <div className="strip">
                  {history.data.daily.map((d) => (
                    <div key={d.date} title={`${d.date}: ${Math.round(d.share * 100)}% of 5-min slots`}>
                      <span
                        className="bar"
                        style={{ background: d.share >= 0.95 ? 'var(--green)' : d.share >= 0.5 ? 'var(--yellow)' : d.share > 0 ? 'var(--orange)' : 'var(--line)' }}
                      />
                      {d.date.slice(8)}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </article>
      )}

      <section className="section" aria-labelledby="qc-h">
        <h2 id="qc-h">Data quality · last 24 h</h2>
        <div className="grid-auto">
          <Stat label="Readings received" value={q ? `${q.received.toLocaleString()} / ${q.expected.toLocaleString()}` : '—'} />
          <Stat label="Spikes flagged" value={q ? q.flags.spike : '—'} />
          <Stat label="Stuck sensor" value={q ? q.flags.stuck || 'None' : '—'} />
          <Stat label="Offline gaps" value={q ? (q.gaps.length ? `${q.gaps.length} · ${gapMinutes} min` : 'None') : '—'} />
          <Stat label="BME/DHT mismatch" value={q ? q.flags.bme_dht_mismatch : '—'} />
          <Stat label="DHT11 fallback" value={q ? (q.fallback_minutes ? `${q.fallback_minutes} min` : 'None') : '—'} />
        </div>
      </section>

      {system && (
        <section className="section" aria-labelledby="sys-h">
          <div className="row-head" style={{ alignItems: 'center' }}>
            <h2 id="sys-h">System</h2>
            <RunNowButton />
          </div>
          <div className="card" style={{ padding: 24 }}>
            <dl>
              <dt>Predictions</dt>
              <dd>
                Last run {system.scheduler.last_run ? formatDateTime(system.scheduler.last_run, tz) : '—'} · next{' '}
                {system.scheduler.next_run ? `${formatTime(system.scheduler.next_run, tz)} (${formatIn(system.scheduler.next_run, now)})` : '—'}
              </dd>
              <dt>Model</dt>
              <dd>
                {system.model.version ?? 'none loaded'}
                {system.model.data_source ? ` · trained on ${system.model.data_source} data` : ''}
                {system.model.error ? ` · ${system.model.error}` : ''}
              </dd>
              <dt>Database</dt>
              <Health ok={system.components.database === 'ok'} />
              <dt>MQTT broker</dt>
              <Health ok={system.components.mqtt === 'connected'} />
              <dt>Email</dt>
              <dd>
                <span className={`tag ${!email.enabled ? 't-off' : email.last_failed_at && (!email.last_sent_at || email.last_failed_at > email.last_sent_at) ? 't-bad' : 't-ok'}`}>
                  {!email.enabled ? 'OFF' : email.last_failed_at && (!email.last_sent_at || email.last_failed_at > email.last_sent_at) ? 'LAST SEND FAILED' : 'OK'}
                </span>{' '}
                to {email.recipient} via {email.host} · last sent {email.last_sent_at ? formatDateTime(email.last_sent_at, tz) : 'never'}
              </dd>
              <dt>Backend</dt>
              <dd className="mono">v{system.version}</dd>
            </dl>
          </div>
        </section>
      )}

      {s && (
        <section className="section" aria-labelledby="set-h">
          <div className="row-head">
            <h2 id="set-h">Active settings</h2>
            <span className="mono small muted">read-only · edit config/site.yaml and restart</span>
          </div>
          <div className="card" style={{ padding: 24 }}>
            <dl>
              <dt>Wind levels</dt>
              <dd>
                Peak wind ≥ {s.wind_kmh.yellow} / {s.wind_kmh.orange} / {s.wind_kmh.red} km/h (Yellow / Orange / Red)
              </dd>
              <dt>Heat levels</dt>
              <dd>
                ≥ {s.heat.abs_threshold_c} °C and +{s.heat.departure_c.yellow} °C (Yellow) / +{s.heat.departure_c.orange} °C (Orange) above normal max · Red ≥{' '}
                {s.heat.red_abs_c} °C
              </dd>
              <dt>Heavy rain</dt>
              <dd>{s.rain_enabled ? 'On' : 'Off in v1 (no rain gauge)'}</dd>
              <dt>Horizon</dt>
              <dd>Next {s.horizon_hours} hours, predicted every hour</dd>
              <dt>Show a level at</dt>
              <dd>Probability ≥ {Math.round(s.show_level_cutoff * 100)}%</dd>
              <dt>Email alerts</dt>
              <dd>
                {s.alert_levels.map((l) => l[0].toUpperCase() + l.slice(1)).join(', ')} · cooldown {s.cooldown_hours} h
              </dd>
              <dt>Kit offline after</dt>
              <dd>{s.offline_after_min} min without readings</dd>
              <dt>Enough data</dt>
              <dd>
                ≤ {Math.round(s.data_sufficiency.max_missing_share_24h * 100)}% missing in 24 h and a reading in the last{' '}
                {s.data_sufficiency.require_data_within_min} min
              </dd>
            </dl>
          </div>
        </section>
      )}
    </>
  );
}
