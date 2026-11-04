"""Areal supports — census tracts and UTB planning units — and point-to-unit assignment.

The study has three spatial supports: the crime **points**, IBGE 2022 census
**tracts** (2,592) and **UTB** planning units (93). This module holds the
polygon side: every support comes out with the same columns (``unit_id``,
``area_km2``, ``geometry``, in :data:`~crime.core.config.CRS_METRIC`).

    unit_polygons(support)          tract / UTB polygons (no attributes)
    assign_points(points, units)    unit_id of the unit each point falls in
    areal_interpolate(src, tgt, c)  area-weighted transfer of extensive counts

The notebook-facing API (:func:`crime.data.api.load_units` etc.) is built on
these. No database is needed.
"""
from __future__ import annotations

from typing import Literal

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from crime.core.config import CRS_METRIC, GEOBR_CACHE

Support = Literal["tract", "utb"]
SUPPORTS = ("tract", "utb")


def _tracts() -> gpd.GeoDataFrame:
    from etl import sources

    tr = sources.extract_census_tracts(cache_dir=GEOBR_CACHE)
    g = tr[["cd_setor", "geometry"]].rename(columns={"cd_setor": "unit_id"}).to_crs(CRS_METRIC)
    g["unit_id"] = g["unit_id"].astype(str)
    return g


def _utbs() -> gpd.GeoDataFrame:
    from etl import sources

    u = sources.extract_utb()
    # utb_sigla repeats (e.g. five "UTR - Campo Grande" polygons); denominacao is unique.
    g = u[["denominacao", "utb_sigla", "geometry"]].rename(columns={"denominacao": "unit_id"})
    g = g.to_crs(CRS_METRIC)
    if g["unit_id"].duplicated().any():
        raise ValueError("UTB denominacao is not unique")
    return g


def _finish(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = g.copy()
    g["area_km2"] = g.geometry.area / 1e6
    extra = [c for c in g.columns if c not in ("unit_id", "area_km2", "geometry")]
    return gpd.GeoDataFrame(g[["unit_id", "area_km2", *extra, "geometry"]], geometry="geometry",
                            crs=CRS_METRIC).reset_index(drop=True)


def unit_polygons(support: Support) -> gpd.GeoDataFrame:
    """Polygons of ``support`` with ``unit_id``, ``area_km2``, ``geometry`` (EPSG:31983).

    ``"tract"``  2,592 IBGE 2022 census tracts (``unit_id`` = ``cd_setor``), from the
                 tracked geobr parquet in ``inputs/data/geobr/``;
    ``"utb"``    93 UTB planning units (``unit_id`` = ``denominacao``; ``utb_sigla``
                 kept), from ``inputs/data/map.geojson`` via ``etl.sources.extract_utb``.
    """
    if support == "tract":
        return _finish(_tracts())
    if support == "utb":
        return _finish(_utbs())
    raise ValueError(f"Unknown support {support!r}. Use: {', '.join(SUPPORTS)}.")


def assign_points(points: gpd.GeoDataFrame, units: gpd.GeoDataFrame) -> pd.Series:
    """``unit_id`` of the unit each point falls in (NaN outside every unit).

    Point-in-polygon (``intersects``) in the metric CRS. A point on an edge
    shared by several units goes to the first of them in ``units`` row order,
    so every point is counted once and the rule is deterministic. Returned
    Series is aligned on ``points.index``.
    """
    out = pd.Series(np.nan, index=points.index, dtype=object, name="unit_id")
    if len(points) == 0:
        return out
    pts = points.geometry.to_crs(CRS_METRIC).values
    poly = units.to_crs(CRS_METRIC).geometry.values
    tree = shapely.STRtree(poly)
    p_idx, u_idx = tree.query(pts, predicate="intersects")
    if len(p_idx):
        order = np.lexsort((u_idx, p_idx))           # by point, then by unit row
        p_idx, u_idx = p_idx[order], u_idx[order]
        first = np.r_[True, p_idx[1:] != p_idx[:-1]]
        ids = units["unit_id"].to_numpy()
        out.iloc[p_idx[first]] = ids[u_idx[first]]
    return out


def assign_nearest(points: gpd.GeoDataFrame, units: gpd.GeoDataFrame, *,
                   max_distance_m: float | None = None) -> pd.Series:
    """:func:`assign_points`, then the **nearest** unit for points that fall in
    none (``geopandas.sjoin_nearest``; ties -> first unit in row order). Used
    for UTBs, whose digitised mesh leaves slivers the tract mesh covers: 22
    in-tract bulletins lie outside every UTB, all within 84 m of one.
    ``max_distance_m`` leaves points farther than that unassigned (NaN)."""
    out = assign_points(points, units)
    miss = out.isna()
    if miss.any():
        p = gpd.GeoDataFrame(geometry=points.geometry[miss].to_crs(CRS_METRIC))
        u = units[["unit_id", "geometry"]].to_crs(CRS_METRIC).reset_index(drop=True)
        j = gpd.sjoin_nearest(p, u, how="left", max_distance=max_distance_m)
        j = j[~j.index.duplicated(keep="first")]
        out.loc[j.index] = j["unit_id"].to_numpy()
    return out


def areal_interpolate(source: gpd.GeoDataFrame, target: gpd.GeoDataFrame, cols) -> pd.DataFrame:
    """Area-weighted interpolation of **extensive** ``cols`` (counts such as
    population) from ``source`` units to ``target`` units.

    Each source value is split over the target units in proportion to the
    share of the source polygon's area that falls in each of them, then
    summed per target: ``y_t = Σ_s x_s · |s ∩ t| / |s|`` — the areal
    weighting method of Goodchild & Lam (1980), which assumes the quantity
    is spread uniformly within each source unit. Both frames need
    ``unit_id`` + geometry; areas are measured in the metric CRS. NaN source
    values contribute nothing. Source area outside every target is lost, so
    totals are preserved only when the targets cover the sources. Returns a
    DataFrame indexed by the target ``unit_id`` (0 for targets that overlap no
    source). (``tobler.area_weighted.area_interpolate`` is the library
    equivalent; this is kept for the tests and as a cross-check.)
    """
    cols = list(cols)
    src = source[["unit_id", *cols, "geometry"]].to_crs(CRS_METRIC).reset_index(drop=True)
    tgt = target[["unit_id", "geometry"]].to_crs(CRS_METRIC).reset_index(drop=True)
    src_area = src.geometry.area.to_numpy()
    s_idx, t_idx = shapely.STRtree(tgt.geometry.values).query(src.geometry.values, predicate="intersects")
    inter = shapely.area(shapely.intersection(src.geometry.values[s_idx], tgt.geometry.values[t_idx]))
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.where(src_area[s_idx] > 0, inter / src_area[s_idx], 0.0)
    out = pd.DataFrame(0.0, index=pd.Index(tgt["unit_id"], name="unit_id"), columns=cols)
    for c in cols:
        contrib = np.nan_to_num(src[c].to_numpy(dtype=float)[s_idx] * share)
        out[c] = np.bincount(t_idx, weights=contrib, minlength=len(tgt))
    return out
