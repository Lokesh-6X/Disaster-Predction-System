// Formatting helpers. Times come from the API in UTC and are shown in the site's timezone.

export const DEFAULT_TZ = 'Asia/Kolkata';

const zoneShort = (tz) => (tz === 'Asia/Kolkata' ? 'IST' : tz);

function parts(value, tz, options) {
  return new Intl.DateTimeFormat('en-GB', { timeZone: tz, hourCycle: 'h23', ...options }).format(new Date(value));
}

export function formatTime(value, tz = DEFAULT_TZ) {
  return value ? parts(value, tz, { hour: '2-digit', minute: '2-digit' }) : '—';
}

export function formatDateTime(value, tz = DEFAULT_TZ) {
  if (!value) return '—';
  const date = parts(value, tz, { day: '2-digit', month: 'short' });
  return `${date} · ${formatTime(value, tz)}`;
}

/** Header label like "SAT 31 OCT · 14:23 IST". */
export function formatClock(value, tz = DEFAULT_TZ) {
  const day = parts(value, tz, { weekday: 'short', day: '2-digit', month: 'short' }).replace(',', '');
  return `${day} · ${formatTime(value, tz)} ${zoneShort(tz)}`.toUpperCase();
}

export function formatAgo(value, now = Date.now()) {
  if (!value) return 'never';
  const seconds = Math.max(0, Math.round((now - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds} s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function formatIn(value, now = Date.now()) {
  if (!value) return '—';
  const minutes = Math.round((new Date(value).getTime() - now) / 60000);
  if (minutes <= 0) return 'now';
  if (minutes < 60) return `in ${minutes} min`;
  return `in ${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export const kmh = (ms) => (ms === null || ms === undefined ? null : ms * 3.6);

export function fixed(value, digits = 1) {
  return value === null || value === undefined || Number.isNaN(value) ? '—' : Number(value).toFixed(digits);
}

export const percent = (p) => (p === null || p === undefined ? '—' : `${Math.round(p * 100)}%`);

export const LEVELS = ['green', 'yellow', 'orange', 'red'];

export const HAZARD_NAMES = { wind: 'High wind', heat: 'Heat wave', rain: 'Heavy rain' };

export const LEVEL_NAMES = {
  wind: { green: 'Normal', yellow: 'Gusty wind', orange: 'Strong gusty wind', red: 'Severe / damaging wind' },
  heat: { green: 'Normal', yellow: 'Heat wave', orange: 'Severe heat wave', red: 'Extreme heat' },
};

/** The probability shown in the ring: the current level's, or Yellow's when Green. */
export function headlineProbability(prediction) {
  if (!prediction?.p) return null;
  const level = prediction.level === 'green' ? 'yellow' : prediction.level;
  return prediction.p[level] ?? null;
}

export const EMAIL_STATUS = {
  sent: 'Email sent',
  cooldown: 'Paused (cooldown) — no email',
  failed: 'Email failed — retried next hour',
  disabled: 'Alerts switched off — recorded only',
};

export function outcomeText(outcome, tz = DEFAULT_TZ) {
  if (!outcome) return '—';
  switch (outcome.status) {
    case 'pending':
      return `Pending (window ends ${formatTime(outcome.window_end, tz)})`;
    case 'unknown':
      return 'Not enough data to check';
    case 'happened':
    case 'did_not_happen': {
      const measured =
        outcome.peak_wind_kmh !== undefined
          ? `peak wind ${Math.round(outcome.peak_wind_kmh)} km/h`
          : `max ${fixed(outcome.tmax_c)} °C`;
      return `${outcome.status === 'happened' ? 'Happened' : 'Did not happen'} · ${measured}`;
    }
    default:
      return '—';
  }
}
