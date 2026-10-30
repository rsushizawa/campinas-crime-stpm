"""Monotonic trend tests on one unit's time series.

Method
    Mann–Kendall trend test (ties + continuity correction), optionally with the
    Hamed–Rao variance correction for serial autocorrelation; Theil–Sen slope.
Reference
    Mann, H.B. (1945). Nonparametric tests against trend. Econometrica 13.
    Kendall, M.G. (1975). Rank Correlation Methods. Griffin.
    Hamed, K.H. & Rao, A.R. (1998). A modified Mann-Kendall trend test for
    autocorrelated data. Journal of Hydrology 204.
    Sen, P.K. (1968). Estimates of the regression coefficient based on
    Kendall's tau. JASA 63.
ESRI tool mirrored
    The Mann-Kendall step of "Emerging Hot Spot Analysis" (applied there to
    each unit's Gi* z-score series).
Steps (Mann-Kendall)
    1. S = Σ sign(x_j − x_i) over i < j; 2. Var(S) with tie correction;
    3. ``hamed_rao``: inflate Var(S) by significant (5 %) lag autocorrelations
       of Sen-detrended ranks up to ``max_lag`` (inflation only — a
       project-specific conservative adaptation, not exact Esri parity);
    4. z = (S − sign S)/√Var(S), two-sided normal p.
Inputs → Outputs
    1-D series → ``(z, p)``; unit x period matrix → per-unit Theil–Sen slopes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm, rankdata

TREND_METHODS = ("classic", "hamed_rao", "legacy")


def mann_kendall(values: np.ndarray, *, method="classic", max_lag=3) -> tuple[float, float]:
    """(z, two-sided p), with ties and continuity correction.

    ``hamed_rao`` uses significant (5%) autocorrelations of Sen-detrended
    ranks through ``max_lag``. We conservatively floor the variance factor
    at one (an inflation-only Hamed--Rao adaptation, not exact Esri parity).
    Missing values return NaNs rather than silently compressing time.
    ``legacy`` is retained only for the archived regression fixture.
    """
    if method not in {"classic", "hamed_rao", "legacy"}:
        raise ValueError("method must be classic, hamed_rao or legacy")
    if not isinstance(max_lag, int) or max_lag < 1:
        raise ValueError("max_lag must be a positive integer")
    x = np.asarray(values, dtype=float)
    if x.ndim != 1:
        raise ValueError("Mann-Kendall requires a one-dimensional series")
    if not np.isfinite(x).all():
        return float("nan"), float("nan")
    n = len(x)
    s = np.sum(np.sign(x[None, :] - x[:, None])[np.triu_indices(n, k=1)])
    var = n * (n - 1) * (2 * n + 5) / 18.0
    if method != "legacy":
        counts = np.unique(x, return_counts=True)[1]
        var -= np.sum(counts * (counts - 1) * (2 * counts + 5)) / 18.0
    if var <= 0:
        return 0.0, 1.0
    if method == "hamed_rao" and n > 3:
        i, j = np.triu_indices(n, k=1)
        slope = np.median((x[j] - x[i]) / (j - i))
        ranks = rankdata(x - slope * np.arange(n))
        ranks -= ranks.mean()
        energy = ranks @ ranks
        if energy > 0:
            correction = 0.0
            cutoff = norm.ppf(0.975) / np.sqrt(n)
            for lag in range(1, min(max_lag, n - 1) + 1):
                rho = (ranks[:-lag] @ ranks[lag:]) / energy
                if abs(rho) > cutoff:
                    correction += (n-lag) * (n-lag-1) * (n-lag-2) * rho
            var *= max(1.0, 1 + 2 * correction / (n * (n-1) * (n-2)))
    z = (s - np.sign(s)) / np.sqrt(var) if s != 0 else 0.0
    p = 2 * (1 - norm.cdf(abs(z))) if method == "legacy" else 2 * norm.sf(abs(z))
    return float(z), float(p)


def trend_test(method="hamed_rao", *, max_lag: int = 3):
    """Resolve a ``trend_method`` argument to a
    :class:`~crime.core.protocols.TrendTest` ``(values) -> (z, p)``: a method
    name selects :func:`mann_kendall`; a callable is used as is."""
    if callable(method):
        return method
    return lambda values: mann_kendall(values, method=method, max_lag=max_lag)


def theil_sen_slopes(matrix: pd.DataFrame) -> pd.Series:
    """Per-row Theil–Sen slope (Sen 1968) against the bin index 0..T-1."""
    from scipy.stats import theilslopes

    x = np.arange(matrix.shape[1])
    return pd.Series([theilslopes(row, x)[0] for row in matrix.to_numpy()], index=matrix.index)
