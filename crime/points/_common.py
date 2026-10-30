"""Shared helpers for the point-pattern methods: metric coordinates inside a window."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import shapely

from crime.core.config import CRS_METRIC


def window(boundary: gpd.GeoDataFrame | gpd.GeoSeries) -> shapely.Geometry:
    """The study window: the boundary dissolved into one (prepared) geometry in CRS_METRIC."""
    region = shapely.union_all(boundary.to_crs(CRS_METRIC).geometry.values)
    shapely.prepare(region)
    return region


def coords_in(points: gpd.GeoDataFrame | gpd.GeoSeries, region: shapely.Geometry, *,
              sample: int | None = None, seed: int = 42) -> np.ndarray:
    """``(n, 2)`` metric coordinates of the points that lie inside ``region``
    (points on the boundary count), optionally a seeded random
    subsample of ``sample`` of them (without replacement)."""
    geom = points.to_crs(CRS_METRIC).geometry
    geom = geom[geom.notna() & ~geom.is_empty]
    xy = shapely.get_coordinates(geom.values)
    xy = xy[shapely.intersects_xy(region, xy[:, 0], xy[:, 1])]
    if sample is not None and sample < len(xy):
        rng = np.random.default_rng(seed)
        xy = xy[rng.choice(len(xy), size=sample, replace=False)]
    return xy


def csr(region: shapely.Geometry, n: int, rng: np.random.Generator) -> np.ndarray:
    """``n`` points of complete spatial randomness (binomial process) in ``region``,
    by rejection sampling from its bounding box."""
    xmin, ymin, xmax, ymax = region.bounds
    frac = max(region.area / ((xmax - xmin) * (ymax - ymin)), 1e-3)
    out, have = [], 0
    while have < n:
        m = int((n - have) / frac * 1.2) + 16
        x, y = rng.uniform(xmin, xmax, m), rng.uniform(ymin, ymax, m)
        ok = shapely.contains_xy(region, x, y)
        out.append(np.column_stack([x[ok], y[ok]]))
        have += int(ok.sum())
    return np.vstack(out)[:n]
