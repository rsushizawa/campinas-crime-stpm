"""Spatial and space-time weights — the neighbourhood every ESRI statistic uses.

Method
    Row-standardised contiguity / k-nearest-neighbour weights (libpysal) and a
    block space-time weights matrix for the space-time Gi* neighbourhood.
Reference
    libpysal ``Queen`` / ``Rook`` / ``KNN`` (Rey & Anselin 2007, PySAL); the
    space-time block matrix is a project-specific choice (see
    :func:`space_time_weights`).
ESRI tool mirrored
    "Generate Spatial Weights Matrix" / the neighbourhood options of
    "Create Space Time Cube" + "Emerging Hot Spot Analysis".
Inputs → Outputs
    GeoDataFrame (metric CRS) → libpysal ``W`` (``transform="r"``);
    spatial ``W`` + number of time bins → sparse ``(n·T) x (n·T)`` matrix.

    w = spatial_weights(ds.metric(), kind="queen")
    w = spatial_weights(ds.metric(), kind="knn", k=8)
    w = resolve_weights(gdf, "knn")                     # what every statistic calls

``kind`` is one of "queen", "rook", "knn".
"""
from __future__ import annotations

import geopandas as gpd
import libpysal.weights as lw
import numpy as np

# --------------------------------------------------------------------------- #
#  builders (registry: kind -> (gdf, k) -> W, before row-standardising)
# --------------------------------------------------------------------------- #
_BUILDERS = {
    "queen": lambda gdf, k: lw.Queen.from_dataframe(gdf, use_index=False),
    "rook": lambda gdf, k: lw.Rook.from_dataframe(gdf, use_index=False),
    "knn": lambda gdf, k: lw.KNN.from_dataframe(gdf, k=k),
}


def spatial_weights(gdf: gpd.GeoDataFrame, *, kind: str = "queen", k: int = 5) -> lw.W:
    """Row-standardised weights of ``kind`` ("queen" | "rook" | "knn"; ``k``
    neighbours for "knn", measured between unit centroids)."""
    if kind not in _BUILDERS:
        raise ValueError(f"Unknown kind '{kind}'. Use: {', '.join(_BUILDERS)}.")
    w = _BUILDERS[kind](gdf, k)
    w.transform = "r"
    return w


def resolve_weights(gdf, weights):
    """The one place a statistic turns its ``weights=`` argument into a ``W``:
    a pre-built libpysal ``W`` passes through, a kind string goes through
    :func:`spatial_weights`, and any other callable is a
    :class:`~crime.core.protocols.WeightsBuilder` called on ``gdf``."""
    if hasattr(weights, "transform"):
        return weights
    if callable(weights):
        return weights(gdf)
    return spatial_weights(gdf, kind=weights)


def weights_tag(weights) -> str:
    """How a ``weights=`` argument is recorded in a result header."""
    return weights if isinstance(weights, str) else "custom"


# --------------------------------------------------------------------------- #
#  space-time neighbourhood
# --------------------------------------------------------------------------- #
def space_time_weights(w, T, *, time_step=1, taper=False, temporal_direction="backward"):
    """Time-major sparse adjacency. Own-location history is explicitly included.

    Backward windows use t-k..t; symmetric windows use t-k..t+k and are
    retrospective. Row-standardised spatial weights retain the project's
    historical weighting convention; this is not an ArcGIS numerical clone.
    """
    from scipy import sparse
    if temporal_direction not in {"backward", "symmetric"}:
        raise ValueError("temporal_direction must be backward or symmetric")
    if not isinstance(time_step, int) or time_step < 0 or T < 1:
        raise ValueError("time_step must be nonnegative and T positive")
    n = w.n
    Wsp = w.sparse.tocsr()                                    # n x n spatial (row-standardised)
    eye = sparse.eye(n, format="csr")
    blocks = [[None] * T for _ in range(T)]
    for t in range(T):
        for dt in range(-time_step, (time_step if temporal_direction == "symmetric" else 0) + 1):
            s = t + dt
            if 0 <= s < T:
                base = Wsp if dt == 0 else (Wsp + eye)
                blocks[t][s] = base * (1.0 / (1 + abs(dt)) if taper else 1.0)
    W_st = sparse.bmat(blocks, format="csr")                  # (n·T) x (n·T), time-major
    W_st = sparse.diags(1.0 / np.asarray(W_st.sum(1)).ravel().clip(1e-12)) @ W_st

    return W_st
