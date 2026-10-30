"""STL decomposition and Time Series Clustering on planted synthetic series — no DB."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from crime.core.dataset import Dataset
from crime.esri.tsclust import time_series_clustering
from crime.stats.eda import _stl, stl_decompose, temporal_trends

MONTHS = pd.date_range("2022-01-01", periods=48, freq="MS")
SEASON = 20 * np.sin(2 * np.pi * np.arange(48) / 12)


def test_stl_recovers_planted_seasonal():
    rng = np.random.default_rng(0)
    trend = 500 + 2.0 * np.arange(48)
    s = pd.Series(trend + SEASON + rng.normal(scale=2, size=48), index=MONTHS)
    out = stl_decompose(s, period=12)
    assert list(out.columns) == ["observed", "trend", "seasonal", "resid"]
    np.testing.assert_allclose(out.observed, out.trend + out.seasonal + out.resid)
    assert np.corrcoef(out.seasonal, SEASON)[0, 1] > 0.95
    assert np.abs(out.seasonal - SEASON).max() < 8
    assert np.abs(out.trend - trend).max() < 8


def test_stl_robust_to_one_outlier():
    s = pd.Series(500 + SEASON, index=MONTHS)
    s.iloc[20] += 400
    out = stl_decompose(s, period=12, robust=True)
    assert np.corrcoef(out.seasonal, SEASON)[0, 1] > 0.95
    assert out.resid.iloc[20] > 300                    # the outlier stays in the residual


def test_stl_rejects_short_or_nan():
    with pytest.raises(ValueError):
        stl_decompose(pd.Series(np.ones(20)), period=12)
    s = pd.Series(500 + SEASON, index=MONTHS)
    s.iloc[3] = np.nan
    with pytest.raises(ValueError):
        stl_decompose(s)


def test_internal_stl_fills_empty_months_with_zero():
    s = pd.Series(100 + SEASON, index=MONTHS).drop(MONTHS[[5, 6]])   # two months with no events
    out = _stl(s, "ME")
    assert len(out["observed"]) == 48 and out["observed"].iloc[5] == 0


def test_temporal_trends_uses_robust_monthly_stl():
    rng = np.random.default_rng(1)
    counts = np.round(100 + SEASON + rng.normal(scale=3, size=48)).astype(int)
    dates = np.repeat(MONTHS + pd.Timedelta(days=10), counts)
    ev = pd.DataFrame({"data_ocorrencia": dates, "hora_ocorrencia": "12:00:00", "unit_id": 0})
    gdf = gpd.GeoDataFrame({"unit_id": [0]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:31983")
    tr = temporal_trends(Dataset(gdf, "grid", events=ev), freq="ME")
    assert tr.stl is not None and len(tr.stl["seasonal"]) == 48
    assert np.corrcoef(tr.stl["seasonal"], SEASON)[0, 1] > 0.9


class _Cube:
    """Minimal stand-in for a CubeResult: ``.wide`` (unit x period) + ``.gdf``."""

    def __init__(self, wide):
        self.wide = wide
        self.gdf = gpd.GeoDataFrame({"unit_id": wide.index},
                                    geometry=[box(i, 0, i + 1, 1) for i in range(len(wide))],
                                    crs="EPSG:31983")
        self.freq = "ME"


def _two_profiles(rng, n=30):
    """Group A peaks in summer months, group B in winter (opposite phase), with
    random levels so 'profile' must ignore level."""
    a = 1 + np.sin(2 * np.pi * np.arange(48) / 12)
    b = 1 - np.sin(2 * np.pi * np.arange(48) / 12)
    lv = rng.uniform(5, 50, 2 * n)
    rows = [lv[i] * (a if i < n else b) + rng.normal(scale=0.5, size=48) for i in range(2 * n)]
    truth = np.r_[np.zeros(n), np.ones(n)]
    return _Cube(pd.DataFrame(np.clip(rows, 0, None), index=range(2 * n), columns=MONTHS)), truth


def _agree(labels, truth):
    from sklearn.metrics import adjusted_rand_score
    return adjusted_rand_score(truth, labels)


def test_tsc_profile_separates_two_planted_profiles():
    cube, truth = _two_profiles(np.random.default_rng(0))
    res = time_series_clustering(cube, method="profile")              # k chosen by pseudo-F
    assert res.k == 2
    assert _agree(res.gdf["cluster"], truth) == 1.0
    assert res.scores.idxmax() == 2 and res.profiles.shape == (2, 48)


def test_tsc_value_groups_by_level():
    rng = np.random.default_rng(1)
    rows = np.r_[rng.normal(5, 0.5, (20, 48)), rng.normal(40, 0.5, (20, 48))]
    cube = _Cube(pd.DataFrame(rows, columns=MONTHS))
    res = time_series_clustering(cube, method="value", k=2)
    assert _agree(res.gdf["cluster"], np.r_[np.zeros(20), np.ones(20)]) == 1.0
    assert res.gdf["cluster"].iloc[0] == 0                            # 0 = quietest


def test_tsc_min_total_excludes_units():
    cube, _ = _two_profiles(np.random.default_rng(2))
    cube.wide.iloc[:3] = 0
    res = time_series_clustering(cube, method="profile", k=2, min_total=1)
    assert (res.gdf["cluster"].iloc[:3] == -1).all()


def test_feature_correlation_any_unit_kind_excludes_id():
    from crime.stats.correlation import feature_correlation

    rng = np.random.default_rng(0)
    for unit in ("sector", "grid"):
        g = gpd.GeoDataFrame({"unit_id": range(40), "crime_count": rng.poisson(5, 40),
                              "log_pop_density": rng.normal(size=40)},
                             geometry=[box(i, 0, i + 1, 1) for i in range(40)], crs="EPSG:31983")
        cols = ["log_pop_density"]
        r = feature_correlation(Dataset(g, unit, years=(2022, 2022)))
        assert r.method == "spearman" and "unit_id" not in r.target_corr.index
        feature_correlation(Dataset(g, unit, years=(2022, 2022)), cols=cols)
        assert cols == ["log_pop_density"]                   # caller's list not mutated
