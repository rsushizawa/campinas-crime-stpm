"""Local spatial statistics — "where are the clusters?"

Method
    Getis-Ord Gi* hot/cold spots and Anselin's Local Moran's I (LISA) with
    optional Benjamini–Hochberg FDR control (:mod:`crime.esri.inference`).
    Inference follows the documented ArcGIS Pro defaults: Gi* uses the
    analytic z-score (general-weights Ord & Getis 1995 variance, two-sided
    normal p — no permutations); Local Moran's I uses conditional
    permutation (``esda`` ``p_sim``, 499 permutations).
Reference
    Getis, A. & Ord, J.K. (1992). The analysis of spatial association by use of
    distance statistics. Geographical Analysis 24(3).
    Ord, J.K. & Getis, A. (1995). Local spatial autocorrelation statistics:
    distributional issues and an application. Geographical Analysis 27(4).
    Anselin, L. (1995). Local indicators of spatial association — LISA.
    Geographical Analysis 27(2).
    Implementation: PySAL ``esda.getisord.G_Local`` / ``esda.moran.Moran_Local``.
ESRI tool mirrored
    "Hot Spot Analysis (Getis-Ord Gi*)" (analytic z) and "Cluster and Outlier
    Analysis (Anselin Local Moran's I)" (499 permutations by default);
    ``gi_confidence_bin`` reproduces ArcGIS's ``Gi_Bin`` 90/95/99 % confidence
    classes.
Steps
    1. drop units with NaN in ``value_col``; 2. resolve weights; 3. compute
    the local statistic + p-values; 4. adjust p (FDR) and label each unit
    ("hotspot"/"coldspot" or HH/LH/LL/HL, "ns", "no data").
Inputs → Outputs
    Dataset + weights → :class:`GiStarResult` / :class:`LisaResult` whose
    ``gdf`` carries the per-unit statistic, p-values and label.

Every function takes a Dataset and ``weights`` as either a kind string
("queen"/"rook"/"knn"), a pre-built libpysal ``W``, or a builder
callable. Call ``.summary()`` on a result to print a breakdown.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np

from crime.core.metadata import ResultMeta, dataset_meta_of
from crime.esri.inference import benjamini_hochberg
from crime.esri.weights import resolve_weights, weights_tag

_QUAD = {1: "HH", 2: "LH", 3: "LL", 4: "HL"}


def island_mask(w) -> np.ndarray:
    """Boolean array (in ``w.id_order``, i.e. the row order of the frame the
    weights were built on) marking units with no neighbours (``w.islands``).
    A local statistic is undefined for them: an island's spatial lag is 0, so
    esda returns ``I = 0`` with a meaningless permutation p-value."""
    pos = {u: i for i, u in enumerate(w.id_order)}
    m = np.zeros(w.n, dtype=bool)
    m[[pos[u] for u in w.islands]] = True
    return m


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
    permutations: int = 499,
    alpha: float = 0.05,
    fdr: bool = True,
    seed: int = 42,
) -> LisaResult:
    """Local Moran's I with esda's conditional-permutation pseudo p-value
    (``Moran_Local.p_sim``). ``permutations=499`` is the ArcGIS Pro "Cluster
    and Outlier Analysis" default; ``seed`` fixes the permutation draws.
    ``fdr=True`` (default) labels on Benjamini-Hochberg adjusted p-values
    across units — the right call when scanning many units. ``fdr=False``
    uses raw p. Units with no neighbours (``w.islands``) get NaN ``lisa_I`` /
    ``p_value``, the label "no data", and are left out of the BH family."""
    from esda.moran import Moran_Local

    gdf = dataset.metric().dropna(subset=[value_col]).reset_index(drop=True)
    w = resolve_weights(gdf, weights)
    print(f"LISA — {len(gdf)} units, {permutations} permutations{' + FDR' if fdr else ''}")
    lisa = Moran_Local(
        gdf[value_col].astype(float).values, w, permutations=permutations, seed=seed
    )
    # islands (no neighbours) have no local statistic: NaN I and p, so they are
    # labelled "no data" and excluded from the BH family (NaN p is skipped).
    isl = island_mask(w)
    gdf["lisa_I"] = np.where(isl, np.nan, lisa.Is)
    gdf["quadrant"] = [_QUAD[q] for q in lisa.q]
    gdf["p_value"] = np.where(isl, np.nan, lisa.p_sim)
    res = LisaResult(gdf=gdf, value_col=value_col, meta=ResultMeta(
        method="Local Moran's I (LISA)", reference="Anselin 1995; PySAL esda.Moran_Local",
        params=dict(value_col=value_col, weights=weights_tag(weights), permutations=permutations,
                    alpha=alpha, fdr=fdr, seed=seed),
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


def gi_star_z(y, w, *, transform: str = "R") -> tuple[np.ndarray, np.ndarray]:
    """Gi* z-scores and analytic p-values for **general** weights.

    esda 2.6.0's ``G_Local.Zs`` uses the Getis & Ord (1992) variance, which is
    exact only for binary weights; with row-standardised weights it ignores
    how many cells are averaged and shrinks z (~0.3-0.5x on queen tracts).
    This applies the Ord & Getis (1995) form to the final weights esda builds
    for Gi* (self-weight included)::

        z_i = (sum_j w_ij x_j - xbar W_i) / (s sqrt((N S2_i - W_i^2) / (N - 1)))

    with ``W_i = sum_j w_ij``, ``S2_i = sum_j w_ij^2``, ``s^2 = mean(x^2) - xbar^2``.
    Identical to esda's ``Zs`` for binary weights. ``p`` is the **two-sided**
    normal p-value ``2 * norm.sf(|z|)`` (the ArcGIS Pro Gi* convention); esda's
    ``p_norm`` is the one-sided ``norm.sf(|z|)``, i.e. half of this. A
    constant ``y`` has no z: both arrays are NaN.

    The weights come from a permutation-free ``G_Local`` (with
    ``permutations > 0`` esda zeroes the diagonal of ``gi.w`` while simulating).
    """
    from scipy.stats import norm

    x = np.asarray(y, dtype=float)
    if np.ptp(x) == 0:                  # zero variance: z undefined (round-off would give ±inf)
        return np.full(len(x), np.nan), np.full(len(x), np.nan)
    W = gi_star_weights(x, w, transform=transform)
    N = len(x)
    xbar = x.mean()
    s = np.sqrt((x ** 2).mean() - xbar ** 2)
    W1 = np.asarray(W.sum(axis=1)).ravel()
    S2 = np.asarray(W.multiply(W).sum(axis=1)).ravel()
    z = (W @ x - xbar * W1) / (s * np.sqrt((N * S2 - W1 ** 2) / (N - 1)))
    return z, 2.0 * norm.sf(np.abs(z))


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
        # a zero-variance value_col makes the Gi* z NaN, and without this
        # check `NaN > 0` (False) would silently mislabel a unit "coldspot".
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
    alpha: float = 0.05,
    fdr: bool = True,
) -> GiStarResult:
    """Gi* with the analytic z-score (:func:`gi_star_z`) and its two-sided
    normal p-value — the ArcGIS Pro "Hot Spot Analysis" default; no
    permutations, so the result is deterministic. ``fdr=True`` (default)
    labels on Benjamini-Hochberg adjusted p-values across all units.
    ``fdr=False`` uses raw p. A constant ``value_col`` has no z (NaN) and is
    labelled "no data"."""
    gdf = dataset.metric().dropna(subset=[value_col]).reset_index(drop=True)
    w = resolve_weights(gdf, weights)
    print(f"Getis-Ord Gi* — {len(gdf)} units, analytic z{' + FDR' if fdr else ''}")
    z, p_norm = gi_star_z(gdf[value_col].astype(float).values, w)
    gdf["gi_z"] = z
    gdf["p_value"] = p_norm
    res = GiStarResult(gdf=gdf, value_col=value_col, meta=ResultMeta(
        method="Getis-Ord Gi*", reference="Getis & Ord 1992; Ord & Getis 1995; PySAL esda.G_Local",
        params=dict(value_col=value_col, weights=weights_tag(weights), inference="analytic",
                    alpha=alpha, fdr=fdr),
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
    permutations: int = 499,
    alpha: float = 0.05,
    fdr: bool = True,
    seed: int = 42,
):
    """Re-run ``stat`` ("gi" | "lisa") under several spatial-weights schemes and
    report how stable the per-unit labels are (a robustness check; project-
    specific summary). ``permutations`` / ``seed`` apply to LISA only (Gi* is
    analytic).

    Returns ``(labels, stability)``: ``labels`` is a unit x kind DataFrame of the
    significance label; ``stability`` is a Series with the share of units whose
    label is identical across all kinds, and pairwise agreement vs the first kind.
    """
    import pandas as pd

    labels = {}
    for kind in kinds:
        if stat == "gi":
            res = getis_ord_gi(dataset, value_col=value_col, weights=kind, alpha=alpha, fdr=fdr)
        else:
            res = local_moran(dataset, value_col=value_col, weights=kind,
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
