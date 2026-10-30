"""Choropleth class breaks — quantile, equal-interval, or natural (1-D k-means).
Display classification for :mod:`crime.viz.maps` (not an inferential step).

``mapclassify`` is not a dependency, so this is a small self-contained version.

    from crime import classify, bin_index
    edges, labels = classify(gdf["crime_count"], scheme="natural", k=5)
    gdf["_cls"] = bin_index(gdf["crime_count"], edges)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SCHEMES = ("quantile", "equal_interval", "natural")


def classify(values, *, scheme: str = "quantile", k: int = 5) -> tuple[np.ndarray, list[str]]:
    """Return ``(edges, labels)`` — ``k+1`` bin edges (ties collapsed) and human
    labels. ``scheme``: ``"quantile"`` (equal count), ``"equal_interval"`` (equal
    width), ``"natural"`` (1-D k-means ≈ Jenks)."""
    v = pd.Series(values).dropna().to_numpy(dtype=float)
    if v.size == 0:
        raise ValueError("no finite values to classify")
    uniq = np.unique(v)
    k = int(min(k, uniq.size))

    if scheme == "quantile":
        edges = np.quantile(v, np.linspace(0.0, 1.0, k + 1))
    elif scheme == "equal_interval":
        edges = np.linspace(v.min(), v.max(), k + 1)
    elif scheme == "natural":
        if uniq.size <= k:
            edges = np.r_[uniq, uniq[-1]]
        else:
            from sklearn.cluster import KMeans

            lab = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(v.reshape(-1, 1))
            groups = sorted((np.sort(v[lab == c]) for c in np.unique(lab)), key=lambda g: g[0])
            edges = np.array(
                [groups[0][0]]
                + [(groups[i][-1] + groups[i + 1][0]) / 2.0 for i in range(len(groups) - 1)]
                + [groups[-1][-1]]
            )
    else:
        raise ValueError(f"scheme must be one of {SCHEMES}")

    edges = np.unique(np.round(edges, 12))
    if edges.size < 2:
        edges = np.array([v.min(), v.max() + 1e-9])

    def fmt(x: float) -> str:
        return f"{x:,.0f}" if abs(x) >= 100 else f"{x:.3g}"

    labels = [f"{fmt(edges[i])} – {fmt(edges[i + 1])}" for i in range(edges.size - 1)]
    return edges, labels


def bin_index(values, edges) -> pd.Series:
    """Integer bin ``0 … len(edges)-2`` per value (lowest edge inclusive)."""
    v = values if isinstance(values, pd.Series) else pd.Series(np.asarray(values, dtype=float))
    return pd.cut(v.astype(float), bins=np.asarray(edges), include_lowest=True, labels=False)
