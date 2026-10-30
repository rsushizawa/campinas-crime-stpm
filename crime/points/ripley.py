"""Ripley's K as Besag's L — "at which distances are the points clustered?"

Method
    K(d) = A / (n(n-1)) · Σ_{i≠j} 1(d_ij ≤ d), the naive estimator (**no edge
    correction**), and L(d) = sqrt(K(d)/π), so L(d) = d under complete spatial
    randomness (CSR). The envelope is the pointwise **min/max** of L(d) over
    ``n_simulations`` CSR patterns of the same n in the same window: for 99
    simulations, L outside it rejects CSR at that distance at the 2/(99+1) =
    0.02 level (two-sided; Besag & Diggle 1977). Because the simulated patterns
    share the observed window, the uncorrected estimator's edge bias (L drifts
    below d at large d) is common to the observed curve and the envelope; the
    choice of no correction is a project choice.
Reference
    Ripley, B.D. (1976). The second-order analysis of stationary point
    processes. J. Applied Probability 13(2). Ripley, B.D. (1977). Modelling
    spatial patterns. JRSS B 39(2). Besag, J. (1977). Contribution to the
    discussion of Ripley (1977), JRSS B 39(2) (the L transform). Besag, J. &
    Diggle, P.J. (1977). Simple Monte Carlo tests for spatial pattern. Applied
    Statistics 26(3).
ESRI tool mirrored
    "Multi-Distance Spatial Cluster Analysis (Ripley's K Function)" (which also
    reports L(d) with a min/max permutation envelope). Implemented with SciPy
    ``cKDTree.count_neighbors`` rather than PySAL ``pointpats``, whose K/L tests
    compute all pairwise distances (infeasible memory for tens of thousands of
    points).
Inputs → Outputs
    points + boundary → :class:`RipleyResult` (``table``: distance_m, L,
    L_minus_d, env_low, env_high).

    from crime.points.ripley import ripley_l
    r = ripley_l(pts, boundary, distances_m=range(100, 2001, 100), sample=20_000)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from crime.core.metadata import ResultMeta
from crime.points._common import coords_in, csr, window

REFERENCE = "Ripley 1976, 1977; Besag 1977 (L); Besag & Diggle 1977 (envelope)"


@dataclass
class RipleyResult:
    table: pd.DataFrame
    n_points: int
    area_km2: float
    n_simulations: int
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    @property
    def clustered(self) -> pd.Series:
        """True where observed L is above the envelope (clustering at that distance)."""
        return self.table["L"] > self.table["env_high"]

    def summary(self) -> None:
        t = self.table
        alpha = 2 / (self.n_simulations + 1)
        print(f"Ripley's L — {self.n_points} points in {self.area_km2:.1f} km², "
              f"{self.n_simulations} CSR simulations (min/max envelope, pointwise alpha={alpha:.3f})")
        state = np.select([t["L"] > t["env_high"], t["L"] < t["env_low"]],
                          ["clustered", "dispersed"], default="CSR")
        print(t.assign(state=state).to_string(index=False, float_format=lambda v: f"{v:.1f}"))


def _l(xy: np.ndarray, d: np.ndarray, area: float) -> np.ndarray:
    n = len(xy)
    tree = cKDTree(xy)
    pairs = tree.count_neighbors(tree, d, cumulative=True).astype(float) - n   # drop i == i
    return np.sqrt(area * pairs / (n * (n - 1)) / np.pi)


def ripley_l(points: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, *, distances_m,
             n_simulations: int = 99, seed: int = 42, sample: int | None = None) -> RipleyResult:
    """Besag's L(d) of ``points`` inside ``boundary`` with a CSR min/max envelope.

    Only points inside the (dissolved) boundary are used; A is its area.
    ``sample`` draws a seeded random subsample of that many points first
    (without replacement) — the envelope is simulated at the same n. Use it on
    the full ~108k crime points: cost grows with the number of pairs within
    the largest distance, per simulation. Coincident points (stacked
    geocodes) are pairs at distance 0 and count at every d.
    """
    d = np.asarray(sorted(distances_m), dtype=float)
    if (d <= 0).any():
        raise ValueError("distances_m must be positive")
    region = window(boundary)
    xy = coords_in(points, region, sample=sample, seed=seed)
    n, area = len(xy), region.area
    if n < 2:
        raise ValueError("need at least two points inside the boundary")
    rng = np.random.default_rng(seed)
    obs = _l(xy, d, area)
    sims = np.vstack([_l(csr(region, n, rng), d, area) for _ in range(n_simulations)])
    table = pd.DataFrame({"distance_m": d, "L": obs, "L_minus_d": obs - d,
                          "env_low": sims.min(axis=0), "env_high": sims.max(axis=0)})
    return RipleyResult(
        table=table, n_points=n, area_km2=area / 1e6, n_simulations=n_simulations,
        meta=ResultMeta(method="Ripley's L", reference=REFERENCE,
                        params=dict(distances_m=d.tolist(), n_simulations=n_simulations, seed=seed,
                                    sample=sample, edge_correction="none", envelope="min/max")),
    )
