"""Known-answer checks for the core inference (Esri defaults) and the weights factory.

* Gi* — analytic z (general-weights variance), two-sided normal p, BH FDR:
  a dense block on an empty lattice is hot; a constant field has no labels.
* Local Moran's I — esda conditional permutation, 499 permutations by default.
* Global Moran's I — permutation p plus the analytic ``p_norm``.
* EHSA — the same analytic Gi* per slice; a block that is hot in every slice
  is a persistent hot spot.
* Weights — queen / rook / knn neighbour counts on a 3x3 lattice.

All synthetic; no database.
"""
from __future__ import annotations

import contextlib
import inspect
import io

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from crime.core.dataset import Dataset
from crime.esri import ehsa, local, moran, stlisa
from crime.esri.weights import spatial_weights

LISA_LABELS = {"HH", "LL", "HL", "LH", "ns"}


def _lattice(n: int, values=None) -> gpd.GeoDataFrame:
    """n x n unit squares, row-major, ids u0..u{n*n-1} (metric CRS)."""
    cells = [box(c, r, c + 1, r + 1) for r in range(n) for c in range(n)]
    gdf = gpd.GeoDataFrame({"unit_id": [f"u{i}" for i in range(n * n)]},
                           geometry=cells, crs="EPSG:31983")
    gdf["crime_count"] = 0.0 if values is None else np.asarray(values, dtype=float)
    return gdf


def _block(n: int, rows, cols, value: float = 10.0) -> np.ndarray:
    grid = np.zeros((n, n))
    grid[np.ix_(rows, cols)] = value
    return grid.ravel()


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


# --------------------------------------------------------------------------- #
#  weights factory
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind,expected", [
    # 3x3 lattice, row-major: corners 0,2,6,8 · edges 1,3,5,7 · centre 4
    ("queen", [3, 5, 3, 5, 8, 5, 3, 5, 3]),
    ("rook", [2, 3, 2, 3, 4, 3, 2, 3, 2]),
])
def test_contiguity_neighbour_counts(kind, expected):
    w = spatial_weights(_lattice(3), kind=kind)
    assert [w.cardinalities[i] for i in range(9)] == expected
    assert w.transform.upper() == "R"
    np.testing.assert_allclose([sum(w.weights[i]) for i in range(9)], 1.0)


def test_knn_neighbour_counts():
    w = spatial_weights(_lattice(3), kind="knn", k=4)
    assert all(w.cardinalities[i] == 4 for i in range(9))
    assert set(w.neighbors[4]) == {1, 3, 5, 7}          # the four rook neighbours at distance 1
    np.testing.assert_allclose([sum(w.weights[i]) for i in range(9)], 1.0)


def test_unknown_weights_kind_is_rejected():
    with pytest.raises(ValueError, match="queen, rook, knn"):
        spatial_weights(_lattice(3), kind="network")


# --------------------------------------------------------------------------- #
#  Getis-Ord Gi* — analytic
# --------------------------------------------------------------------------- #
def test_gi_star_has_no_permutation_parameters():
    for fn in (local.getis_ord_gi, ehsa.gi_time_series, ehsa.gi_space_time, ehsa.emerging_hotspots):
        params = inspect.signature(fn).parameters
        assert not {"permutations", "seed", "tie_rule"} & set(params), fn.__name__


def test_gi_star_dense_cluster_is_hot():
    n = 10
    gdf = _lattice(n, _block(n, [3, 4, 5], [3, 4, 5]))
    res = _quiet(local.getis_ord_gi, Dataset(gdf, "sector"), weights="queen")
    labels = res.gdf.set_index("unit_id")["label"]
    assert labels["u44"] == "hotspot"                   # centre of the 3x3 block
    assert set(labels[[f"u{r * n + c}" for r in (3, 4, 5) for c in (3, 4, 5)]]) == {"hotspot"}
    assert labels["u0"] != "hotspot" and "coldspot" not in set(labels)
    # p is the two-sided normal p of the analytic z
    from scipy.stats import norm
    np.testing.assert_allclose(res.gdf["p_value"], 2 * norm.sf(np.abs(res.gdf["gi_z"])))
    assert res.meta.params["inference"] == "analytic"


def test_gi_star_constant_field_has_no_labels():
    gdf = _lattice(5)
    gdf["crime_count"] = 3.0
    res = _quiet(local.getis_ord_gi, Dataset(gdf, "sector"), weights="queen")
    assert not res.gdf["label"].isin(["hotspot", "coldspot"]).any()
    assert not res.gdf["significant"].any()


def test_gi_star_is_deterministic():
    rng = np.random.default_rng(1)
    gdf = _lattice(6, rng.poisson(2.0, 36))
    a = _quiet(local.getis_ord_gi, Dataset(gdf, "sector"))
    b = _quiet(local.getis_ord_gi, Dataset(gdf, "sector"))
    np.testing.assert_array_equal(a.gdf["p_value"], b.gdf["p_value"])


def test_ehsa_block_hot_in_every_slice_is_persistent():
    n, T = 10, 12
    gdf = _lattice(n)
    base = _block(n, [3, 4, 5], [3, 4, 5])
    matrix = pd.DataFrame(np.repeat(base[:, None], T, axis=1), index=gdf["unit_id"],
                          columns=pd.date_range("2022-01-31", periods=T, freq="ME"))
    res = _quiet(ehsa.emerging_hotspots, Dataset(gdf, "sector"), matrix=matrix, freq="ME")
    cat = res.gdf.set_index("unit_id")["category"]
    assert cat["u44"] == "persistent hotspot"
    assert res.specification["inference"] == "analytic"


# --------------------------------------------------------------------------- #
#  Local Moran's I — 499 conditional permutations
# --------------------------------------------------------------------------- #
def _two_halves(n: int = 10) -> np.ndarray:
    """High left half, low right half, one low cell inside the high half (LH)
    and one high cell inside the low half (HL)."""
    grid = np.zeros((n, n))
    grid[:, : n // 2] = 10.0
    grid[4, 2] = 0.0          # low among highs   -> LH quadrant
    grid[4, 7] = 10.0         # high among lows   -> HL quadrant
    return grid.ravel()


def test_lisa_default_is_499_permutations():
    assert inspect.signature(local.local_moran).parameters["permutations"].default == 499
    assert inspect.signature(stlisa.space_time_lisa).parameters["permutations"].default == 499
    assert "tie_rule" not in inspect.signature(local.local_moran).parameters


def test_lisa_quadrants_and_labels():
    gdf = _lattice(10, _two_halves())
    res = _quiet(local.local_moran, Dataset(gdf, "sector"), weights="queen")
    assert res.meta.params["permutations"] == 499
    assert set(res.gdf["quadrant"]) == {"HH", "LL", "HL", "LH"}
    assert set(res.gdf["label"]) <= LISA_LABELS
    q = res.gdf.set_index("unit_id")["quadrant"]
    assert q["u42"] == "LH" and q["u47"] == "HL"
    labels = set(res.gdf["label"])
    assert {"HH", "LL"} <= labels and "ns" in labels
    p = res.gdf["p_value"]
    assert ((p >= 1 / 500) & (p <= 1)).all()           # esda p_sim = (k + 1) / (499 + 1)


def test_lisa_seed_reproduces():
    gdf = _lattice(10, _two_halves())
    a = _quiet(local.local_moran, Dataset(gdf, "sector"), seed=7)
    b = _quiet(local.local_moran, Dataset(gdf, "sector"), seed=7)
    np.testing.assert_array_equal(a.gdf["p_value"], b.gdf["p_value"])


# --------------------------------------------------------------------------- #
#  Global Moran's I
# --------------------------------------------------------------------------- #
def test_global_moran_reports_permutation_and_analytic_p():
    gdf = _lattice(10, _two_halves())
    res = _quiet(moran.global_moran, Dataset(gdf, "sector"), permutations=999)
    assert res.I > 0.5 and res.significant
    assert res.p_sim < 0.01 and res.p_norm < 1e-6 and res.z_norm > 0
