import { useMemo } from 'react';
import TimeSeriesChart from './TimeSeriesChart.jsx';

/** API reading points → chart rows (time as a number, wind in km/h). */
export function toChartRows(points) {
  return points.map((p) => ({
    t: Date.parse(p.ts),
    temp_bme_c: p.temp_bme_c,
    temp_dht_c: p.temp_dht_c,
    hum_bme_pct: p.hum_bme_pct,
    hum_dht_pct: p.hum_dht_pct,
    pressure_hpa: p.pressure_hpa,
    wind_kmh: p.wind_speed_ms == null ? null : p.wind_speed_ms * 3.6,
    wind_max_kmh: p.wind_max_ms == null ? null : p.wind_max_ms * 3.6,
  }));
}

/**
 * Temperature and humidity (BME280 + DHT11), pressure, and wind with the
 * Yellow/Orange/Red lines. ``show`` limits which charts appear.
 */
export default function SensorCharts({ points, settings, tz, hourly = false, multiDay = false, show }) {
  const rows = useMemo(() => toChartRows(points), [points]);
  const visible = (name) => !show || show.includes(name);
  const wind = settings?.wind_kmh;
  const heatLine = settings?.heat?.abs_threshold_c;

  return (
    <div className="charts">
      {visible('temperature') && (
        <TimeSeriesChart
          title="Temperature"
          unit={heatLine ? `°C · ${heatLine} °C line` : '°C'}
          data={rows}
          tz={tz}
          multiDay={multiDay}
          lines={[
            { key: 'temp_bme_c', label: 'BME280', color: 'orange' },
            { key: 'temp_dht_c', label: 'DHT11', color: 'chart-dht', dashed: true },
          ]}
          refs={heatLine ? [{ y: heatLine, label: `${heatLine} °C`, color: 'orange' }] : []}
        />
      )}
      {visible('humidity') && (
        <TimeSeriesChart
          title="Humidity"
          unit="%"
          data={rows}
          tz={tz}
          multiDay={multiDay}
          domain={[0, 100]}
          lines={[
            { key: 'hum_bme_pct', label: 'BME280', color: 'chart-humidity' },
            { key: 'hum_dht_pct', label: 'DHT11', color: 'chart-dht', dashed: true },
          ]}
        />
      )}
      {visible('pressure') && (
        <TimeSeriesChart
          title="Pressure"
          unit="hPa"
          data={rows}
          tz={tz}
          multiDay={multiDay}
          lines={[{ key: 'pressure_hpa', label: 'Pressure', color: 'chart-pressure' }]}
        />
      )}
      {visible('wind') && (
        <TimeSeriesChart
          title="Wind"
          unit="km/h"
          data={rows}
          tz={tz}
          multiDay={multiDay}
          lines={[
            { key: 'wind_kmh', label: hourly ? 'Hourly mean' : 'Speed', color: 'chart-wind' },
            ...(hourly ? [{ key: 'wind_max_kmh', label: 'Hourly peak', color: 'yellow', dashed: true }] : []),
          ]}
          refs={
            wind
              ? [
                  { y: wind.yellow, label: `Yellow ${wind.yellow}`, color: 'yellow' },
                  { y: wind.orange, label: `Orange ${wind.orange}`, color: 'orange' },
                  { y: wind.red, label: `Red ${wind.red}`, color: 'red' },
                ]
              : []
          }
        />
      )}
    </div>
  );
}
