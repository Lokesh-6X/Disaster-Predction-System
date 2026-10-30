import { describe, expect, it } from 'vitest';
import {
  fixed,
  formatAgo,
  formatClock,
  formatDateTime,
  formatIn,
  formatTime,
  headlineProbability,
  kmh,
  outcomeText,
  percent,
} from './format.js';

const T = '2026-10-31T08:53:00Z'; // 14:23 IST

describe('time formatting in IST', () => {
  it('converts UTC to IST', () => {
    expect(formatTime(T)).toBe('14:23');
    expect(formatDateTime(T)).toBe('31 Oct · 14:23');
  });

  it('builds the header clock', () => {
    expect(formatClock(T)).toBe('SAT 31 OCT · 14:23 IST');
  });

  it('handles missing values', () => {
    expect(formatTime(null)).toBe('—');
    expect(formatAgo(null)).toBe('never');
  });
});

describe('relative times', () => {
  const now = new Date(T).getTime();
  it('formats the past', () => {
    expect(formatAgo('2026-10-31T08:52:18Z', now)).toBe('42 s ago');
    expect(formatAgo('2026-10-31T08:40:00Z', now)).toBe('13 min ago');
    expect(formatAgo('2026-10-31T05:53:00Z', now)).toBe('3 h ago');
  });

  it('formats the future', () => {
    expect(formatIn('2026-10-31T09:30:30Z', now)).toBe('in 38 min');
    expect(formatIn('2026-10-31T10:30:00Z', now)).toBe('in 1 h 37 min');
    expect(formatIn('2026-10-31T08:00:00Z', now)).toBe('now');
  });
});

describe('units and numbers', () => {
  it('converts m/s to km/h', () => {
    expect(kmh(10)).toBe(36);
    expect(kmh(null)).toBeNull();
  });

  it('formats numbers and percentages', () => {
    expect(fixed(38.44)).toBe('38.4');
    expect(fixed(null)).toBe('—');
    expect(percent(0.678)).toBe('68%');
  });
});

describe('levels', () => {
  it('shows the current level probability, or yellow when green', () => {
    const p = { yellow: 0.3, orange: 0.1, red: 0.0 };
    expect(headlineProbability({ level: 'green', p })).toBe(0.3);
    expect(headlineProbability({ level: 'orange', p: { ...p, orange: 0.6 } })).toBe(0.6);
    expect(headlineProbability({ level: null, p: null })).toBeNull();
  });

  it('describes alert outcomes', () => {
    expect(outcomeText({ status: 'pending', window_end: '2026-10-31T11:30:00Z' })).toBe(
      'Pending (window ends 17:00)',
    );
    expect(outcomeText({ status: 'happened', peak_wind_kmh: 58 })).toBe('Happened · peak wind 58 km/h');
    expect(outcomeText({ status: 'did_not_happen', tmax_c: 38.2 })).toBe('Did not happen · max 38.2 °C');
  });
});
