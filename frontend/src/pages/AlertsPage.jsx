import { useEffect, useMemo, useState } from 'react';
import { query } from '../api/client.js';
import { LevelBadge } from '../components/Hazard.jsx';
import { useLive } from '../context/LiveContext.jsx';
import { useApi } from '../hooks/useApi.js';
import { EMAIL_STATUS, formatDateTime, HAZARD_NAMES, outcomeText, percent } from '../utils/format.js';

const HAZARD_FILTERS = [
  { label: 'All', value: null },
  { label: 'Heat wave', value: 'heat' },
  { label: 'High wind', value: 'wind' },
];
const PERIODS = [
  { label: 'Last 7 days', days: 7 },
  { label: 'Last 30 days', days: 30 },
  { label: 'Last 90 days', days: 90 },
  { label: 'All time', days: null },
];
const PAGE_SIZE = 20;

const EMAIL_SHORT = { sent: '✅ Sent', cooldown: '⏸ Cooldown', failed: '❌ Failed', disabled: '— Off' };

export default function AlertsPage() {
  const { system, subscribe, tz } = useLive();
  const [hazard, setHazard] = useState(null);
  const [level, setLevel] = useState(null);
  const [period, setPeriod] = useState(PERIODS[1]);
  const [page, setPage] = useState(1);

  const from = useMemo(
    () => (period.days ? new Date(Date.now() - period.days * 86400_000).toISOString() : null),
    [period],
  );
  const alerts = useApi(`/api/alerts${query({ hazard, level, from, page, page_size: PAGE_SIZE })}`);
  const { reload } = alerts;
  useEffect(() => subscribe((type) => type === 'alert' && reload()), [subscribe, reload]);
  useEffect(() => setPage(1), [hazard, level, period]);

  const settings = system?.settings;
  const levels = settings?.alert_levels ?? ['orange', 'red'];
  const stats = alerts.data?.stats;

  return (
    <>
      <header className="page-head">
        <div className="titles">
          <span className="label" style={{ fontSize: 12 }}>
            History
          </span>
          <h1>Alerts</h1>
          <p>
            {levels.map((l) => l[0].toUpperCase() + l.slice(1)).join(' and ')} send email to the admin. Each hazard waits{' '}
            {settings?.cooldown_hours ?? 3} h before re-alerting at the same or a lower level; a higher level is sent at once.
          </p>
        </div>
      </header>

      <div className="grid-auto" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
        <div className="card stat">
          <span className="label">Last {stats?.days ?? 7} days</span>
          <span className="n">{stats?.raised ?? '—'}</span>
          <span className="d">alerts raised</span>
        </div>
        <div className="card stat">
          <span className="label">Emailed</span>
          <span className="n">{stats?.emailed ?? '—'}</span>
          <span className="d">sent to the admin</span>
        </div>
        <div className="card stat">
          <span className="label">Confirmed</span>
          <span className="n">{stats ? (stats.evaluated ? `${stats.confirmed} of ${stats.evaluated}` : '—') : '—'}</span>
          <span className="d">emailed alerts where the hazard happened</span>
        </div>
      </div>

      <div className="filters">
        <div className="chips" role="group" aria-label="Filter by hazard">
          {HAZARD_FILTERS.map((h) => (
            <button key={h.label} type="button" aria-pressed={hazard === h.value} onClick={() => setHazard(h.value)}>
              {h.label}
            </button>
          ))}
        </div>
        <div className="chips" role="group" aria-label="Filter by level">
          <button type="button" aria-pressed={level === null} onClick={() => setLevel(null)}>
            Any level
          </button>
          {levels.map((l) => (
            <button key={l} type="button" aria-pressed={level === l} onClick={() => setLevel(l)}>
              {l[0].toUpperCase() + l.slice(1)}
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="period">
          Period
        </label>
        <select id="period" value={period.label} onChange={(e) => setPeriod(PERIODS.find((p) => p.label === e.target.value))}>
          {PERIODS.map((p) => (
            <option key={p.label}>{p.label}</option>
          ))}
        </select>
      </div>

      {alerts.error && <div className="note bad">{alerts.error}</div>}
      <div className="card tablebox">
        <table>
          <thead>
            <tr>
              <th scope="col">Issued</th>
              <th scope="col">Hazard</th>
              <th scope="col">Level</th>
              <th scope="col">Prob.</th>
              <th scope="col">Valid to</th>
              <th scope="col">Kit</th>
              <th scope="col">Email</th>
              <th scope="col">Outcome</th>
            </tr>
          </thead>
          <tbody>
            {alerts.data?.items.map((a) => (
              <tr key={a.id}>
                <td className="mono" style={{ fontSize: 13, whiteSpace: 'nowrap' }}>
                  {formatDateTime(a.created_at, tz)}
                </td>
                <td className="h">{HAZARD_NAMES[a.hazard]}</td>
                <td>
                  <LevelBadge level={a.level} small />
                </td>
                <td className="mono" style={{ color: 'var(--text)' }}>
                  {percent(a.probability)}
                </td>
                <td className="mono" style={{ fontSize: 13 }}>
                  {formatDateTime(a.valid_until, tz).split(' · ')[1]}
                </td>
                <td className="mono">{a.kit_id.toUpperCase()}</td>
                <td title={a.error || EMAIL_STATUS[a.email_status]}>{EMAIL_SHORT[a.email_status] ?? a.email_status}</td>
                <td>{outcomeText(a.outcome, tz)}</td>
              </tr>
            ))}
            {alerts.data?.items.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  No alerts match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {alerts.data && alerts.data.pages > 1 && (
          <div className="pager">
            <button type="button" className="btn-ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              ◀ Prev
            </button>
            <span>
              Page {alerts.data.page} of {alerts.data.pages}
            </span>
            <button type="button" className="btn-ghost" disabled={page >= alerts.data.pages} onClick={() => setPage((p) => p + 1)}>
              Next ▶
            </button>
          </div>
        )}
      </div>
    </>
  );
}
