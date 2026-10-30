"""Daily climate normals interpolated from monthly normals (design §7.1).

Each monthly value is placed at mid-month and joined with a periodic cubic
spline, so values change smoothly through the year and wrap from Dec to Jan.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.interpolate import CubicSpline

DAYS_IN_MONTH = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
YEAR_DAYS = 365
# Day of year (1-based, fractional) at the middle of each month
MID_MONTH_DOY = np.cumsum(DAYS_IN_MONTH) - DAYS_IN_MONTH / 2 + 0.5


def daily_from_monthly(monthly: Sequence[float]) -> np.ndarray:
    """366 daily values; index ``doy - 1`` (day 366 repeats the end of the year)."""
    values = np.asarray(monthly, dtype=float)
    if values.shape != (12,):
        raise ValueError("need 12 monthly values")
    x = np.append(MID_MONTH_DOY, MID_MONTH_DOY[0] + YEAR_DAYS)
    y = np.append(values, values[0])
    spline = CubicSpline(x, y, bc_type="periodic")
    doy = np.arange(1, 367, dtype=float)
    wrapped = (doy - x[0]) % YEAR_DAYS + x[0]
    return spline(wrapped)


class DailyNormals:
    """Daily normals for every day of the year, from the ``normals`` section of site.yaml."""

    def __init__(self, normals) -> None:
        self.tmax_c = daily_from_monthly(normals.tmax_c)
        self.tmin_c = daily_from_monthly(normals.tmin_c)
        self.rh_morning_pct = daily_from_monthly(normals.rh_morning_pct)
        self.rh_evening_pct = daily_from_monthly(normals.rh_evening_pct)
        self.wind_kmh = daily_from_monthly(normals.wind_kmh)
        self.mslp_hpa = daily_from_monthly(normals.mslp_hpa)

    @staticmethod
    def _index(doy) -> np.ndarray:
        return np.asarray(doy, dtype=int) - 1

    def tmax_for(self, doy) -> np.ndarray:
        """Normal daily maximum temperature for day(s) of year (1..366)."""
        return self.tmax_c[self._index(doy)]
