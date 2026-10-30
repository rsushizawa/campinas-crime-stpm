"""Planar kernel density — a continuous intensity surface of the crime points.

Method
    density(c) = Σ_i K(‖c − x_i‖; h) at each grid-cell centre c, in points per
    km². Kernels:
    ``"quartic"``  (default) K = 3/(π h²) · (1 − (d/h)²)² for d < h, the
                   kernel of Esri's Kernel Density tool (Silverman 1986,
                   eq. 4.5), h = search radius;
    ``"gaussian"`` K = 1/(2π h²) · exp(−d²/(2h²)), h = standard deviation,
                   truncated at 4h (keeps ~99.97% of each point's mass).
    Default bandwidth (``bandwidth_m=None``):
    quartic   — Esri's spatial variant of Silverman's rule of thumb,
                h = 0.9 · min(SD, sqrt(1/ln 2) · D_m) · n^(−0.2), with SD the
                standard distance and D_m the median distance to the mean centre;
    gaussian  — Silverman's normal-reference rule for two dimensions,
                h = σ · n^(−1/6), σ² the mean of the two coordinate variances
                (Silverman 1986, §4.3.2).
    Cells whose centre is outside the boundary are masked (NaN); kernel mass
    that falls outside the boundary is not renormalised (no edge correction),
    so the surface integrates to ≈ n only for points away from the edge.
Reference
    Silverman, B.W. (1986). Density Estimation for Statistics and Data
    Analysis. Chapman & Hall. Esri, ArcGIS Pro "How Kernel Density works".
ESRI tool mirrored
    "Kernel Density" (Spatial Analyst), planar method, no population field.
Inputs → Outputs
    points + boundary → :class:`KDEResult` (``density`` 2-D array, north row
    first; ``transform`` / ``extent`` to place it; ``cells()`` / ``mean_by_unit``
    to aggregate it to areal units).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree

from crime.core.config import CRS_METRIC
from crime.core.metadata import ResultMeta
from crime.points._common import coords_in, window

_KERNELS = ("quartic", "gaussian")


@dataclass
class KDEResult:
    density: np.ndarray                 # (rows, cols) points per km², row 0 = north; NaN outside
    transform: tuple[float, ...]        # GDAL/affine order: (cell, 0, xmin, 0, -cell, ymax)
    extent: tuple[float, float, float, float]   # (xmin, xmax, ymin, ymax) — matplotlib imshow order
    cell_m: float
    bandwidth_m: float
    kernel: str
    n_points: int
    crs: str = CRS_METRIC
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    @property
    def total(self) -> float:
        """Integral of the surface over the boundary (≈ number of points)."""
        return float(np.nansum(self.density) * (self.cell_m / 1000) ** 2)

    def cells(self) -> gpd.GeoDataFrame:
        """Cell centres inside the boundary as points with a ``density`` column."""
        rows, cols = np.nonzero(~np.isnan(self.density))
        cell, xmin, ymax = self.transform[0], self.transform[2], self.transform[5]
        x, y = xmin + (cols + 0.5) * cell, ymax - (rows + 0.5) * cell
        return gpd.GeoDataFrame({"density": self.density[rows, cols]},
                                geometry=gpd.points_from_xy(x, y), crs=self.crs)

    def mean_by_unit(self, units: gpd.GeoDataFrame) -> pd.Series:
        """Mean density (per km²) of the cells whose centre falls in each unit,
        indexed by ``units.unit_id`` (NaN for units holding no cell centre)."""
        from crime.data.units import assign_points

        c = self.cells()
        uid = assign_points(c, units)
        return c["density"].groupby(uid).mean().reindex(units["unit_id"]).rename("kde_density")

    def summary(self) -> None:
        d = self.density[~np.isnan(self.density)]
        print(f"Kernel density ({self.kernel}) — {self.n_points} points, h = {self.bandwidth_m:.0f} m, "
              f"cell = {self.cell_m:.0f} m, {d.size} cells\n"
              f"  density per km²: max {d.max():.1f}, mean {d.mean():.1f}; integral {self.total:.1f}")


def default_bandwidth(xy: np.ndarray, kernel: str = "quartic") -> float:
    """Default h for ``kernel`` (module docstring)."""
    n = len(xy)
    if kernel == "gaussian":
        return float(np.sqrt(xy.var(axis=0, ddof=1).mean()) * n ** (-1 / 6))
    centre = xy.mean(axis=0)
    dist = np.hypot(*(xy - centre).T)
    sd = math.sqrt((dist ** 2).sum() / n)            # standard distance
    return float(0.9 * min(sd, math.sqrt(1 / math.log(2)) * np.median(dist)) * n ** -0.2)


def _kernel(d: np.ndarray, h: float, kernel: str) -> np.ndarray:
    if kernel == "quartic":
        return 3 / (math.pi * h * h) * (1 - (d / h) ** 2) ** 2
    return np.exp(-d * d / (2 * h * h)) / (2 * math.pi * h * h)


def kde_surface(points: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, *, cell_m: float = 100,
                bandwidth_m: float | None = None, kernel: str = "quartic",
                chunk: int = 4096) -> KDEResult:
    """Kernel density of the points inside ``boundary`` on a ``cell_m`` grid, per km².

    Exact sum over points within the kernel support of each cell centre
    (``cKDTree.sparse_distance_matrix``, ``chunk`` cells at a time)."""
    if kernel not in _KERNELS:
        raise ValueError(f"kernel must be one of {_KERNELS}")
    region = window(boundary)
    xy = coords_in(points, region)
    if len(xy) < 2:
        raise ValueError("need at least two points inside the boundary")
    h = float(bandwidth_m) if bandwidth_m is not None else default_bandwidth(xy, kernel)
    support = h if kernel == "quartic" else 4 * h

    xmin, ymin, xmax, ymax = region.bounds
    nx, ny = int(math.ceil((xmax - xmin) / cell_m)), int(math.ceil((ymax - ymin) / cell_m))
    ymax = ymin + ny * cell_m
    cx = xmin + (np.arange(nx) + 0.5) * cell_m
    cy = ymax - (np.arange(ny) + 0.5) * cell_m
    gx, gy = np.meshgrid(cx, cy)
    inside = shapely.contains_xy(region, gx, gy)
    centres = np.column_stack([gx[inside], gy[inside]])

    tree = cKDTree(xy)
    vals = np.zeros(len(centres))
    for s in range(0, len(centres), chunk):
        part = centres[s:s + chunk]
        m = tree.sparse_distance_matrix(cKDTree(part), support, output_type="ndarray")
        if len(m):
            w = _kernel(m["v"], h, kernel)
            vals[s:s + chunk] = np.bincount(m["j"], weights=w, minlength=len(part))
    density = np.full((ny, nx), np.nan)
    density[inside] = vals * 1e6                       # per m² -> per km²
    return KDEResult(
        density=density, transform=(cell_m, 0.0, xmin, 0.0, -cell_m, ymax),
        extent=(xmin, xmin + nx * cell_m, ymin, ymax), cell_m=cell_m, bandwidth_m=h,
        kernel=kernel, n_points=len(xy),
        meta=ResultMeta(method="Kernel Density", reference="Silverman 1986; Esri Kernel Density",
                        params=dict(cell_m=cell_m, bandwidth_m=h, kernel=kernel,
                                    bandwidth_rule="given" if bandwidth_m is not None else "default")),
    )
