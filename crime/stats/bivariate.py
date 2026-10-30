"""Bivariate spatial association — "is x high where y is high *nearby*?"

Method
    Global bivariate Moran's I: the slope of the standardised spatial lag of
    ``y`` on the standardised ``x``, ``I_xy = z_x' W z_y / (n - 1)``, with a
    permutation pseudo p-value (``y`` is permuted, ``x`` held fixed). The local
    form ``I_i = z_x,i (W z_y)_i`` labels each unit HH / LH / LL / HL with
    esda's conditional permutation (the other values of ``y`` are permuted
    around a fixed ``x_i``), then Benjamini–Hochberg FDR as in
    :func:`crime.esri.local.local_moran`.
Reference
    Wartenberg, D. (1985). Multivariate spatial correlation: a method for
    exploratory geographical analysis. Geographical Analysis 17(4).
    Anselin, L., Syabri, I. & Smirnov, O. (2002). Visualizing multivariate
    spatial correlation with dynamically linked windows. In Anselin & Rey
    (eds.), New Tools for Spatial Data Analysis, CSISS (UC Santa Barbara).
    Implementation: PySAL ``esda.moran.Moran_BV`` / ``Moran_Local_BV``
    (whose docstrings cite no reference).
Properties (read before interpreting)
    * Asymmetric: ``I(x, lag y) != I(y, lag x)`` in general —
      :func:`bivariate_matrix` therefore reports both ordered pairs.
    * It mixes the in-place correlation of x and y with the spatial
      autocorrelation of y: a strongly autocorrelated y makes ``W z_y`` close
      to ``z_y`` and ``I_xy`` close to Pearson's r. It is not a test of
      "spatial association beyond the plain correlation"; Lee (2001, J.
      Geographical Systems 3(4)) proposed the L statistic for that reason.
    * The permutation null is spatial randomness of y given x, not
      independence of two autocorrelated fields.
Inputs → Outputs
    Dataset + two columns → :class:`BivariateMoranResult` /
    :class:`LocalBivariateResult`; Dataset + column list → long DataFrame of
    every ordered pair (with the Spearman ρ alongside).

    from crime.stats.bivariate import bivariate_moran, local_bivariate_moran
    bv = bivariate_moran(ds, "log_pop_density", "crime_count")
    lbv = local_bivariate_moran(ds, "log_pop_density", "crime_count")
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd

from crime.core.metadata import ResultMeta, dataset_meta_of
from crime.esri.inference import benjamini_hochberg
from crime.esri.local import island_mask
from crime.esri.weights import resolve_weights, weights_tag

__all__ = ["BivariateMoranResult", "LocalBivariateResult", "bivariate_moran",
           "local_bivariate_moran", "bivariate_matrix"]

#: esda's PySAL quadrant scheme (x first, lag of y second) — same names as local_moran
_QUAD = {1: "HH", 2: "LH", 3: "LL", 4: "HL"}


def _frame(dataset, x_col: str, y_col: str) -> gpd.GeoDataFrame:
    return dataset.metric().dropna(subset=[x_col, y_col]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
#  global
# --------------------------------------------------------------------------- #
@dataclass
class BivariateMoranResult:
    I: float
    expected: float                   # mean of the permutation distribution (EI_sim)
    z_sim: float
    p_sim: float                      # esda's folded pseudo p: (min(#>=, #<) + 1) / (P + 1)
    x_col: str = ""
    y_col: str = ""
    n: int = 0
    permutations: int = 999
    sim: np.ndarray | None = field(default=None, repr=False)
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def summary(self) -> None:
        print(f"bivariate Moran's I — {self.x_col} vs lag({self.y_col}), n={self.n}: "
              f"I={self.I:.4f} (E={self.expected:.4f}), z_sim={self.z_sim:.2f}, "
              f"p_sim={self.p_sim:.4f} ({self.permutations} permutations)")


def _moran_bv(x: np.ndarray, y: np.ndarray, w, permutations: int, seed: int):
    """``esda.Moran_BV`` seeded without leaking into the caller's global RNG
    (esda draws from ``np.random`` and takes no seed)."""
    from esda.moran import Moran_BV

    state = np.random.get_state()
    np.random.seed(seed)
    try:
        return Moran_BV(x, y, w, permutations=permutations)
    finally:
        np.random.set_state(state)


def bivariate_moran(
    dataset,
    x_col: str,
    y_col: str,
    *,
    weights="queen",
    permutations: int = 999,
    seed: int = 42,
) -> BivariateMoranResult:
    """Global bivariate Moran's I of ``x_col`` against the spatial lag of
    ``y_col`` (``esda.Moran_BV``: both standardised with ddof=1, row-standardised
    weights). ``expected`` / ``z_sim`` / ``p_sim`` come from ``permutations``
    random permutations of ``y``; ``p_sim`` is esda's folded (two-tailed-style)
    pseudo p. Units with NaN in either column are dropped. Asymmetric — see the
    module docstring."""
    gdf = _frame(dataset, x_col, y_col)
    w = resolve_weights(gdf, weights)
    bv = _moran_bv(gdf[x_col].astype(float).values, gdf[y_col].astype(float).values,
                   w, permutations, seed)
    return BivariateMoranResult(
        I=float(bv.I), expected=float(bv.EI_sim), z_sim=float(bv.z_sim), p_sim=float(bv.p_sim),
        x_col=x_col, y_col=y_col, n=len(gdf), permutations=permutations, sim=np.asarray(bv.sim),
        meta=ResultMeta(
            method="bivariate Moran's I", reference="Wartenberg 1985; Anselin et al. 2002; "
                                                    "PySAL esda.Moran_BV",
            params=dict(x_col=x_col, y_col=y_col, weights=weights_tag(weights),
                        permutations=permutations, seed=seed),
            dataset=dataset_meta_of(dataset)))


def bivariate_matrix(
    dataset,
    cols: list[str],
    *,
    weights="queen",
    permutations: int = 999,
    seed: int = 42,
) -> pd.DataFrame:
    """Bivariate Moran's I for every ordered pair ``(x, y)``, ``x != y``, of
    ``cols`` on one common set of units (rows with NaN in any of ``cols``
    dropped, so every pair shares the same weights), with the Spearman ρ of the
    pair alongside. Long form: columns ``x, y, I, expected, z_sim, p_sim,
    spearman, n``."""
    gdf = dataset.metric().dropna(subset=list(cols)).reset_index(drop=True)
    w = resolve_weights(gdf, weights)
    rho = gdf[list(cols)].corr(method="spearman")
    rows = []
    for x in cols:
        for y in cols:
            if x == y:
                continue
            bv = _moran_bv(gdf[x].astype(float).values, gdf[y].astype(float).values,
                           w, permutations, seed)
            rows.append(dict(x=x, y=y, I=float(bv.I), expected=float(bv.EI_sim),
                             z_sim=float(bv.z_sim), p_sim=float(bv.p_sim),
                             spearman=float(rho.loc[x, y]), n=len(gdf)))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
#  local
# --------------------------------------------------------------------------- #
@dataclass
class LocalBivariateResult:
    gdf: gpd.GeoDataFrame = field(repr=False)
    x_col: str = ""
    y_col: str = ""
    alpha: float = 0.05
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def relabel(self, p_values: np.ndarray, alpha: float) -> None:
        self.alpha = alpha
        self.gdf["p_adjusted"] = p_values
        self.gdf["significant"] = self.gdf["p_adjusted"] < alpha
        # same zero-variance guard as LisaResult.relabel: a constant column
        # gives NaN I, which must read "no data", not a quadrant.
        self.gdf["label"] = np.select(
            [self.gdf["lisa_bv_I"].isna(), ~self.gdf["significant"]],
            ["no data", "ns"],
            default=self.gdf["quadrant"],
        )

    def summary(self) -> None:
        print(f"local bivariate Moran — {self.x_col} vs lag({self.y_col}) (alpha={self.alpha})")
        print(self.gdf["label"].value_counts().to_string())


def local_bivariate_moran(
    dataset,
    x_col: str,
    y_col: str,
    *,
    weights="queen",
    permutations: int = 499,
    alpha: float = 0.05,
    fdr: bool = True,
    seed: int = 42,
) -> LocalBivariateResult:
    """Local bivariate Moran's I (``esda.Moran_Local_BV``) with its
    conditional-permutation pseudo p-value; quadrant = (x high/low, lag of y
    high/low): HH / LH / LL / HL, "ns" when not significant. ``permutations=499``
    and ``fdr=True`` mirror :func:`crime.esri.local.local_moran` (499 is the
    ArcGIS Pro "Cluster and Outlier Analysis" default). Esri's bivariate tool,
    "Bivariate Spatial Association (Lee's L)", computes a different statistic
    and is not mirrored here; the 499 / BH choice is a project choice for
    consistency with ``local_moran``."""
    from esda.moran import Moran_Local_BV

    gdf = _frame(dataset, x_col, y_col)
    w = resolve_weights(gdf, weights)
    print(f"local bivariate Moran — {len(gdf)} units, {permutations} permutations"
          f"{' + FDR' if fdr else ''}")
    lbv = Moran_Local_BV(gdf[x_col].astype(float).values, gdf[y_col].astype(float).values, w,
                         permutations=permutations, seed=seed)
    isl = island_mask(w)                       # no neighbours: "no data", outside the BH family
    gdf["lisa_bv_I"] = np.where(isl, np.nan, lbv.Is)
    gdf["quadrant"] = [_QUAD[q] for q in lbv.q]
    gdf["p_value"] = np.where(isl, np.nan, lbv.p_sim)
    res = LocalBivariateResult(gdf=gdf, x_col=x_col, y_col=y_col, meta=ResultMeta(
        method="local bivariate Moran's I", reference="Anselin et al. 2002; PySAL esda.Moran_Local_BV",
        params=dict(x_col=x_col, y_col=y_col, weights=weights_tag(weights),
                    permutations=permutations, alpha=alpha, fdr=fdr, seed=seed),
        dataset=dataset_meta_of(dataset)))
    p_values = gdf["p_value"].to_numpy()
    res.relabel(benjamini_hochberg(p_values) if fdr else p_values, alpha)
    return res
