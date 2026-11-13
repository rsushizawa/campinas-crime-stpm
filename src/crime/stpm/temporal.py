"""Monthly STL decomposition, strength, robustness and Mann–Kendall tables."""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pymannkendall as mk
from statsmodels.tsa.seasonal import STL


@dataclass(frozen=True)
class TemporalResult:
    fits: dict
    components: pd.DataFrame


def strengths(r):
    vR = np.var(r.resid, ddof=1)
    return (max(0.0, 1 - vR / np.var(r.trend + r.resid, ddof=1)),
            max(0.0, 1 - vR / np.var(r.seasonal + r.resid, ddof=1)))



def fit_stl(series, period=12, robust=True):
    fits = {}
    for kind, df in series.items():
        for g in df.columns:
            fits[(kind, g)] = STL(df[g].astype(float), period=period, robust=robust).fit()

    comp = pd.concat({f"{k}|{g}": pd.DataFrame({"observed": r.observed, "trend": r.trend, "seasonal": r.seasonal,
                                                "resid": r.resid, "robust_weight": r.weights})
                      for (k, g), r in fits.items()}, axis=1)
    return TemporalResult(fits, comp)


def summarize_stl(fits):
    rows = []
    for (kind, g), r in fits.items():
        ft, fs = strengths(r)
        s_mean = r.seasonal.groupby(r.seasonal.index.month).mean()
        rows.append({"series": kind, "group": g, "mean_per_month": r.observed.mean(),
                     "trend_strength_FT": ft, "seasonal_strength_FS": fs,
                     "seasonal_amplitude": r.seasonal.max() - r.seasonal.min(),
                     "seasonal_peak_month": int(s_mean.idxmax()), "seasonal_trough_month": int(s_mean.idxmin()),
                     "trend_first": r.trend.iloc[0], "trend_last": r.trend.iloc[-1],
                     "trend_change_%": 100 * (r.trend.iloc[-1] / r.trend.iloc[0] - 1),
                     "months_robust_weight_lt_0.5": int((r.weights < 0.5).sum())})
    strength = pd.DataFrame(rows)
    return strength


def robust_sensitivity(series, fits, period=12):
    """Return sensitivity table and add nonrobust fits to the supplied fit mapping."""
    rows = []
    for (kind, g), r in list(fits.items()):
        r0 = STL(series[kind][g].astype(float), period=period, robust=False).fit()
        ft, fs = strengths(r)
        ft0, fs0 = strengths(r0)
        rows.append({"series": kind, "group": g,
                     "robust_months_|R|<1": int((r.resid.abs() < 1).sum()),
                     "robust_months_weight<0.5": int((r.weights < 0.5).sum()),
                     "nonrobust_months_|R|<1": int((r0.resid.abs() < 1).sum()),
                     "FT_robust": ft, "FT_nonrobust": ft0, "FS_robust": fs, "FS_nonrobust": fs0,
                     "trend_change_%_robust": 100 * (r.trend.iloc[-1] / r.trend.iloc[0] - 1),
                     "trend_change_%_nonrobust": 100 * (r0.trend.iloc[-1] / r0.trend.iloc[0] - 1)})
        fits[(kind + "_nonrobust", g)] = r0
    sens = pd.DataFrame(rows)
    return sens


def mann_kendall_table(series, period=12, alpha=0.05):
    rows = []
    for kind, df in series.items():
        for g in df.columns:
            y = df[g].to_numpy(dtype=float)
            o = mk.original_test(y, alpha=alpha)
            h = mk.hamed_rao_modification_test(y, alpha=alpha)
            sz = mk.seasonal_test(y, period=period, alpha=alpha)
            rows.append({"series": kind, "group": g,
                         "mk_trend": o.trend, "mk_tau": o.Tau, "mk_z": o.z, "mk_p": o.p,
                         "sen_slope_per_month": o.slope, "sen_slope_per_year": 12 * o.slope,
                         "sen_slope_%_of_mean_per_year": 100 * 12 * o.slope / y.mean(),
                         "hamed_rao_z": h.z, "hamed_rao_p": h.p, "hamed_rao_trend": h.trend,
                         "seasonal_mk_z": sz.z, "seasonal_mk_p": sz.p, "seasonal_mk_trend": sz.trend,
                         "seasonal_sen_slope_per_year": sz.slope})
    mkt = pd.DataFrame(rows)
    return mkt
