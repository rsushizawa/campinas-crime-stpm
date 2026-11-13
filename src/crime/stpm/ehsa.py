"""Space-time Gi*, Mann–Kendall and the notebook's ordered EHSA rules."""
from dataclasses import dataclass

import esda
import libpysal
import numpy as np
import pandas as pd
import pymannkendall as mk
import scipy.sparse as sp
from scipy import stats
from statsmodels.stats.multitest import multipletests

from crime.errors import ConfigurationError

CATEGORIES = [f"{p} {side} spot" for side in ("hot", "cold")
              for p in ("new", "consecutive", "intensifying", "persistent",
                        "diminishing", "sporadic", "oscillating", "historical")] + ["no pattern detected", "trend unavailable"]


def space_time_weights(w_spatial, n_times, k=1):
    # Space-time W (node t*n+i): queen nbrs at t; queen nbrs and self at t-1..t-k. Binary.
    A = w_spatial.sparse.copy().tocsr()
    A.data[:] = 1.0
    n = A.shape[0]
    I_n = sp.identity(n, format="csr")
    Wst = sp.kron(sp.identity(n_times), A)
    for lag in range(1, k + 1):
        L = sp.eye(n_times, k=-lag, format="csr")     # L[t, t-lag] = 1
        Wst = Wst + sp.kron(L, A + I_n)
    Wst = sp.csr_matrix(Wst)
    return libpysal.weights.WSP(Wst).to_W(silence_warnings=True)



def gi_star_cube(Y, w, k=1, spatial_only=False):
    # Return z, p (two-sided) as (n_units, n_times) arrays.
    if Y.ndim != 2 or Y.shape[0] != w.n:
        raise ConfigurationError("Gi* cube must have one row per spatial weight ID")
    n, T = Y.shape
    if spatial_only:
        wst = space_time_weights(w, T, k=0)
        g = esda.G_Local(Y.T.reshape(-1).astype(float), wst, transform="B", star=True, permutations=0)
        Z = g.Zs.reshape(T, n).T
    else:
        wst = space_time_weights(w, T, k)
        y = Y.T.reshape(-1).astype(float)          # node t*n+i
        g = esda.G_Local(y, wst, transform="B", star=True, permutations=0)
        Z = g.Zs.reshape(T, n).T
    P = 2 * stats.norm.sf(np.abs(Z))
    return Z, P



def mann_kendall(Z, alpha=0.05, hamed_rao=False):
    f = mk.hamed_rao_modification_test if hamed_rao else mk.original_test
    rows = []
    for z in Z:
        # Undefined Gi* (e.g. a constant cube) leaves no observations for MK.
        # pymannkendall raises on this empty sample; retain undefined statistics.
        if np.isnan(z).all():
            rows.append((np.nan, np.nan, np.nan, np.nan))
        else:
            r = f(z, alpha=alpha)
            rows.append((r.s, r.Tau, r.z, r.p))
    return pd.DataFrame(rows, columns=["mk_s", "mk_tau", "mk_z", "mk_p"])


def esri_category(hot, cold, mk_s, mk_p, alpha=0.05, frac=0.9):
    # hot, cold: boolean arrays over the T bins (significant hot / cold bins) of one unit
    T = len(hot)
    if not np.isfinite(mk_p):
        return "trend unavailable"
    trend_up = (mk_p < alpha) and (mk_s > 0)      # Gi* z rising
    trend_dn = (mk_p < alpha) and (mk_s < 0)      # Gi* z falling
    sides = (("hot", hot, cold, trend_up, trend_dn),     # (name, this side, other side,
             ("cold", cold, hot, trend_dn, trend_up))    #  intensifying, diminishing)
    # rule 1: >= 90 % of the bins on one side
    for name, this, other, intens, dimin in sides:
        if this.sum() >= frac * T:
            if not this[-1]:
                return f"historical {name} spot"
            if intens:
                return f"intensifying {name} spot"
            if dimin:
                return f"diminishing {name} spot"
            return f"persistent {name} spot"
    # rule 2: significant final bin, < 90 % of the bins on that side
    for name, this, other, intens, dimin in sides:
        if this[-1]:
            if other[:-1].any():
                return f"oscillating {name} spot"
            n_this = int(this.sum())
            if n_this == 1:
                return f"new {name} spot"
            run = len(this) - np.flatnonzero(~this)[-1] - 1 if (~this).any() else len(this)
            if run >= 2 and run == n_this:
                return f"consecutive {name} spot"
            return f"sporadic {name} spot"
    return "no pattern detected"



def classify(Z, P, mkdf, alpha=0.05, frac=0.9):
    hot = (P < alpha) & (Z > 0)
    cold = (P < alpha) & (Z < 0)
    return [esri_category(hot[i], cold[i], mkdf.mk_s[i], mkdf.mk_p[i], alpha, frac) for i in range(len(Z))], hot, cold



def hot_cold(df, col="category"):
    c = df[col]
    return int(c.str.contains("hot").sum()), int(c.str.contains("cold").sum())



def counts_table(labels, col="category"):
    rows = {}
    for key, df in labels.items():
        if col in df:
            rows[key] = df[col].value_counts()
    t = pd.DataFrame(rows).reindex(CATEGORIES).fillna(0).astype(int)
    t.columns = [f"{f}/{s}/{g}" for f, s, g in t.columns]
    t = t.loc[(t.sum(1) > 0) | (t.index == "no pattern detected")]
    return t



@dataclass(frozen=True)
class EHSAResult:
    labels: pd.DataFrame
    bins: pd.DataFrame | None


def analyze_cube(Y, w, *, quarterly=True, k=1, alpha=0.05, frac=0.9):
    """Analyze a unit-by-period DataFrame; BH covers all bins in this run.

    Quarterly runs also return the original 0.01, Hamed–Rao and purely
    spatial sensitivity analyses. Non-finite trend p-values remain unavailable.
    Y row IDs must exactly match w.id_order, including their order.
    """
    if list(Y.index) != list(w.id_order):
        raise ConfigurationError("EHSA cube row IDs must match spatial weights id_order exactly")
    periods = list(Y.columns)
    Yv = Y.to_numpy()
    Z, P = gi_star_cube(Yv, w, k=k)
    m = mann_kendall(Z, alpha=alpha)
    cat, hot, cold = classify(Z, P, m, alpha=alpha, frac=frac)
    df = pd.DataFrame({"unit_id": Y.index, "category": cat,
                       "n_hot_bins": hot.sum(1), "n_cold_bins": cold.sum(1)}).join(m)
    P_bh = multipletests(P.ravel(), method="fdr_bh")[1].reshape(P.shape)
    df["category_fdr"], *_ = classify(Z, P_bh, m, alpha=alpha, frac=frac)
    long = None
    if quarterly:
        m01 = mann_kendall(Z, alpha=0.01)
        df["category_a01"], *_ = classify(Z, P, m01, alpha=0.01, frac=frac)
        with np.errstate(invalid="ignore"):
            m_hr = mann_kendall(Z, alpha=alpha, hamed_rao=True)
        df["mk_p_hamed_rao"] = m_hr.mk_p
        df["category_hamed_rao"], *_ = classify(Z, P, m_hr, alpha=alpha, frac=frac)
        Zs, Ps = gi_star_cube(Yv, w, k=k, spatial_only=True)
        m_sp = mann_kendall(Zs, alpha=alpha)
        df["category_spatial"], *_ = classify(Zs, Ps, m_sp, alpha=alpha, frac=frac)
        long = pd.DataFrame({"unit_id": np.repeat(Y.index.values, len(periods)),
                             "period": np.tile(periods, len(Y)),
                             "z": Z.ravel(), "p": P.ravel(), "p_bh": P_bh.ravel(),
                             "z_spatial": Zs.ravel(), "p_spatial": Ps.ravel()})
    return EHSAResult(df, long)
