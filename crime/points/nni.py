"""Average nearest-neighbour index — "are the points closer together than random?"

Method
    Clark & Evans ratio R = D_obs / D_exp, with D_obs the mean distance from
    each point to its nearest neighbour and D_exp = 0.5 / sqrt(n/A) its
    expectation under complete spatial randomness. z = (D_obs − D_exp) / SE,
    SE = 0.26136 / sqrt(n²/A), two-sided normal p. R < 1 clustered, R > 1
    dispersed. **No edge correction**: points near the boundary have their
    nearest neighbour searched only inside the window, which biases D_obs up;
    the result also depends on the chosen area A.
Reference
    Clark, P.J. & Evans, F.C. (1954). Distance to nearest neighbor as a measure
    of spatial relationships in populations. Ecology 35(4).
ESRI tool mirrored
    "Average Nearest Neighbor" (same ratio, z and p; A = the boundary area here).
Inputs → Outputs
    points + boundary → :class:`NNIResult`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree
from scipy.stats import norm

from crime.core.metadata import ResultMeta
from crime.points._common import coords_in, window


@dataclass
class NNIResult:
    ratio: float
    observed_m: float
    expected_m: float
    z: float
    p: float
    n_points: int
    area_km2: float
    n_coincident: int = 0
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def summary(self) -> None:
        kind = "clustered" if self.ratio < 1 else "dispersed" if self.ratio > 1 else "random"
        print(f"Average nearest neighbour (Clark & Evans) — {self.n_points} points, {self.area_km2:.1f} km²\n"
              f"  observed mean NN = {self.observed_m:.1f} m  expected = {self.expected_m:.1f} m\n"
              f"  R = {self.ratio:.4f} ({kind})  z = {self.z:.3f}  p = {self.p:.4g}\n"
              f"  points whose nearest neighbour is coincident (d = 0): {self.n_coincident}")


def nearest_neighbour_index(points: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> NNIResult:
    """Clark & Evans (1954) R of the points inside ``boundary`` (A = its area)."""
    region = window(boundary)
    xy = coords_in(points, region)
    n, area = len(xy), region.area
    if n < 2:
        raise ValueError("need at least two points inside the boundary")
    dist, _ = cKDTree(xy).query(xy, k=2)
    nn = dist[:, 1]
    obs, exp = float(nn.mean()), 0.5 / np.sqrt(n / area)
    se = 0.26136 / np.sqrt(n * n / area)
    z = (obs - exp) / se
    return NNIResult(
        ratio=obs / exp, observed_m=obs, expected_m=float(exp), z=float(z),
        p=float(2 * norm.sf(abs(z))), n_points=n, area_km2=area / 1e6,
        n_coincident=int((nn == 0).sum()),
        meta=ResultMeta(method="Average Nearest Neighbor", reference="Clark & Evans 1954",
                        params=dict(edge_correction="none", area="boundary")),
    )
