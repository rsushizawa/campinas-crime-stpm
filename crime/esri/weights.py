"""Spatial and space-time weights — the neighbourhood every ESRI statistic uses.

Method
    Row-standardised contiguity / k-nearest-neighbour weights (libpysal), a
    street-network analogue (segments sharing an endpoint), and a block
    space-time weights matrix for the space-time Gi* neighbourhood.
Reference
    libpysal ``Queen`` / ``Rook`` / ``KNN`` (Rey & Anselin 2007, PySAL);
    network adjacency and the space-time block matrix are project-specific
    choices (see :func:`space_time_weights`).
ESRI tool mirrored
    "Generate Spatial Weights Matrix" / the neighbourhood options of
    "Create Space Time Cube" + "Emerging Hot Spot Analysis".
Inputs → Outputs
    GeoDataFrame (metric CRS) → libpysal ``W`` (``transform="r"``);
    spatial ``W`` + number of time bins → sparse ``(n·T) x (n·T)`` matrix.

    w = spatial_weights(ds.metric(), kind="queen")
    w = spatial_weights(segments, kind="network")      # LineString rows
    w = network_weights(segments)                       # same thing, explicit
    w = resolve_weights(gdf, "knn")                     # what every statistic calls

``kind`` is one of "queen", "rook", "knn", "network" ("segment" is an alias
for "network"). "network" treats LineString rows as street segments: two
segments are neighbours when they share an endpoint (the network analogue of
rook), optionally expanded to ``order`` topological hops (lower orders
included).
"""
from __future__ import annotations

import geopandas as gpd
import libpysal.weights as lw
import numpy as np

_ALIASES = {"segment": "network"}


# --------------------------------------------------------------------------- #
#  segment topology
# --------------------------------------------------------------------------- #
def endpoint_index(segments: gpd.GeoDataFrame) -> dict[object, list[int]]:
    """endpoint id -> row positions of the segments meeting there. Uses the OSM
    ``u`` / ``v`` node ids when ``street_segments`` provides them (exact), else
    falls back to rounding the endpoint coordinates.

    Shared by network weights, NKDE and segment structure so they always agree
    on what counts as a junction."""
    idx: dict[object, list[int]] = {}
    if {"u", "v"}.issubset(segments.columns):
        for i, (u, v) in enumerate(zip(segments["u"].to_numpy(), segments["v"].to_numpy())):
            idx.setdefault(u, []).append(i)
            idx.setdefault(v, []).append(i)
    else:
        for i, geom in enumerate(segments.geometry):
            for x, y in (geom.coords[0], geom.coords[-1]):
                idx.setdefault((round(x, 2), round(y, 2)), []).append(i)
    return idx


def _endpoint_adjacency(gdf: gpd.GeoDataFrame) -> lw.W:
    """libpysal ``W`` from :func:`endpoint_index`."""
    endpoint_rows = endpoint_index(gdf)
    neighbors: dict[int, set[int]] = {i: set() for i in range(len(gdf))}
    for rows in endpoint_rows.values():
        for i in rows:
            neighbors[i].update(j for j in rows if j != i)
    return lw.W({i: sorted(js) for i, js in neighbors.items()}, silence_warnings=True)


# --------------------------------------------------------------------------- #
#  builders (registry: kind -> (gdf, k, order) -> W, before row-standardising)
# --------------------------------------------------------------------------- #
def _network(gdf, k, order):
    w = _endpoint_adjacency(gdf)
    if order > 1:
        w = lw.higher_order(w, order, lower_order=True, silence_warnings=True)
    return w


_BUILDERS = {
    "queen": lambda gdf, k, order: lw.Queen.from_dataframe(gdf, use_index=False),
    "rook": lambda gdf, k, order: lw.Rook.from_dataframe(gdf, use_index=False),
    "knn": lambda gdf, k, order: lw.KNN.from_dataframe(gdf, k=k),
    "network": _network,
}


def spatial_weights(
    gdf: gpd.GeoDataFrame, *, kind: str = "queen", k: int = 5, order: int = 1
) -> lw.W:
    """Row-standardised weights of ``kind`` ("queen" | "rook" | "knn" | "network")."""
    kind = _ALIASES.get(kind, kind)
    if kind not in _BUILDERS:
        raise ValueError(f"Unknown kind '{kind}'. Use: queen, rook, knn, network.")
    w = _BUILDERS[kind](gdf, k, order)
    w.transform = "r"
    return w


def network_weights(segments: gpd.GeoDataFrame, *, order: int = 1) -> lw.W:
    """Topological weights over street segments (shared-endpoint adjacency)."""
    return spatial_weights(segments, kind="network", order=order)


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
