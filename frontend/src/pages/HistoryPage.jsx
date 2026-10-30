import { useMemo, useState } from 'react';
import { api, query } from '../api/client.js';
import { DownloadIcon } from '../components/Icons.jsx';
import SensorCharts from '../components/SensorCharts.jsx';
import { useLive } from '../context/LiveContext.jsx';
import { useApi } from '../hooks/useApi.js';
import { formatDateTime, percent } from '../utils/format.js';

const TIMELINE_LABELS = { wind: 'Wind', heat: 'Heat' };

const PRESETS = [
  { label: '24 h', hours: 24 },
  { label: '7 days', hours: 168 },
  { label: '30 days', hours: 720 },
];
const CHARTS = [
  { key: 'temperature', label: 'Temperature' },
  { key: 'humidity', label: 'Humidity' },
  { key: 'pressure', label: 'Pressure' },
  { key: 'wind', label: 'Wind' },
  { key: 'risk', label: 'Predicted risk' },
];

const isoDate = (date) => date.toISOString().slice(0, 10);

function RiskTimeline({ predictions, tz }) {
  if (!predictions.length) return <p className="muted">No predictions in this range.</p>;
  return (
    <div className="card" style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="timeline">
        {['wind', 'heat'].map((hazard) => (
          <div key={hazard} style={{ display: 'contents' }}>
            <span className="mono small">{TIMELINE_LABELS[hazard]}</span>
            <div className="cells">
              {predictions
                .filter((p) => p.hazard === hazard)
                .map((p) => {
                  const level = p.status === 'ok' ? p.level : null;
                  const title =
                    `${formatDateTime(p.run_at, tz)} · ` +
                    (level ? `${level} (Yellow ${percent(p.p.yellow)}, Orange ${percent(p.p.orange)}, Red ${percent(p.p.red)})` : 'insufficient data');
                  return <span key={p.id} title={title} style={{ background: level ? `var(--${level})` : 'var(--grey)' }} />;
                })}
            </div>
          </div>
        ))}
      </div>
      <div className="legend">
        {['green', 'yellow', 'orange', 'red'].map((l) => (
          <span key={l} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <i style={{ background: `var(--${l})`, height: 10, width: 10 }} />
            {l}
          </span>
        ))}
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <i style={{ background: 'var(--grey)', height: 10, width: 10 }} />
          no data
        </span>
        <span>one cell per hourly prediction · hover for details</span>
      </div>
    </div>
  );
}

export default function HistoryPage() {
  const { kit, system, tz } = useLive();
  const [preset, setPreset] = useState(PRESETS[1]);
  const [custom, setCustom] = useState(() => ({
    from: isoDate(new Date(Date.now() - 7 * 86400_000)),
    to: isoDate(new Date()),
  }));
  const [shown, setShown] = useState(() => new Set(CHARTS.map((c) => c.key)));
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState(null);

  // Custom dates are whole days in the browser's local time
  const range = useMemo(() => {
    if (preset) {
      const to = new Date();
      return { from: new Date(to.getTime() - preset.hours * 3600_000).toISOString(), to: to.toISOString() };
    }
    return {
      from: new Date(`${custom.from}T00:00:00`).toISOString(),
      to: new Date(`${custom.to}T23:59:59`).toISOString(),
    };
  }, [preset, custom]);

  const kitId = kit?.kit_id;
  const params = kitId ? query({ kit_id: kitId, ...range }) : null;
  const readings = useApi(params ? `/api/readings${params}` : null);
  const predictions = useApi(params ? `/api/predictions${params}` : null);
  const multiDay = Date.parse(range.to) - Date.parse(range.from) > 2 * 86400_000;

  const toggle = (key) =>
    setShown((set) => {
      const next = new Set(set);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const download = async () => {
    setDownloading(true);
    setDownloadError(null);
    try {
      const response = await api.raw(`/api/readings/export.csv${params}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${kitId}_${range.from.slice(0, 10)}_${range.to.slice(0, 10)}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setDownloadError(err.message);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="label" style={{ fontSize: 12 }}>
            Readings &amp; predictions
          </span>
          <h1>History</h1>
          <p>Stored data for any period, with the hourly risk the models predicted. Ranges over 7 days show hourly averages.</p>
        </div>
        <button type="button" className="btn-ghost" onClick={download} disabled={!params || downloading}>
          <DownloadIcon />
          {downloading ? 'Preparing…' : 'Download CSV'}
        </button>
      </header>
      {downloadError && <div className="note bad">{downloadError}</div>}

      <div className="filters">
        <div className="chips" role="group" aria-label="Range">
          {PRESETS.map((p) => (
            <button key={p.label} type="button" aria-pressed={preset === p} onClick={() => setPreset(p)}>
              {p.label}
            </button>
          ))}
          <button type="button" aria-pressed={!preset} onClick={() => setPreset(null)}>
            Custom
          </button>
        </div>
        {!preset && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <label className="sr-only" htmlFor="from">
              From
            </label>
            <input id="from" type="date" value={custom.from} max={custom.to} onChange={(e) => setCustom((c) => ({ ...c, from: e.target.value }))} />
            <span className="muted">→</span>
            <label className="sr-only" htmlFor="to">
              To
            </label>
            <input id="to" type="date" value={custom.to} min={custom.from} onChange={(e) => setCustom((c) => ({ ...c, to: e.target.value }))} />
          </div>
        )}
      </div>
      <div className="chips" role="group" aria-label="Show">
        {CHARTS.map((c) => (
          <button key={c.key} type="button" aria-pressed={shown.has(c.key)} onClick={() => toggle(c.key)}>
            {c.label}
          </button>
        ))}
      </div>

      {readings.error && <div className="note bad">{readings.error}</div>}
      {readings.loading && !readings.data && <div className="loading">Loading readings…</div>}
      {readings.data && (
        <SensorCharts
          points={readings.data.points}
          settings={system?.settings}
          tz={tz}
          hourly={readings.data.resolution === 'hourly'}
          multiDay={multiDay}
          show={[...shown]}
        />
      )}

      {shown.has('risk') && (
        <section className="section" aria-labelledby="risk-h">
          <h2 id="risk-h">Predicted risk timeline</h2>
          {predictions.data ? <RiskTimeline predictions={predictions.data.items} tz={tz} /> : <div className="loading">Loading…</div>}
        </section>
      )}
    </>
  );
}
