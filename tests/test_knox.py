"""Knox space-time interaction test + near-repeat table — synthetic events, no DB."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest

from crime.stats.knox import knox_table, knox_test

T0 = pd.Timestamp("2022-01-01")


def _background(n, rng, extent=5000.0, days=365):
    return pd.DataFrame({"x": rng.uniform(0, extent, n), "y": rng.uniform(0, extent, n),
                         "date": T0 + pd.to_timedelta(rng.integers(0, days, n), unit="D")})


def _clustered(rng, n_bg=600, n_seeds=40, per_seed=5):
    """Background + near-repeat bursts: each seed spawns events within 50 m and 5 days."""
    bg = _background(n_bg, rng)
    sx, sy = rng.uniform(0, 5000, n_seeds), rng.uniform(0, 5000, n_seeds)
    sd = rng.integers(0, 360, n_seeds)
    k = np.repeat(np.arange(n_seeds), per_seed)
    burst = pd.DataFrame({"x": sx[k] + rng.uniform(-35, 35, len(k)),
                          "y": sy[k] + rng.uniform(-35, 35, len(k)),
                          "date": T0 + pd.to_timedelta(sd[k] + rng.integers(0, 5, len(k)), unit="D")})
    return pd.concat([bg, burst], ignore_index=True)


def test_detects_planted_space_time_clusters():
    ev = _clustered(np.random.default_rng(0))
    r = knox_test(ev, space_m=100, time_days=7, permutations=199)
    assert r.ratio > 2 and r.p_value < 0.05
    assert r.observed > r.expected and r.n_events == len(ev)


def test_independent_times_ratio_near_one_and_p_uniform():
    ps, ratios = [], []
    for s in range(30):
        rng = np.random.default_rng(100 + s)
        ev = _background(800, rng)
        r = knox_test(ev, space_m=300, time_days=14, permutations=99, seed=s)
        ps.append(r.p_value)
        ratios.append(r.ratio)
    assert abs(np.mean(ratios) - 1) < 0.05
    from scipy.stats import kstest
    assert kstest(ps, "uniform").pvalue > 0.01
    assert np.mean(np.array(ps) < 0.05) < 0.2


def test_matches_brute_force_count():
    rng = np.random.default_rng(5)
    ev = _clustered(rng, n_bg=150, n_seeds=10)
    r = knox_test(ev, space_m=120, time_days=3, permutations=9)
    xy, d = ev[["x", "y"]].to_numpy(), (ev["date"] - ev["date"].min()).dt.days.to_numpy()
    dist = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
    close = (dist <= 120) & (np.abs(d[:, None] - d[None, :]) <= 3)
    assert r.observed == int(np.triu(close, 1).sum())


def test_geodataframe_input_and_sample():
    ev = _clustered(np.random.default_rng(1))
    gdf = gpd.GeoDataFrame({"date": ev["date"]}, geometry=gpd.points_from_xy(ev.x, ev.y),
                           crs="EPSG:31983").to_crs("EPSG:4326")
    a = knox_test(ev, space_m=100, time_days=7, permutations=49)
    b = knox_test(gdf, space_m=100, time_days=7, permutations=49)
    assert a.observed == b.observed
    c = knox_test(ev, space_m=100, time_days=7, permutations=49, sample=300)
    assert c.n_events == 300


def test_table_shape_and_band_semantics():
    # four events on a line, 1 day apart in time, 100 m apart in space
    ev = pd.DataFrame({"x": [0.0, 100.0, 200.0, 350.0], "y": 0.0,
                       "date": T0 + pd.to_timedelta([0, 1, 2, 10], unit="D")})
    tab = knox_table(ev, space_bands_m=[100, 200], time_bands_days=[1, 2, 7], permutations=19)
    assert tab["ratio"].shape == (2, 3)
    assert list(tab.columns.get_level_values(0).unique()) == ["observed", "expected", "ratio", "p"]
    obs = tab["observed"].to_numpy()
    # pairs: (0,1) 100 m/1 d -> [0,100]x[0,1]; (1,2) same; (0,2) 200 m/2 d -> (100,200]x(1,2];
    # (2,3) 150 m/8 d -> beyond last time band; (1,3) 250 m -> beyond space bands
    assert obs.tolist() == [[2, 0, 0], [0, 1, 0]]
    assert tab.index[0] == "[0, 100] m" and tab.index[1] == "(100, 200] m"


def test_table_agrees_with_knox_test_first_cell():
    ev = _clustered(np.random.default_rng(2))
    tab = knox_table(ev, space_bands_m=[100, 200], time_bands_days=[7, 14], permutations=99)
    r = knox_test(ev, space_m=100, time_days=7, permutations=99)
    assert tab["observed"].iloc[0, 0] == r.observed
    assert tab["expected"].iloc[0, 0] == pytest.approx(r.expected)
    assert tab["p"].iloc[0, 0] == pytest.approx(r.p_value)
    assert tab["ratio"].iloc[0, 0] > 2 and tab["p"].iloc[0, 0] < 0.05


def test_bad_bands_raise():
    ev = _background(20, np.random.default_rng(0))
    with pytest.raises(ValueError):
        knox_table(ev, space_bands_m=[200, 100], time_bands_days=[7], permutations=9)


def test_fractional_times_take_the_float_path():
    ev = pd.DataFrame({"x": [0.0, 100.0, 200.0, 350.0], "y": 0.0, "date": [0.0, 1.5, 2.0, 10.0]})
    tab = knox_table(ev, space_bands_m=[100, 200], time_bands_days=[1, 2, 7], permutations=19)
    # (0,1) 100 m / 1.5 d -> (1,2]; (1,2) 100 m / 0.5 d -> [0,1]; (0,2) 200 m / 2 d -> (1,2]
    assert tab["observed"].to_numpy().tolist() == [[1, 1, 0], [0, 1, 0]]
