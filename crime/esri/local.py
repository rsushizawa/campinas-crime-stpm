"""Local spatial statistics — "where are the clusters?"

Method
    Getis-Ord Gi* hot/cold spots and Anselin's Local Moran's I (LISA), each
    with a permutation (or analytic) p-value and optional Benjamini–Hochberg
    FDR control (:mod:`crime.esri.inference`).
Reference
    Getis, A. & Ord, J.K. (1992). The analysis of spatial association by use of
    distance statistics. Geographical Analysis 24(3).
    Ord, J.K. & Getis, A. (1995). Local spatial autocorrelation statistics:
    distributional issues and an application. Geographical Analysis 27(4).
    Anselin, L. (1995). Local indicators of spatial association — LISA.
    Geographical Analysis 27(2).
    Implementation: PySAL ``esda.getisord.G_Local`` / ``esda.moran.Moran_Local``.
ESRI tool mirrored
    "Hot Spot Analysis (Getis-Ord Gi*)" and "Cluster and Outlier Analysis
    (Anselin Local Moran's I)"; ``gi_confidence_bin`` reproduces ArcGIS's
    ``Gi_Bin`` 90/95/99 % confidence classes.
Steps
    1. drop units with NaN in ``value_col``; 2. resolve weights; 3. compute
    the local statistic + p-values; 4. adjust p (FDR) and label each unit
    ("hotspot"/"coldspot" or HH/LH/LL/HL, "ns", "no data").
Inputs → Outputs
    Dataset + weights → :class:`GiStarResult` / :class:`LisaResult` whose
    ``gdf`` carries the per-unit statistic, p-values and label.

Every function takes a Dataset and ``weights`` as either a kind string
("queen"/"rook"/"knn"/"network"), a pre-built libpysal ``W``, or a builder
callable. Call ``.summary()`` on a result to print a breakdown.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np

from crime.core.metadata import ResultMeta, dataset_meta_of
from crime.esri.inference import benjamini_hochberg
from crime.esri.permutation import local_moran_counts, pseudo_p, tail_counts
from crime.esri.weights import resolve_weights, weights_tag

_QUAD = {1: "HH", 2: "LH", 3: "LL", 4: "HL"}


# --------------------------------------------------------------------------- #
#  Local Moran's I (LISA)
# --------------------------------------------------------------------------- #
@dataclass
class LisaResult:
    gdf: gpd.GeoDataFrame = field(repr=False)
    value_col: str = "crime_count"
    alpha: float = 0.05
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def relabel(self, p_values: np.ndarray, alpha: float) -> None:
        self.alpha = alpha
        self.gdf["p_adjusted"] = p_values
        self.gdf["significant"] = self.gdf["p_adjusted"] < alpha
        # A zero-variance value_col (e.g. a crime slug with 0% sector
        # geocoding, so crime_count is identically 0 everywhere) makes
        # Moran_Local's I NaN (division by a zero variance) while esda's
        # permutation p-value can still floor near 0 -- spuriously
        # "significant". NaN compared against anything is False, so without
        # this guard every such unit silently mislabels as the default
        # quadrant instead of "no data". Checked directly against
        # estupro_vulneravel (100% missing cd_setor): before this guard,
        # relabel produced "LL" for all 2,592 units.
        self.gdf["label"] = np.select(
            [self.gdf["lisa_I"].isna(), ~self.gdf["significant"]],
            ["no data", "ns"],
            default=self.gdf["quadrant"],
        )

    def summary(self) -> None:
        print(f"LISA — {self.value_col} (alpha={self.alpha})")
        print(self.gdf["label"].value_counts().to_string())


def local_moran(
    dataset,
    *,
    value_col: str = "crime_count",
    weights="queen",
    permutations: int = 9999,
    alpha: float = 0.05,
    fdr: bool = True,
    seed: int = 42,
    tie_rule: str = "esda",
) -> LisaResult:
    """``fdr=True`` (default) labels on Benjamini-Hochberg adjusted p-values —
    the right call when scanning many units. ``fdr=False`` uses raw p.
    ``tie_rule`` other than ``"esda"`` replaces esda's pseudo p with
    :func:`crime.esri.permutation.pseudo_p` (see that module for why)."""
    from esda.moran import Moran_Local

    gdf = dataset.metric().dropna(subset=[value_col]).reset_index(drop=True)
    w = resolve_weights(gdf, weights)
    print(f"LISA — {len(gdf)} units, {permutations} permutations{' + FDR' if fdr else ''}")
    lisa = Moran_Local(
        gdf[value_col].astype(float).values, w, permutations=permutations, seed=seed
    )
    gdf["lisa_I"] = lisa.Is
    gdf["quadrant"] = [_QUAD[q] for q in lisa.q]
    if permutations and tie_rule != "esda":
        x = gdf[value_col].astype(float).values
        gt, eq, lt = local_moran_counts(x, w, permutations, seed=seed)
        gdf["p_value"] = pseudo_p(gt, eq, lt, permutations, tie_rule, local_sum=w.sparse @ x + x)
    else:
        gdf["p_value"] = lisa.p_sim
    res = LisaResult(gdf=gdf, value_col=value_col, meta=ResultMeta(
        method="Local Moran's I (LISA)", reference="Anselin 1995; PySAL esda.Moran_Local",
        params=dict(value_col=value_col, weights=weights_tag(weights), permutations=permutations,
                    alpha=alpha, fdr=fdr, seed=seed, tie_rule=tie_rule),
        dataset=dataset_meta_of(dataset),
    ))
    p_values = gdf["p_value"].to_numpy()
    res.relabel(benjamini_hochberg(p_values) if fdr else p_values, alpha)
    return res


# --------------------------------------------------------------------------- #
#  Getis-Ord Gi*
# --------------------------------------------------------------------------- #
def gi_star_weights(y, w, *, transform: str = "R"):
    """The final Gi* weights esda builds (csr, self-weight on the diagonal)."""
    import warnings

    from esda.getisord import G_Local

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)    # esda's row-max self-weight notice
        return G_Local(np.asarray(y, dtype=float), w, transform=transform, star=True,
                       permutations=0).w.sparse.tocsr()


def gi_star_pseudo_p(y, w, permutations: int, seed: int, tie_rule: str) -> np.ndarray:
    """Gi* pseudo p under a :data:`crime.esri.permutation.TIE_RULES` rule."""
    x = np.asarray(y, dtype=float)
    W = gi_star_weights(x, w)
    gt, eq, lt = tail_counts(x, W, permutations, seed=seed)
    return pseudo_p(gt, eq, lt, permutations, tie_rule, local_sum=W @ x)


def gi_star_z(y, w, *, transform: str = "R") -> tuple[np.ndarray, np.ndarray]:
    """Gi* z-scores and analytic p-values for **general** weights.

    esda 2.6.0's ``G_Local.Zs`` uses the Getis & Ord (1992) variance, which is
    exact only for binary weights; with row-standardised weights it ignores
    how many cells are averaged and shrinks z (~0.3-0.5x on queen tracts).
    This applies the Ord & Getis (1995) form to the final weights esda builds
    for Gi* (self-weight included)::

        z_i = (sum_j w_ij x_j - xbar W_i) / (s sqrt((N S2_i - W_i^2) / (N - 1)))

    with ``W_i = sum_j w_ij``, ``S2_i = sum_j w_ij^2``, ``s^2 = mean(x^2) - xbar^2``.
    Identical to esda for binary weights. ``p`` keeps esda's ``p_norm``
    convention (``norm.sf(|z|)``). Permutation p-values are unaffected.

    The weights come from a permutation-free ``G_Local``: with
    ``permutations > 0`` esda zeroes the diagonal of ``gi.w`` while simulating,
    so a permuted result's ``w`` no longer holds the Gi* weights.
    """
    from scipy.stats import norm

    x = np.asarray(y, dtype=float)
    W = gi_star_weights(x, w, transform=transform)
    N = len(x)
    xbar = x.mean()
    s = np.sqrt((x ** 2).mean() - xbar ** 2)
    W1 = np.asarray(W.sum(axis=1)).ravel()
    S2 = np.asarray(W.multiply(W).sum(axis=1)).ravel()
    z = (W @ x - xbar * W1) / (s * np.sqrt((N * S2 - W1 ** 2) / (N - 1)))
    return z, norm.sf(np.abs(z))


@dataclass
class GiStarResult:
    gdf: gpd.GeoDataFrame = field(repr=False)
    value_col: str = "crime_count"
    alpha: float = 0.05
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def relabel(self, p_values: np.ndarray, alpha: float) -> None:
        self.alpha = alpha
        self.gdf["p_adjusted"] = p_values
        self.gdf["significant"] = self.gdf["p_adjusted"] < alpha
        # Same zero-variance guard as LisaResult.relabel (see its comment):
        # a zero-variance value_col makes G_Local's Zs NaN while the
        # permutation p-value can still floor near 0, so without this check
        # `NaN > 0` (False) silently mislabels every such unit "coldspot".
        self.gdf["label"] = np.select(
            [self.gdf["gi_z"].isna(), ~self.gdf["significant"], self.gdf["gi_z"] > 0],
            ["no data", "ns", "hotspot"],
            default="coldspot",
        )

    def summary(self) -> None:
        print(f"Getis-Ord Gi* — {self.value_col} (alpha={self.alpha})")
        print(self.gdf["label"].value_counts().to_string())


def getis_ord_gi(
    dataset,
    *,
    value_col: str = "crime_count",
    weights="queen",
    permutations: int = 9999,
    alpha: float = 0.05,
    fdr: bool = True,
    seed: int = 42,
    tie_rule: str = "esda",
) -> GiStarResult:
    """``fdr=True`` (default) labels on Benjamini-Hochberg adjusted p-values —
    the right call when scanning many units. ``fdr=False`` uses raw p.
    ``tie_rule`` other than ``"esda"`` replaces esda's pseudo p with
    :func:`crime.esri.permutation.pseudo_p` (see that module for why)."""
    from esda.getisord import G_Local

    np.random.seed(seed)
    gdf = dataset.metric().dropna(subset=[value_col]).reset_index(drop=True)
    w = resolve_weights(gdf, weights)
    print(f"Getis-Ord Gi* — {len(gdf)} units, {permutations} permutations{' + FDR' if fdr else ''}")
    gi = G_Local(gdf[value_col].astype(float).values, w, star=True, permutations=permutations)
    z, p_norm = gi_star_z(gdf[value_col].astype(float).values, w)
    gdf["gi_z"] = z
    # analytic p-values from the general-weights z when permutations=0;
    # esda's simulated p-values as ``p_sim`` otherwise.
    if permutations and tie_rule != "esda":
        gdf["p_value"] = gi_star_pseudo_p(gdf[value_col].astype(float).values, w,
                                          permutations, seed, tie_rule)
    else:
        gdf["p_value"] = gi.p_sim if permutations else p_norm
    res = GiStarResult(gdf=gdf, value_col=value_col, meta=ResultMeta(
        method="Getis-Ord Gi*", reference="Getis & Ord 1992; Ord & Getis 1995; PySAL esda.G_Local",
        params=dict(value_col=value_col, weights=weights_tag(weights), permutations=permutations,
                    alpha=alpha, fdr=fdr, seed=seed, tie_rule=tie_rule),
        dataset=dataset_meta_of(dataset),
    ))
    p_values = gdf["p_value"].to_numpy()
    res.relabel(benjamini_hochberg(p_values) if fdr else p_values, alpha)
    return res


# --------------------------------------------------------------------------- #
#  ArcGIS Gi_Bin confidence classes
# --------------------------------------------------------------------------- #
# names match PlotStyle.gi_bin_palette keys.
_GI_BINS = (
    ("hot 99%", 2.576, None), ("hot 95%", 1.960, 2.576), ("hot 90%", 1.645, 1.960),
    ("cold 90%", -1.960, -1.645), ("cold 95%", -2.576, -1.960), ("cold 99%", None, -2.576),
)

#: display order of the Gi_Bin classes, coldest to hottest
GI_BIN_ORDER = ["cold 99%", "cold 95%", "cold 90%", "ns", "hot 90%", "hot 95%", "hot 99%"]


def gi_confidence_bin(z: np.ndarray) -> np.ndarray:
    """Object array of Gi_Bin class names ("ns" where |z| < 1.645) — the
    two-sided 90/95/99 % normal critical values ArcGIS uses for ``Gi_Bin``."""
    labels = np.full(np.shape(z), "ns", dtype=object)
    z = np.asarray(z)
    for name, lo, hi in _GI_BINS:
        mask = np.ones(z.shape, dtype=bool)
        if lo is not None:
            mask &= z >= lo
        if hi is not None:
            mask &= z < hi
        labels[mask] = name
    return labels


# --------------------------------------------------------------------------- #
#  weights sensitivity
# --------------------------------------------------------------------------- #
def weights_sensitivity(
    dataset,
    *,
    stat: str = "gi",
    value_col: str = "crime_count",
    kinds=("queen", "rook", "knn"),
    permutations: int = 999,
    alpha: float = 0.05,
    fdr: bool = True,
    seed: int = 42,
):
    """Re-run ``stat`` ("gi" | "lisa") under several spatial-weights schemes and
    report how stable the per-unit labels are (a robustness check; project-
    specific summary).

    Returns ``(labels, stability)``: ``labels`` is a unit x kind DataFrame of the
    significance label; ``stability`` is a Series with the share of units whose
    label is identical across all kinds, and pairwise agreement vs the first kind.
    """
    import pandas as pd

    runner = getis_ord_gi if stat == "gi" else local_moran
    labels = {}
    for kind in kinds:
        res = runner(dataset, value_col=value_col, weights=kind,
                     permutations=permutations, alpha=alpha, fdr=fdr, seed=seed)
        labels[kind] = res.gdf.set_index(res.gdf.get("unit_id", res.gdf.index))["label"]
    labels = pd.DataFrame(labels)
    ref = labels[kinds[0]]
    stability = pd.Series(
        {"identical_all": float((labels.nunique(axis=1) == 1).mean()),
         **{f"vs_{k}": float((labels[k] == ref).mean()) for k in kinds[1:]}}
    )
    print(f"weights sensitivity ({stat}, {value_col}): "
          f"{stability['identical_all']:.1%} of units keep the same label across "
          f"{', '.join(kinds)}")
    return labels, stability
