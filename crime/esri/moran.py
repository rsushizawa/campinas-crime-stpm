"""Global spatial autocorrelation — "is crime clustered at all?"

Method
    Global Moran's I with a conditional-permutation pseudo p-value, plus the
    analytic normal-approximation z / p (randomisation-free, ``esda`` ``z_norm`` /
    ``p_norm`` — the value ArcGIS Pro reports).
Reference
    Moran, P.A.P. (1950). Notes on continuous stochastic phenomena.
    Biometrika 37(1/2). Implementation: PySAL ``esda.moran.Moran``.
ESRI tool mirrored
    "Spatial Autocorrelation (Global Moran's I)".
Steps
    1. drop units with NaN in ``value_col``; 2. build/resolve row-standardised
    weights; 3. compute I and its permutation distribution (seeded).
Inputs → Outputs
    Dataset + weights → :class:`MoranResult` (I, E[I], z, p, significance).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np

from crime.core.metadata import ResultMeta, dataset_meta_of
from crime.esri.weights import resolve_weights, weights_tag


@dataclass
class MoranResult:
    I: float
    p_sim: float
    z_sim: float
    EI: float
    significant: bool
    value_col: str
    gdf: gpd.GeoDataFrame = field(repr=False)
    weights: object = field(repr=False)
    z_norm: float = float("nan")      # analytic (normality) z
    p_norm: float = float("nan")      # analytic (normality) two-sided p
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def summary(self) -> None:
        print(
            f"Global Moran's I — {self.value_col}\n"
            f"  I = {self.I:.4f}  E[I] = {self.EI:.4f}\n"
            f"  z_sim = {self.z_sim:.4f}  p_sim = {self.p_sim:.4f}\n"
            f"  z_norm = {self.z_norm:.4f}  p_norm = {self.p_norm:.4f}\n"
            f"  significant: {'yes' if self.significant else 'no'}"
        )


def global_moran(
    dataset,
    *,
    value_col: str = "crime_count",
    weights="queen",
    permutations: int = 9999,
    alpha: float = 0.05,
    seed: int = 42,
) -> MoranResult:
    from esda.moran import Moran

    np.random.seed(seed)
    gdf = dataset.metric().dropna(subset=[value_col]).reset_index(drop=True)
    w = resolve_weights(gdf, weights)
    print(f"Global Moran's I — {len(gdf)} units, {permutations} permutations")
    mi = Moran(gdf[value_col].astype(float).values, w, permutations=permutations)
    return MoranResult(
        I=float(mi.I), p_sim=float(mi.p_sim), z_sim=float(mi.z_sim), EI=float(mi.EI),
        z_norm=float(mi.z_norm), p_norm=float(mi.p_norm),
        significant=bool(mi.p_sim < alpha), value_col=value_col, gdf=gdf, weights=w,
        meta=ResultMeta(
            method="Global Moran's I", reference="Moran 1950; PySAL esda.Moran",
            params=dict(value_col=value_col, weights=weights_tag(weights),
                        permutations=permutations, alpha=alpha, seed=seed),
            dataset=dataset_meta_of(dataset),
        ),
    )
