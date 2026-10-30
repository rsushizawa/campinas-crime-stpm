"""Bivariate Moran's I (global + local) on a synthetic lattice — no DB."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from crime.core.dataset import Dataset
from crime.esri.weights import spatial_weights
from crime.stats.bivariate import bivariate_matrix, bivariate_moran, local_bivariate_moran

N = 15                                   # 15 x 15 lattice of 100 m cells


def _lattice(**cols) -> Dataset:
    geoms = [box(c * 100, r * 100, (c + 1) * 100, (r + 1) * 100) for r in range(N) for c in range(N)]
    gdf = gpd.GeoDataFrame({"unit_id": range(N * N), **cols}, geometry=geoms, crs="EPSG:31983")
    return Dataset(gdf, "grid")


def _smooth_pair(seed=0):
    """x = smoothed noise; y = x + small noise, so lag(y) tracks x."""
    rng = np.random.default_rng(seed)
    ds0 = _lattice(z=rng.normal(size=N * N))
    w = spatial_weights(ds0.metric(), kind="queen")
    x = rng.normal(size=N * N)
    for _ in range(3):
        x = x + w.sparse @ x                 # spatial smoothing -> autocorrelated field
    y = x + 0.3 * x.std() * rng.normal(size=N * N)
    return x, y


def test_positive_when_lag_y_tracks_x():
    x, y = _smooth_pair()
    res = bivariate_moran(_lattice(x=x, y=y), "x", "y", permutations=199)
    assert res.I > 0.5 and res.p_sim < 0.01 and res.z_sim > 3
    assert abs(res.expected) < 0.05


def test_near_zero_for_independent_fields():
    rng = np.random.default_rng(1)
    res = bivariate_moran(_lattice(x=rng.normal(size=N * N), y=rng.normal(size=N * N)),
                          "x", "y", permutations=199)
    assert abs(res.I) < 0.15 and res.p_sim > 0.01


def test_seed_reproducible_and_global_rng_untouched():
    x, y = _smooth_pair()
    ds = _lattice(x=x, y=y)
    np.random.seed(7)
    before = np.random.random()
    np.random.seed(7)
    a = bivariate_moran(ds, "x", "y", permutations=99, seed=3)
    assert np.random.random() == before
    b = bivariate_moran(ds, "x", "y", permutations=99, seed=3)
    assert a.p_sim == b.p_sim and a.z_sim == b.z_sim


def test_rook_and_knn_weights():
    x, y = _smooth_pair()
    ds = _lattice(x=x, y=y)
    for kind in ("rook", "knn"):
        assert bivariate_moran(ds, "x", "y", weights=kind, permutations=99).I > 0.3


def test_local_quadrants():
    """x high on the left half, y high on the left half -> HH left, LL right."""
    cols = np.tile(np.arange(N), N)
    left = cols < N // 2
    rng = np.random.default_rng(2)
    x = np.where(left, 10.0, 0.0) + rng.normal(scale=0.1, size=N * N)
    y = np.where(left, 10.0, 0.0) + rng.normal(scale=0.1, size=N * N)
    res = local_bivariate_moran(_lattice(x=x, y=y), "x", "y", permutations=199)
    lab = res.gdf["label"].to_numpy()
    deep_left, deep_right = cols <= 3, cols >= N - 4
    assert (lab[deep_left] == "HH").mean() > 0.8
    assert (lab[deep_right] == "LL").mean() > 0.8
    assert set(lab) <= {"HH", "LH", "LL", "HL", "ns"}
    # x high where lag(y) is low -> HL
    res2 = local_bivariate_moran(_lattice(x=x, y=-y), "x", "y", permutations=199)
    assert (res2.gdf["label"].to_numpy()[deep_left] == "HL").mean() > 0.8


def test_local_constant_column_is_no_data():
    rng = np.random.default_rng(3)
    with np.errstate(all="ignore"):
        res = local_bivariate_moran(_lattice(x=np.zeros(N * N), y=rng.normal(size=N * N)),
                                    "x", "y", permutations=99)
    assert (res.gdf["label"] == "no data").all()


def test_matrix_all_ordered_pairs_and_asymmetry():
    x, y = _smooth_pair()
    rng = np.random.default_rng(4)
    ds = _lattice(x=x, y=y, z=rng.normal(size=N * N))
    m = bivariate_matrix(ds, ["x", "y", "z"], permutations=99)
    assert len(m) == 6 and set(zip(m.x, m.y)) == {(a, b) for a in "xyz" for b in "xyz" if a != b}
    assert {"I", "expected", "z_sim", "p_sim", "spearman", "n"} <= set(m.columns)
    xy = m.set_index(["x", "y"])
    assert xy.loc[("x", "y"), "spearman"] == pytest.approx(xy.loc[("y", "x"), "spearman"])
    assert xy.loc[("x", "y"), "I"] != pytest.approx(xy.loc[("y", "x"), "I"], abs=1e-9)
