"""Local Gi* and LISA, including BH families and permutation-floor diagnostics."""
from dataclasses import dataclass

import esda
import numpy as np
import pandas as pd
from libpysal.weights import W
from scipy.stats import norm
from statsmodels.stats.multitest import multipletests

QUAD = {1: "HH", 2: "LH", 3: "LL", 4: "HL"}


@dataclass(frozen=True)
class HotspotResult:
    summary: dict
    labels: pd.DataFrame


def local_hotspots(counts, weights, *, support="tract", group="all", kind="queen",
                   alpha=0.05, permutations=499, seed=20221):
    """Compute Gi*/LISA labels after applying the supplied island keep mask."""
    s, g, k = support, group, kind
    w, mask, isl = weights
    y = np.asarray(counts, dtype=float)[mask]
    n = len(y)
    # all-zero neighbourhood: own count 0 and every neighbour 0
    nb_sum = np.array([y[[w.id2i[j] for j in w.neighbors[i]]].sum() for i in w.id_order])
    allzero = (y == 0) & (nb_sum == 0)
    # Gi*: binary weights + self-weight 1, analytic z, two-sided p, BH
    wb = W(w.neighbors, id_order=w.id_order, silence_warnings=True)
    gi = esda.G_Local(y, wb, transform="B", star=True, permutations=0)
    z = np.asarray(gi.Zs)
    p_gi = 2 * norm.sf(np.abs(z))
    q_gi = multipletests(p_gi, alpha=alpha, method="fdr_bh")[1]
    # LISA: row-standardised weights, 499 conditional permutations, BH on the folded pseudo p
    wr = W(w.neighbors, id_order=w.id_order, silence_warnings=True); wr.transform = "r"
    li = esda.Moran_Local(y, wr, transformation="r", permutations=permutations, seed=seed, keep_simulations=False)
    p_li = li.p_sim
    q_li = multipletests(p_li, alpha=alpha, method="fdr_bh")[1]
    quad = np.vectorize(QUAD.get)(li.q)
    def gilab(pv):
        return np.where(pv <= alpha, np.where(z > 0, "hot", "cold"), "ns")
    def lilab(pv):
        return np.where(pv <= alpha, quad, "ns")
    def giconf(pv):   # Esri-style confidence bins of the (raw or BH-adjusted) two-sided p
        lvl = np.select([pv <= 0.01, pv <= 0.05, pv <= 0.10], ["99%", "95%", "90%"], "")
        return np.where(lvl != "", np.where(z > 0, "hot spot ", "cold spot ") + lvl, "ns")
    lab = pd.DataFrame({"unit_id": w.id_order, "count": y, "gi_z": z, "gi_p2": p_gi, "gi_q_bh": q_gi,
                        "gi_raw": gilab(p_gi), "gi_fdr": gilab(q_gi),
                        "gi_conf_raw": giconf(p_gi), "gi_conf_fdr": giconf(q_gi), "lisa_I": li.Is, "lisa_p": p_li,
                        "lisa_q_bh": q_li, "lisa_quadrant": quad, "lisa_raw": lilab(p_li), "lisa_fdr": lilab(q_li),
                        "allzero_neighbourhood": allzero})
    floor = 1 / (permutations + 1)
    row = dict(support=s, group=g, weights=k, n=n, n_islands=len(isl), events=int(y.sum()),
               n_allzero_neighbourhood=int(allzero.sum()))
    for c in ("hot", "cold"):
        row[f"gi_{c}_raw"] = int((lab.gi_raw == c).sum()); row[f"gi_{c}_fdr"] = int((lab.gi_fdr == c).sum())
    row["gi_cold_fdr_allzero"] = int(((lab.gi_fdr == "cold") & allzero).sum())
    for c in ("HH", "LL", "HL", "LH"):
        row[f"lisa_{c}_raw"] = int((lab.lisa_raw == c).sum()); row[f"lisa_{c}_fdr"] = int((lab.lisa_fdr == c).sum())
    row["lisa_LL_raw_allzero"] = int(((lab.lisa_raw == "LL") & allzero).sum())
    row["lisa_LL_fdr_allzero"] = int(((lab.lisa_fdr == "LL") & allzero).sum())
    row["lisa_min_p"] = p_li.min()
    row["lisa_n_at_floor"] = int(np.isclose(p_li, floor).sum())
    row["lisa_floor_units_needed_for_bh"] = int(np.ceil(floor * n / alpha))
    return HotspotResult(row, lab)

