import { useState } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useColors } from '../context/ThemeContext.jsx';
import { formatDateTime, formatTime } from '../utils/format.js';

/**
 * A card with one line chart.
 * lines: [{ key, label, color (token name), dashed? }]; refs: [{ y, label, color }].
 * Legend entries toggle their line.
 */
export default function TimeSeriesChart({ title, unit, data, lines, refs = [], tz, multiDay = false, domain }) {
  const tokens = [...new Set(['line', 'muted', 'card', 'text', ...lines.map((l) => l.color), ...refs.map((r) => r.color)])];
  const colors = useColors(tokens);
  const [hidden, setHidden] = useState(() => new Set());
  const hasData = data.some((point) => lines.some((l) => point[l.key] !== null && point[l.key] !== undefined));

  const toggle = (key) =>
    setHidden((set) => {
      const next = new Set(set);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <figure className="card">
      <figcaption>
        <span style={{ fontWeight: 600 }}>{title}</span>
        <span className="legend">
          {lines.length > 1
            ? lines.map((l) => (
                <button key={l.key} type="button" aria-pressed={!hidden.has(l.key)} onClick={() => toggle(l.key)}>
                  <i style={{ background: colors[l.color] }} />
                  {l.label}
                </button>
              ))
            : null}
          <span>{unit}</span>
        </span>
      </figcaption>
      {hasData ? (
        <div className="chart-box">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid stroke={colors.line} strokeDasharray="2 4" vertical={false} />
              <XAxis
                dataKey="t"
                type="number"
                scale="time"
                domain={['dataMin', 'dataMax']}
                tickFormatter={(t) => (multiDay ? formatDateTime(t, tz).split(' · ')[0] : formatTime(t, tz))}
                stroke={colors.muted}
                tick={{ fontSize: 11, fontFamily: 'var(--mono)' }}
                minTickGap={40}
              />
              <YAxis
                stroke={colors.muted}
                tick={{ fontSize: 11, fontFamily: 'var(--mono)' }}
                width={48}
                domain={domain ?? ['auto', 'auto']}
                allowDecimals={false}
              />
              <Tooltip
                labelFormatter={(t) => formatDateTime(t, tz)}
                formatter={(value, name) => [value === null ? '—' : Number(value).toFixed(1), name]}
                contentStyle={{ background: colors.card, border: `1px solid ${colors.line}`, borderRadius: 10, fontSize: 12 }}
                labelStyle={{ color: colors.text }}
              />
              {refs.map((r) => (
                <ReferenceLine
                  key={r.label}
                  y={r.y}
                  stroke={colors[r.color]}
                  strokeDasharray="4 4"
                  ifOverflow="extendDomain"
                  label={{ value: r.label, position: 'insideTopRight', fill: colors.muted, fontSize: 10 }}
                />
              ))}
              {lines.map((l) => (
                <Line
                  key={l.key}
                  dataKey={l.key}
                  name={l.label}
                  hide={hidden.has(l.key)}
                  stroke={colors[l.color]}
                  strokeWidth={l.dashed ? 1.5 : 2.5}
                  strokeDasharray={l.dashed ? '3 3' : undefined}
                  dot={false}
                  isAnimationActive={false}
                  connectNulls={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="chart-empty">No data in this range</div>
      )}
    </figure>
  );
}
