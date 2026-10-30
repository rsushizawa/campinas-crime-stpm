"""Point-pattern methods (crime.points) on synthetic patterns — no DB, no real data."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from crime.core.config import CRS_METRIC
from crime.points.kde import kde_surface
from crime.points.nni import nearest_neighbour_index
from crime.points.ripley import ripley_l

SIDE = 2_000.0
BOUNDARY = gpd.GeoDataFrame(geometry=[box(0, 0, SIDE, SIDE)], crs=CRS_METRIC)


def _pts(xy):
    return gpd.GeoDataFrame(geometry=gpd.points_from_xy(xy[:, 0], xy[:, 1]), crs=CRS_METRIC)


def _csr(n=400, seed=1):
    return _pts(np.random.default_rng(seed).uniform(0, SIDE, size=(n, 2)))


def _clustered(n=400, seed=2):
    """Thomas-like process: 8 parents, offspring N(parent, 40 m), kept inside the square."""
    rng = np.random.default_rng(seed)
    parents = rng.uniform(300, SIDE - 300, size=(8, 2))
    xy = parents[rng.integers(0, 8, n)] + rng.normal(0, 40, size=(n, 2))
    return _pts(np.clip(xy, 1, SIDE - 1))


DIST = np.arange(50, 401, 50)


def test_ripley_csr_inside_envelope():
    r = ripley_l(_csr(), BOUNDARY, distances_m=DIST, n_simulations=99, seed=7)
    t = r.table
    assert list(t.columns) == ["distance_m", "L", "L_minus_d", "env_low", "env_high"]
    assert ((t["L"] >= t["env_low"]) & (t["L"] <= t["env_high"])).mean() >= 0.75
    assert np.allclose(t["L_minus_d"], t["L"] - t["distance_m"])
    assert r.n_points == 400


def test_ripley_clustered_above_envelope():
    r = ripley_l(_clustered(), BOUNDARY, distances_m=DIST, n_simulations=39, seed=7)
    assert r.clustered.all()
    assert (r.table["L_minus_d"] > 0).all()


def test_ripley_sample_and_validation():
    r = ripley_l(_csr(n=1000), BOUNDARY, distances_m=[100], n_simulations=9, sample=200)
    assert r.n_points == 200
    with pytest.raises(ValueError):
        ripley_l(_csr(), BOUNDARY, distances_m=[0, 100], n_simulations=9)


def test_ripley_ignores_points_outside_boundary():
    pts = _pts(np.vstack([np.random.default_rng(3).uniform(0, SIDE, (200, 2)), [[5e4, 5e4]]]))
    assert ripley_l(pts, BOUNDARY, distances_m=[100], n_simulations=9).n_points == 200


def test_nni_clustered_and_csr():
    clu = nearest_neighbour_index(_clustered(), BOUNDARY)
    assert clu.ratio < 0.6 and clu.z < -5 and clu.p < 1e-6
    ratios = [nearest_neighbour_index(_csr(n=1000, seed=s), BOUNDARY).ratio for s in range(5)]
    # no edge correction -> CSR sits slightly above 1 (Clark & Evans' known boundary bias)
    assert 0.95 < np.mean(ratios) < 1.1
    assert nearest_neighbour_index(_csr(), BOUNDARY).expected_m == pytest.approx(0.5 / np.sqrt(400 / SIDE**2))


@pytest.mark.parametrize("kernel", ["quartic", "gaussian"])
def test_kde_integrates_to_n(kernel):
    rng = np.random.default_rng(4)
    xy = rng.uniform(700, 1300, size=(300, 2))          # well inside: no mass lost at the edge
    k = kde_surface(_pts(xy), BOUNDARY, cell_m=20, bandwidth_m=100, kernel=kernel)
    assert k.total == pytest.approx(300, rel=0.01)
    assert k.density.shape == (100, 100)
    assert k.extent == (0, SIDE, 0, SIDE)
    assert np.nanmax(k.density) > 0 and np.nanmin(k.density) >= 0


def test_kde_mask_default_bandwidth_and_units():
    from crime.data.units import tessellation

    tri = gpd.GeoDataFrame(geometry=[box(0, 0, SIDE, SIDE).difference(box(SIDE / 2, SIDE / 2, SIDE, SIDE))],
                           crs=CRS_METRIC)
    k = kde_surface(_clustered(), tri, cell_m=50)
    assert np.isnan(k.density[0, -1])                     # NE quadrant (north row, east col) masked
    assert not np.isnan(k.density[-1, 0])
    assert 0 < k.bandwidth_m < SIDE
    units = tessellation(tri, shape="square", area_km2=0.25)
    m = k.mean_by_unit(units)
    assert list(m.index) == units["unit_id"].tolist() and m.notna().all()
