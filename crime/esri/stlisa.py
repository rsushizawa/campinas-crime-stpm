"""Space-time LISA — Anselin's Local Moran's I on every time slice of the cube.

Method
    Per-slice Local Moran's I with per-slice Benjamini–Hochberg FDR; units are
    then summarised by how often they are HH / LL and by their modal label.
Reference
    Anselin, L. (1995). Local indicators of spatial association — LISA.
    Geographical Analysis 27(2). Benjamini & Hochberg (1995) for FDR.
    The slice-by-slice application and the modal summary are a project-
    specific choice (ESRI's "Local Outlier Analysis" works on the cube with a
    space-time neighbourhood instead).
Steps
    1. cube (or a supplied matrix) as ``unit x period``; 2. for each slice
       with variance: Moran_Local + FDR → HH/LH/LL/HL or "ns" (units with no
       neighbours — ``w.islands`` — are "no data" in every slice and are left
       out of the BH family); 3. per unit: ``n_hh``, ``n_ll``, ``modal_label``
       (the most frequent significant quadrant; ties broken by the fixed
       order HH, LL, HL, LH — clusters before outliers, a project choice;
       "ns" if never significant, "no data" for islands).
Inputs → Outputs
    Dataset (``events=True``) → :class:`SpaceTimeLisaResult`
    (``labels`` unit x period, ``gdf`` + per-unit summary).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd

from crime.core.metadata import ResultMeta, dataset_meta_of
from crime.esri.cube import space_time_cube
from crime.esri.inference import benjamini_hochberg
from crime.esri.local import _QUAD, island_mask
from crime.esri.weights import resolve_weights, weights_tag

#: tie-break order of the modal label: clusters (HH, LL) before outliers (HL, LH)
_MODAL_ORDER = ("HH", "LL", "HL", "LH")


@dataclass
class SpaceTimeLisaResult:
    gdf: gpd.GeoDataFrame = field(repr=False)
    labels: pd.DataFrame = field(repr=False)     # unit x period category matrix
    alpha: float = 0.05
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def summary(self) -> None:
        counts = self.labels.stack().value_counts()
        print(
            f"Space-time LISA — {self.labels.shape[0]} units x {self.labels.shape[1]} "
            f"slices (alpha={self.alpha})"
        )
        print(counts.to_string())


def space_time_lisa(
    dataset, *, freq: str = "ME", weights="queen",
    permutations: int = 499, alpha: float = 0.05, fdr: bool = True, seed: int = 42, matrix=None,
) -> SpaceTimeLisaResult:
    """``matrix`` — a precomputed unit x period DataFrame to run per-slice LISA
    on instead of the crime-count cube (e.g. an EB-smoothed rate matrix);
    its index must match ``dataset``'s unit ids. Each slice uses esda's
    conditional-permutation pseudo p (``Moran_Local.p_sim``; ``permutations=499``
    is the ArcGIS Pro "Local Outlier Analysis" default, ``seed`` fixes the
    draws). ``fdr=True`` applies per-slice Benjamini-Hochberg correction,
    matching :func:`crime.esri.ehsa.gi_time_series`."""
    from esda.moran import Moran_Local

    gdf = dataset.metric().reset_index(drop=True)
    if matrix is not None:
        wide = matrix.reindex(gdf[dataset.id_col]).fillna(0.0).astype(float)
    else:
        wide = space_time_cube(dataset, freq=freq).wide.reindex(gdf[dataset.id_col]).fillna(0)
    w = resolve_weights(gdf, weights)

    print(f"Space-time LISA on {wide.shape[1]} slices x {len(gdf)} units"
          f"{' + FDR' if fdr else ''}")
    isl = island_mask(w)
    labels = {}
    for col in wide.columns:
        y = wide[col].values.astype(float)
        if y.sum() == 0 or y.std() == 0:
            labels[col] = np.where(isl, "no data", "ns")
            continue
        lisa = Moran_Local(y, w, permutations=permutations, seed=seed)
        p_raw = np.where(isl, np.nan, lisa.p_sim)          # islands: no test, outside the BH family
        p = benjamini_hochberg(p_raw) if fdr else p_raw
        sig = p < alpha                                     # NaN -> False
        labels[col] = np.where(isl, "no data", np.where(sig, [_QUAD[q] for q in lisa.q], "ns"))

    labels = pd.DataFrame(labels, index=wide.index)
    out = dataset.gdf.copy()
    out["n_hh"] = (labels == "HH").sum(axis=1).values
    out["n_ll"] = (labels == "LL").sum(axis=1).values
    # modal significant quadrant; ties -> first in _MODAL_ORDER (stated rule, not alphabetical)
    counts = pd.DataFrame({q: (labels == q).sum(axis=1) for q in _MODAL_ORDER})
    modal = counts.idxmax(axis=1).where(counts.max(axis=1) > 0, "ns")
    out["modal_label"] = np.where(isl, "no data", modal.to_numpy())
    return SpaceTimeLisaResult(gdf=out, labels=labels, alpha=alpha, meta=ResultMeta(
        method="Space-time LISA (per-slice Local Moran's I)", reference="Anselin 1995",
        params=dict(freq=freq, weights=weights_tag(weights), permutations=permutations,
                    alpha=alpha, fdr=fdr, seed=seed, matrix=matrix is not None),
        dataset=dataset_meta_of(dataset),
    ))
