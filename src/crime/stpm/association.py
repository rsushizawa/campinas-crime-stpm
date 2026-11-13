"""Feature association with the notebook's scaling, missingness and BH policies."""
from dataclasses import dataclass

import esda
import numpy as np
import pandas as pd
from libpysal.weights import W, w_subset
from scipy.stats import spearmanr
from statsmodels.stats.multitest import multipletests

QUAD = {1: "HH", 2: "LH", 3: "LL", 4: "HL"}
POI = ["n_commercial", "n_education", "n_health", "n_religious"]
EXTENSIVE = POI + ["population"]
INTENSIVE = ["income_head_mean", "literacy_rate"]


def pairs(s, extensive=EXTENSIVE, intensive=INTENSIVE):
    for f in list(extensive) + (list(intensive) if s == "tract" else []):
        yield f, "count"
        if f in extensive:
            yield f, "per_km2"


def xy(crime, features, feature, scale):
    """Pairwise nonmissing values; per-km² scales both crime and feature."""
    y, x = crime, features[feature]
    if scale == "per_km2":
        a = features["area_km2"]
        y, x = y / a, x / a
    ok = x.notna() & y.notna()
    return x[ok], y[ok]


def w_for(wq, keep_ids):
    if len(keep_ids) == wq.n:
        w = W(wq.neighbors, id_order=wq.id_order, silence_warnings=True)
    else:
        w = w_subset(wq, list(keep_ids), silence_warnings=True)
    w.transform = "r"
    return w


def spearman_table(crime, features, supports=("tract",), groups=("all",),
                   periods=("2022-2025", "2022")):
    rows = []
    for s in supports:
        for g in groups:
            for period in periods:
                for f, scale in pairs(s):
                    x, y = xy(crime[s, g, period], features[s], f, scale)
                    r = spearmanr(x, y)
                    rows.append(dict(support=s, group=g, period=period, feature=f,
                                     scale=scale, n=len(x), rho=r.statistic, p=r.pvalue))
    return pd.DataFrame(rows)


def bivariate_moran_table(crime, features, weights, supports=("tract",), groups=("all",),
                          period="2022-2025", permutations=999, seed=20221):
    rows = []
    for s in supports:
        for g in groups:
            for f, scale in pairs(s):
                x, y = xy(crime[s, g, period], features[s], f, scale)
                w = w_for(weights[s], x.index)
                for order, (a, b) in {"feature x lag(crime)": (x, y), "crime x lag(feature)": (y, x)}.items():
                    np.random.seed(seed)
                    bv = esda.Moran_BV(a.to_numpy(), b.to_numpy(), w, permutations=permutations)
                    rows.append(dict(support=s, group=g, feature=f, scale=scale, order=order,
                                     n=len(x), I_bv=bv.I, z_sim=bv.z_sim, p_sim=bv.p_sim))
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class LocalAssociationResult:
    summary: dict
    labels: pd.DataFrame


def local_bivariate(x, y, w, *, scale="count", permutations=499, seed=20221, alpha=0.05):
    """Crime x lag(feature), with BH across this scale's local tests."""
    lbv = esda.Moran_Local_BV(y.to_numpy(), x.to_numpy(), w, permutations=permutations,
                            seed=seed, keep_simulations=False)
    q = multipletests(lbv.p_sim, alpha=alpha, method="fdr_bh")[1]
    quad = np.vectorize(QUAD.get)(lbv.q)
    raw = np.where(lbv.p_sim <= alpha, quad, "ns")
    fdr = np.where(q <= alpha, quad, "ns")
    labels = pd.DataFrame({"unit_id": y.index, "Ii": lbv.Is, "p_sim": lbv.p_sim,
                           "q_bh": q, "raw": raw, "fdr": fdr})
    r = dict(scale=scale, n=len(y), min_p=lbv.p_sim.min(),
             n_at_floor=int(np.isclose(lbv.p_sim, 1 / (permutations + 1)).sum()),
             floor_units_needed_for_bh=int(np.ceil(len(y) / 25)))
    for c in ("HH", "LL", "HL", "LH"):
        r[f"{c}_raw"] = int((raw == c).sum())
        r[f"{c}_fdr"] = int((fdr == c).sum())
    nb0 = np.array([x.loc[w.neighbors[i]].sum() == 0 for i in w.id_order])
    allzero = (y.to_numpy() == 0) & nb0
    r["LL_raw_allzero"] = int(((raw == "LL") & allzero).sum())
    r["LL_fdr_allzero"] = int(((fdr == "LL") & allzero).sum())
    return LocalAssociationResult(r, labels)
