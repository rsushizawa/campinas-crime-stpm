"""Time Series Clustering of a space-time cube.

Method
    k-means on a per-unit feature vector derived from its time series, with k
    chosen by the Calinski–Harabasz pseudo-F statistic.
Reference
    Caliński, T. & Harabasz, J. (1974). A dendrite method for cluster
    analysis. Communications in Statistics 3(1). k-means: scikit-learn.
ESRI tool mirrored
    "Time Series Clustering" (value / profile / Fourier characteristics of
    interest; pseudo-F rule for the number of clusters).
    Shared with ArcGIS: k swept over 2..10 when not given, 10 random starts per
    k, the k with the largest pseudo-F kept; Value = k-means on the raw series
    (Euclidean). Differences (ArcGIS Pro "How Time Series Clustering works"):
    * Profile (Correlation): ArcGIS runs k-medoids (PAM; CLARA above 10,000
      locations) on the distance 1 − r. Here k-means on z-scored series —
      squared Euclidean between z-scored series is 2T(1 − r), so the
      dissimilarity is the same up to scale but the centres are means, not
      medoids.
    * Profile (Fourier): ArcGIS clusters on the weights of (almost) all
      Fourier basis functions, optionally ignoring start time / magnitude.
      Here k-means on |DFT| of harmonics 1..``n_harmonics`` (the mean is
      dropped, phase always ignored, magnitude kept).
    * Pseudo-F is scikit-learn's Calinski–Harabasz on the feature space (ArcGIS
      uses medoid-based squared errors for the correlation option); no
      ``CENTER_REP`` medoid field.
Steps
    1. features: raw values, z-scored profile, or |DFT| of the first
       ``n_harmonics`` harmonics; 2. drop units below ``min_total``;
    3. sweep ``k_range`` (if ``k=None``) and keep the best pseudo-F;
    4. relabel clusters by total level (0 = quietest) for a stable palette.
Inputs → Outputs
    space-time cube → :class:`TSClusterResult` (per-unit ``cluster``, mean
    profile per cluster, pseudo-F by k).

Partition the cube's spatial units by the *shape* of their time series — a
data-driven trajectory typology to sit next to the rule-based EHSA categories.

    from crime import space_time_cube, time_series_clustering, cluster_profiles

    cube = space_time_cube(ds, freq="ME")
    tsc  = time_series_clustering(cube, method="profile")   # k chosen by pseudo-F
    tsc.summary()
    fig, ax = cluster_profiles(tsc)
    fig, ax, _ = choropleth_map(tsc, column="cluster")

``method``:
  ``"value"``    k-means on the raw series (groups units with similar *levels*);
  ``"profile"``  z-score each series first, so Euclidean ≈ 1 − correlation
                 (groups units that rise & fall *together*, regardless of level);
  ``"fourier"``  k-means on the magnitudes of the first few DFT harmonics
                 (groups units with a similar periodicity).
``k=None`` sweeps ``k_range`` and keeps the k with the highest Calinski-Harabasz
pseudo-F (ESRI's rule).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd

from crime.core.metadata import ResultMeta


@dataclass
class TSClusterResult:
    gdf: gpd.GeoDataFrame = field(repr=False)     # dataset.gdf + "cluster"
    profiles: pd.DataFrame = field(repr=False)    # cluster x period — mean series
    k: int = 0
    method: str = "profile"
    pseudo_f: float = float("nan")                # Calinski-Harabasz at the chosen k
    scores: pd.Series = field(default=None, repr=False)   # pseudo-F per candidate k
    value_col: str = "cluster"
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def summary(self) -> None:
        print(f"time series clustering ({self.method}) — k={self.k}, "
              f"pseudo-F {self.pseudo_f:.1f}")
        print(self.gdf["cluster"].value_counts().sort_index().to_string())
        if self.scores is not None and len(self.scores) > 1:
            print("pseudo-F by k: " + ", ".join(f"{k}:{v:.0f}" for k, v in self.scores.items()))


def _features(wide: np.ndarray, method: str, n_harmonics: int) -> np.ndarray:
    if method == "value":
        return wide
    if method == "profile":
        mu = wide.mean(1, keepdims=True)
        sd = wide.std(1, keepdims=True)
        return (wide - mu) / np.where(sd < 1e-9, 1.0, sd)
    if method == "fourier":
        return np.abs(np.fft.rfft(wide, axis=1))[:, 1:n_harmonics + 1]
    raise ValueError("method must be 'value', 'profile' or 'fourier'")


def time_series_clustering(
    cube,
    *,
    method: str = "profile",
    k: int | None = None,
    k_range: tuple[int, int] = (2, 10),
    n_harmonics: int = 6,
    min_total: int = 0,
    seed: int = 42,
) -> TSClusterResult:
    """``min_total`` — only cluster units with at least this many events over the
    whole period (the rest get ``cluster = -1``). Most tracts have near-zero,
    near-flat series; a threshold keeps the clustering about the units that
    actually vary."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import calinski_harabasz_score

    wide = getattr(cube, "wide", cube)
    gdf = getattr(cube, "gdf", None)
    if gdf is None:
        raise ValueError("pass a space_time_cube result (needs .wide and .gdf).")
    X = _features(wide.to_numpy(dtype=float), method, n_harmonics)
    keep = np.isfinite(X).all(1) & (wide.to_numpy().sum(1) >= min_total)
    Xk = X[keep]
    if len(Xk) < (k or k_range[1]) + 1:
        raise ValueError(f"only {len(Xk)} units pass min_total={min_total} — lower it.")

    scores = {}
    if k is None:
        for kk in range(k_range[0], min(k_range[1], len(Xk) - 1) + 1):
            lab = KMeans(n_clusters=kk, random_state=seed, n_init=10).fit_predict(Xk)
            scores[kk] = float(calinski_harabasz_score(Xk, lab)) if len(set(lab)) > 1 else 0.0
        k = max(scores, key=scores.get)

    km = KMeans(n_clusters=k, random_state=seed, n_init=10).fit(Xk)
    labels = pd.Series(-1, index=wide.index, dtype=int)
    labels[wide.index[keep]] = km.labels_
    # order clusters by mean level (0 = quietest) for a stable palette
    order = (wide.loc[labels[labels >= 0].index]
             .groupby(labels[labels >= 0]).sum().sum(axis=1).sort_values().index)
    remap = {old: new for new, old in enumerate(order)}
    labels = labels.map(lambda v: remap.get(v, -1))

    out = gdf.copy()
    out["cluster"] = labels.reindex(out["unit_id"] if "unit_id" in out else out.index).to_numpy()
    prof = wide.groupby(labels.reindex(wide.index)).mean()
    prof = prof[prof.index >= 0]
    prof.index = [f"cluster {i}" for i in prof.index]
    ch = float(calinski_harabasz_score(Xk, km.labels_)) if k > 1 else float("nan")
    return TSClusterResult(gdf=out, profiles=prof, k=int(k), method=method, pseudo_f=ch,
                           scores=pd.Series(scores).sort_index() if scores else None,
                           meta=ResultMeta(
                               method="Time series clustering (k-means)",
                               reference="Caliński & Harabasz 1974; ESRI Time Series Clustering",
                               params=dict(method=method, k=int(k), k_range=k_range,
                                           n_harmonics=n_harmonics, min_total=min_total, seed=seed,
                                           freq=getattr(cube, "freq", None)),
                               dataset=getattr(cube, "meta", None)))
