import { useLive } from '../context/LiveContext.jsx';
import {
  fixed,
  formatTime,
  headlineProbability,
  HAZARD_NAMES,
  kmh,
  LEVEL_NAMES,
  LEVELS,
  percent,
} from '../utils/format.js';

export function LevelBadge({ level, small = false }) {
  const known = LEVELS.includes(level);
  return (
    <span className={`badge${small ? ' sm' : ''} ${known ? `b-${level}` : 'b-grey'}`}>
      {known ? level.toUpperCase() : 'NO DATA'}
    </span>
  );
}

const CIRCUMFERENCE = 2 * Math.PI * 50;

export function ProbabilityRing({ probability, level }) {
  const color = LEVELS.includes(level) ? `var(--${level})` : 'var(--grey)';
  const dash = probability === null ? 0 : probability * CIRCUMFERENCE;
  const label = probability === null ? 'No probability' : `Probability ${Math.round(probability * 100)} percent`;
  return (
    <svg width="112" height="112" viewBox="0 0 120 120" role="img" aria-label={label}>
      <circle cx="60" cy="60" r="50" fill="none" stroke="var(--line)" strokeWidth="10" />
      {dash > 0 && (
        <circle
          cx="60"
          cy="60"
          r="50"
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${CIRCUMFERENCE}`}
          transform="rotate(-90 60 60)"
        />
      )}
      <text x="60" y="64" textAnchor="middle" fontFamily="var(--mono)" fontSize="26" fontWeight="600" fill="var(--text)">
        {probability === null ? '—' : percent(probability)}
      </text>
      <text x="60" y="84" textAnchor="middle" fontFamily="var(--mono)" fontSize="10" fill="var(--muted)">
        PROB.
      </text>
    </svg>
  );
}

function Bands({ level }) {
  const soft = { yellow: 'var(--yellow-soft)', orange: 'var(--orange-soft)', red: 'var(--red-soft)' };
  const index = LEVELS.indexOf(level);
  return (
    <div className="bands" aria-hidden="true">
      {LEVELS.map((name, i) => (
        <div
          key={name}
          className={i === index ? 'cur' : undefined}
          style={{ background: i <= index || name === 'green' ? `var(--${name})` : soft[name] }}
        />
      ))}
    </div>
  );
}

function arrow(trend) {
  return { up: 'rising', down: 'falling', steady: 'steady' }[trend] ?? '';
}

/** One hazard (wind or heat): level badge, probability ring, context and band bar. */
export function HazardCard({ hazard }) {
  const { predictions, reading, system, tz } = useLive();
  const prediction = predictions?.items?.find((p) => p.hazard === hazard);
  const settings = system?.settings;
  const ok = prediction?.status === 'ok';
  const level = ok ? prediction.level : null;
  const probability = ok ? headlineProbability(prediction) : null;

  let detail = null;
  let thresholds = null;
  if (hazard === 'heat') {
    const normal = prediction?.context?.tmax_normal_c;
    detail = reading?.temp_c != null && (
      <span>
        Temp {fixed(reading.temp_c)} °C{reading.trend?.temp_c ? `, ${arrow(reading.trend.temp_c)}` : ''}
        {normal != null && (
          <>
            {' · '}
            <span style={{ color: 'var(--text)' }}>normal max today {fixed(normal)} °C</span>
          </>
        )}
      </span>
    );
    if (settings) {
      const h = settings.heat;
      thresholds = `Yellow ≥ ${h.abs_threshold_c} °C & +${h.departure_c.yellow} °C · Orange +${h.departure_c.orange} °C · Red ≥ ${h.red_abs_c} °C`;
    }
  } else {
    detail = reading?.wind_speed_ms != null && (
      <span>
        Wind {fixed(reading.wind_speed_ms)} m/s ({fixed(kmh(reading.wind_speed_ms), 0)} km/h)
        {reading.pressure_change_3h != null && (
          <>
            {' · '}
            <span style={{ color: 'var(--text)' }}>
              pressure {reading.pressure_change_3h < 0 ? 'falling' : 'rising'} {fixed(Math.abs(reading.pressure_change_3h))} hPa / 3 h
            </span>
          </>
        )}
      </span>
    );
    if (settings) {
      const w = settings.wind_kmh;
      thresholds = `Peak wind ≥ ${w.yellow} / ${w.orange} / ${w.red} km/h for Yellow / Orange / Red`;
    }
  }

  return (
    <article className="card hazard" aria-label={`${HAZARD_NAMES[hazard]} outlook`}>
      <div className="top">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span className="label" style={{ fontSize: 12 }}>
            {HAZARD_NAMES[hazard]}
          </span>
          <LevelBadge level={level} />
          {ok && <span className="small muted">{LEVEL_NAMES[hazard][level]}</span>}
        </div>
        <ProbabilityRing probability={probability} level={level} />
      </div>
      <div className="info">
        {prediction && !ok && (
          <span style={{ color: 'var(--text)' }}>
            Insufficient data — no prediction this hour ({prediction.context?.reason ?? 'not enough readings'}).
          </span>
        )}
        {!prediction && <span>No prediction yet — the first one runs at the next full hour.</span>}
        {detail}
        {ok && (
          <span className="probs">
            {['yellow', 'orange', 'red'].map((name) => (
              <span key={name}>
                {name[0].toUpperCase() + name.slice(1)} <b>{percent(prediction.p[name])}</b>
              </span>
            ))}
          </span>
        )}
        {thresholds && <span className="mono small muted">{thresholds}</span>}
        {prediction && (
          <span className="mono small muted">
            Valid until {formatTime(prediction.valid_until, tz)} · predicted {formatTime(prediction.run_at, tz)}
            {prediction.model_version ? ` · model ${prediction.model_version}` : ''}
            {prediction.fallback_used ? ' · 🔁 DHT11 fallback used' : ''}
          </span>
        )}
      </div>
      <Bands level={level} />
    </article>
  );
}

/** Heavy rain is not predicted in v1 (no rain gauge); shown as a placeholder like the design. */
export function RainCard() {
  return (
    <article className="card hazard off" aria-label="Heavy rain outlook (not available)">
      <div className="top">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span className="label" style={{ fontSize: 12 }}>
            Heavy rain
          </span>
          <span className="badge b-grey">OFF</span>
        </div>
        <ProbabilityRing probability={null} level={null} />
      </div>
      <div className="info">
        <span>Not predicted in v1.</span>
        <span className="mono small muted">Rain gauge (DFRobot SEN0575) not fitted yet</span>
      </div>
      <div className="bands" aria-hidden="true">
        {LEVELS.map((name) => (
          <div key={name} style={{ background: 'var(--line)' }} />
        ))}
      </div>
    </article>
  );
}
