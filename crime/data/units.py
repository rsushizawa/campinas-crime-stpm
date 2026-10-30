"""Spatial supports for the MAUP comparison — one loader for every areal unit.

The study compares results across supports: census **tracts** (IBGE 2022),
**UTB** planning units, and the crime **points** aggregated into a regular
tessellation (**hexagon** / **square** cells of a fixed area). Every support
comes out with the same columns (``unit_id``, ``area_km2``, ``geometry``, in
:data:`~crime.core.config.CRS_METRIC`), so Moran / Gi* / LISA / the cube /
EHSA run on each one unchanged.

Method
    Tessellation: regular cells of the requested area laid over the boundary's
    bounding box, kept where they overlap the boundary with positive area, and
    clipped to it. Points are assigned to units by point-in-polygon in the
    metric CRS (:func:`assign_points`).
ESRI tool mirrored
    "Generate Tessellation" (shape + cell area) followed by "Create Space Time
    Cube By Aggregating Points" with a polygon template. Grid origin, hexagon
    orientation (flat-topped) and the clip-to-boundary step are project choices.
Inputs → Outputs
    ``load_units(kind)`` → GeoDataFrame; ``unit_dataset(kind, ...)`` →
    :class:`~crime.core.dataset.Dataset` with ``crime_count`` per unit (0 for
    units with no events) and an ``events`` table for the space-time cube.

    from crime.data.units import unit_dataset
    ds = unit_dataset("hexagon", area_km2=0.5, crime_group="property")
"""
from __future__ import annotations

import math
from typing import Literal

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from crime.core.config import BULLETINS_PARQUET, CRS_METRIC, CRS_WGS84, GEOBR_CACHE
from crime.core.dataset import Dataset
from crime.core.metadata import DatasetMeta

Kind = Literal["tract", "utb", "hexagon", "square"]
KINDS = ("tract", "utb", "hexagon", "square")
_PREFIX = {"hexagon": "H", "square": "S"}

#: cleaned-bulletin columns -> event-table columns (as ``fato_crimes`` names them)
_EVENT_COLS = {"DATA_OCORRENCIA_BO": "data_ocorrencia", "HORA_OCORRENCIA_BO": "hora_ocorrencia",
               "DESC_PERIODO": "periodo", "crime_slug": "crime_slug", "crime_group": "crime_group"}


# --------------------------------------------------------------------------- #
#  tessellation
# --------------------------------------------------------------------------- #
def _hexagons(xmin, ymin, xmax, ymax, area_m2):
    """Flat-topped regular hexagons of ``area_m2`` covering the box (one cell of
    margin): columns 1.5·side apart, odd columns shifted down half a row.
    Vertices are built on an integer lattice (x in side/2, y in height/2 steps)
    so neighbouring cells share bit-identical vertices — queen/rook contiguity
    matches vertices exactly."""
    side = math.sqrt(2 * area_m2 / (3 * math.sqrt(3)))
    h = math.sqrt(3) * side
    ncol = int(math.ceil((xmax - xmin) / (1.5 * side))) + 2
    nrow = int(math.ceil((ymax - ymin) / h)) + 2
    cc, rr = (a.ravel() for a in np.meshgrid(np.arange(ncol), np.arange(nrow)))
    ix = 3 * cc                                   # centre x in units of side/2
    iy = 2 * rr - (cc % 2)                        # centre y in units of h/2
    dx = np.array([2, 1, -1, -2, -1, 1])
    dy = np.array([0, 1, 1, 0, -1, -1])
    xs = xmin + (ix[:, None] + dx) * (side / 2)
    ys = ymin + (iy[:, None] + dy) * (h / 2)
    return shapely.polygons(np.stack([xs, ys], axis=-1))


def _squares(xmin, ymin, xmax, ymax, area_m2):
    """Square cells of ``area_m2`` covering the box; edges come from one shared
    coordinate array so neighbours share identical vertices."""
    s = math.sqrt(area_m2)
    nx, ny = int(math.ceil((xmax - xmin) / s)), int(math.ceil((ymax - ymin) / s))
    xe, ye = xmin + np.arange(nx + 1) * s, ymin + np.arange(ny + 1) * s
    cc, rr = (a.ravel() for a in np.meshgrid(np.arange(nx), np.arange(ny)))
    return shapely.box(xe[cc], ye[rr], xe[cc + 1], ye[rr + 1])


def tessellation(boundary: gpd.GeoDataFrame, *, shape: Literal["hexagon", "square"],
                 area_km2: float) -> gpd.GeoDataFrame:
    """Regular ``shape`` cells of ``area_km2`` covering ``boundary``.

    Cells overlapping the (dissolved) boundary with positive area are kept and
    clipped to it, so edge cells are smaller (their clipped area is in
    ``area_km2``). The grid is anchored at the boundary's lower-left bounding
    corner. ``unit_id`` = shape letter + cell area in 1,000 m² + row-major cell
    number, e.g. ``"H500_000123"`` for a 0.5 km² hexagon; ids are stable for a
    given boundary, shape and area.
    """
    if shape not in _PREFIX:
        raise ValueError(f"shape must be 'hexagon' or 'square', got {shape!r}")
    if not area_km2 or area_km2 <= 0:
        raise ValueError("area_km2 must be positive")
    region = shapely.union_all(boundary.to_crs(CRS_METRIC).geometry.values)
    area_m2 = area_km2 * 1e6
    build = _hexagons if shape == "hexagon" else _squares
    cells = build(*region.bounds, area_m2)
    shapely.prepare(region)
    keep = np.flatnonzero(shapely.intersects(region, cells))
    clipped = shapely.intersection(cells[keep], region)
    clipped = shapely.make_valid(clipped)
    area = shapely.area(clipped)
    ok = area > 0
    keep, clipped, area = keep[ok], clipped[ok], area[ok]
    tag = f"{_PREFIX[shape]}{round(area_m2 / 1000)}"
    return gpd.GeoDataFrame(
        {"unit_id": [f"{tag}_{i:06d}" for i in keep], "area_km2": area / 1e6},
        geometry=clipped, crs=CRS_METRIC,
    ).reset_index(drop=True)


# --------------------------------------------------------------------------- #
#  loaders
# --------------------------------------------------------------------------- #
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
    g = u[["denominacao", "geometry"]].rename(columns={"denominacao": "unit_id"}).to_crs(CRS_METRIC)
    if g["unit_id"].duplicated().any():
        raise ValueError("UTB denominacao is not unique")
    return g


def _finish(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = g.copy()
    g["area_km2"] = g.geometry.area / 1e6
    return gpd.GeoDataFrame(g[["unit_id", "area_km2", "geometry"]], geometry="geometry",
                            crs=CRS_METRIC).reset_index(drop=True)


def load_units(kind: Kind, *, area_km2: float | None = None) -> gpd.GeoDataFrame:
    """Units of ``kind`` with ``unit_id``, ``area_km2``, ``geometry`` (EPSG:31983).

    ``"tract"``  2,592 IBGE 2022 census tracts (``cd_setor``), from the tracked
                 geobr parquet in ``inputs/data/geobr/``;
    ``"utb"``    93 UTB planning units (``denominacao``), ``etl.sources.extract_utb``;
    ``"hexagon"`` / ``"square"``  :func:`tessellation` of ``area_km2`` over the
                 dissolved tract boundary (the municipality).
    No database is needed.
    """
    if kind == "tract":
        return _finish(_tracts())
    if kind == "utb":
        return _finish(_utbs())
    if kind in _PREFIX:
        if area_km2 is None:
            raise ValueError(f"kind={kind!r} needs area_km2")
        return tessellation(_tracts(), shape=kind, area_km2=area_km2)
    raise ValueError(f"Unknown kind {kind!r}. Use: {', '.join(KINDS)}.")


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
    source).
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


def unit_dataset(
    kind: Kind,
    *,
    crime_group: str | None = None,
    area_km2: float | None = None,
    years: tuple[int, int] = (2022, 2025),
    bulletins: pd.DataFrame | None = None,
    units: gpd.GeoDataFrame | None = None,
) -> Dataset:
    """Crime counts on ``kind`` units, from the cleaned bulletins.

    ``bulletins`` defaults to ``outputs/data/bulletins_clean.parquet`` (one row
    per bulletin; ``LATITUDE``/``LONGITUDE`` in WGS84, ``DATA_OCORRENCIA_BO``
    ...). Rows are kept when they match ``crime_group`` (``None`` = all
    groups), have coordinates, and occurred within ``years`` (inclusive);
    each is assigned to a unit by :func:`assign_points` — also for tracts, so
    every support uses the same rule. Points outside every unit are dropped.
    ``units`` overrides :func:`load_units` (any frame with ``unit_id`` +
    geometry, e.g. for tests).

    ``gdf``: ``unit_id``, ``area_km2``, ``crime_count`` (0 for empty units),
    ``geometry``. ``events``: ``unit_id``, ``data_ocorrencia``,
    ``hora_ocorrencia``, ``periodo``, ``crime_slug``, ``crime_group``.
    """
    u = load_units(kind, area_km2=area_km2) if units is None else units.to_crs(CRS_METRIC)
    if "area_km2" not in u:
        u = _finish(u)
    b = pd.read_parquet(BULLETINS_PARQUET) if bulletins is None else bulletins
    if crime_group is not None:
        b = b[b["crime_group"].eq(crime_group).fillna(False).astype(bool)]
    b = b[b["LATITUDE"].notna() & b["LONGITUDE"].notna()]
    when = pd.to_datetime(b["DATA_OCORRENCIA_BO"], errors="coerce")
    lo, hi = pd.Timestamp(years[0], 1, 1), pd.Timestamp(years[1] + 1, 1, 1)
    b = b[when.ge(lo) & when.lt(hi)]

    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(b["LONGITUDE"], b["LATITUDE"]),
                           index=b.index, crs=CRS_WGS84)
    uid = assign_points(pts, u)
    ev = b[[c for c in _EVENT_COLS if c in b]].rename(columns=_EVENT_COLS)
    ev.insert(0, "unit_id", uid)
    ev = ev[ev["unit_id"].notna()].reset_index(drop=True)
    ev["data_ocorrencia"] = pd.to_datetime(ev["data_ocorrencia"])

    gdf = u[["unit_id", "area_km2", "geometry"]].copy()
    gdf["crime_count"] = gdf["unit_id"].map(ev["unit_id"].value_counts()).fillna(0).astype(int)
    gdf = gpd.GeoDataFrame(gdf[["unit_id", "area_km2", "crime_count", "geometry"]],
                           geometry="geometry", crs=CRS_METRIC)

    src = "bulletins_clean.parquet" if bulletins is None else "bulletins (frame)"
    unit = kind if area_km2 is None or kind not in _PREFIX else f"{kind}:{area_km2:g}km2"
    meta = DatasetMeta(unit=unit, years=years, crime_group=crime_group,
                       source=f"{src} -> {kind} point-in-polygon")
    return Dataset(gdf=gdf, unit=unit, years=meta.years, events=ev, meta=meta)
