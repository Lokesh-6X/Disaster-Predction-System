import { useLive } from '../context/LiveContext.jsx';
import { EMAIL_STATUS, HAZARD_NAMES, percent } from '../utils/format.js';
import { LevelBadge } from './Hazard.jsx';

/** Pop-up notices for new alerts arriving over the live connection. */
export default function Toasts() {
  const { toasts, dismissToast } = useLive();
  if (!toasts.length) return null;
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="toast">
          <LevelBadge level={t.level} small />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <strong>
              {HAZARD_NAMES[t.hazard]} · {percent(t.probability)}
            </strong>
            <span className="small muted">{EMAIL_STATUS[t.email_status] ?? t.email_status}</span>
          </div>
          <button type="button" aria-label="Dismiss" onClick={() => dismissToast(t.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
