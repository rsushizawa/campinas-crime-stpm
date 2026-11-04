"""Spatial supports and the notebook data API on synthetic data — no DB, no real files.

The last test checks the real counts when ``outputs/data/bulletins_clean.parquet``
exists (skipped otherwise)."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

from crime.core.config import BULLETINS_PARQUET, CRS_METRIC, CRS_WGS84
from crime.data import api
from crime.data.units import assign_nearest, assign_points

X0, Y0 = 280_000.0, 7_460_000.0          # somewhere in UTM 23S (Campinas-ish)
SIDE = 4_000.0                           # 4 km x 4 km study square


def _squares(side=SIDE, cell=1000.0, x0=X0, y0=Y0):
    """Square cells of ``cell`` metres covering a ``side`` x ``side`` box (row-major ids)."""
    n = int(side // cell)
    polys = [box(x0 + i * cell, y0 + j * cell, x0 + (i + 1) * cell, y0 + (j + 1) * cell)
             for j in range(n) for i in range(n)]
    return gpd.GeoDataFrame({"unit_id": [f"S{k:03d}" for k in range(len(polys))]},
                            geometry=polys, crs=CRS_METRIC)


# ------------------------------------------------------------------ assign_points
def test_assign_points_edges_and_outside():
    units = _squares()
    pts = gpd.GeoDataFrame(geometry=[
        Point(X0 + 500, Y0 + 500),          # inside the first cell
        Point(X0 + 1000, Y0 + 500),         # on an edge shared by two cells
        Point(X0 + 1000, Y0 + 1000),        # on a corner shared by four cells
        Point(X0 - 10, Y0 - 10),            # outside
        Point(X0 + SIDE, Y0 + 200),         # on the outer boundary
    ], index=[10, 11, 12, 13, 14], crs=CRS_METRIC)
    out = assign_points(pts, units)
    assert list(out.index) == [10, 11, 12, 13, 14]
    assert pd.isna(out[13])
    assert out.drop(13).notna().all()
    # shared edge / corner -> the first unit (row order) touching the point
    touching = units[units.intersects(pts.geometry[11])]
    assert out[11] == touching["unit_id"].iloc[0]
    touching = units[units.intersects(pts.geometry[12])]
    assert len(touching) == 4 and out[12] == touching["unit_id"].iloc[0]
    # deterministic; points in another CRS are reprojected first
    assert out.equals(assign_points(pts, units))
    assert assign_points(pts.to_crs(CRS_WGS84), units)[10] == out[10]


def test_assign_points_empty():
    units = _squares()
    out = assign_points(gpd.GeoDataFrame(geometry=[], crs=CRS_METRIC), units)
    assert out.empty


def test_assign_nearest_fills_slivers():
    units = _squares(side=2000.0)
    units = units.assign(geometry=units.geometry.buffer(-5))          # 10 m slivers between cells
    pts = gpd.GeoDataFrame(geometry=[Point(X0 + 500, Y0 + 500), Point(X0 + 997, Y0 + 500),
                                     Point(X0 + 9000, Y0 + 9000)], crs=CRS_METRIC)
    assert assign_points(pts, units).isna().tolist() == [False, True, True]
    out = assign_nearest(pts, units, max_distance_m=100)
    assert out[0] == out[1] == "S000" and pd.isna(out[2])
    assert assign_nearest(pts, units).notna().all()


# ------------------------------------------------------------------ data API
# synthetic cleaned bulletins
def _bulletins(n=1500, seed=0):
    """Synthetic cleaned-bulletin rows: a hot corner + background, 2022-2023."""
    rng = np.random.default_rng(seed)
    hot = np.clip(rng.normal([X0 + 800, Y0 + 800], 250, size=(n // 2, 2)), [X0 + 1, Y0 + 1], None)
    bg = rng.uniform([X0, Y0], [X0 + SIDE, Y0 + SIDE], size=(n - n // 2, 2))
    xy = np.vstack([hot, bg])
    ll = gpd.GeoSeries(gpd.points_from_xy(xy[:, 0], xy[:, 1]), crs=CRS_METRIC).to_crs(CRS_WGS84)
    days = rng.integers(0, 730, n)
    df = pd.DataFrame({
        "LATITUDE": ll.y.to_numpy(), "LONGITUDE": ll.x.to_numpy(),
        "DATA_OCORRENCIA_BO": pd.Timestamp("2022-01-01") + pd.to_timedelta(days, unit="D"),
        "HORA_OCORRENCIA_BO": "12:00", "DESC_PERIODO": "A tarde",
        "NUM_BO": [str(i) for i in range(n)], "ANO_BO": 2022, "NOME_DELEGACIA": "DP",
        "crime_slug": np.where(rng.random(n) < 0.7, "furto_outros", "lesao_corporal_dolosa"),
    })
    df["crime_group"] = np.where(df["crime_slug"] == "furto_outros", "property", "bodily_harm")
    # rows that must be dropped: no coordinates, outside the window, outside the units
    extra = df.iloc[:3].copy()
    extra.loc[extra.index[0], ["LATITUDE", "LONGITUDE"]] = np.nan
    extra.loc[extra.index[1], "DATA_OCORRENCIA_BO"] = pd.Timestamp("2021-06-01")
    far = gpd.GeoSeries([Point(X0 - 5000, Y0 - 5000)], crs=CRS_METRIC).to_crs(CRS_WGS84)
    extra.loc[extra.index[2], ["LATITUDE", "LONGITUDE"]] = [far.y[0], far.x[0]]
    out = pd.concat([df, extra], ignore_index=True)
    out.loc[n:, "NUM_BO"] = ["x0", "x1", "x2"]
    return out


def _with_tracts(b, units):
    """Stage 02's tract join on the synthetic rows (cd_setor = containing unit)."""
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(b["LONGITUDE"], b["LATITUDE"]),
                           index=b.index, crs=CRS_WGS84)
    return b.assign(cd_setor=assign_points(pts, units).astype("string"))


@pytest.fixture(scope="module")
def synthetic():
    units = _squares()
    b = _with_tracts(_bulletins(), units)
    return units, b, api.points_from_bulletins(b, utbs=units)


def test_points_from_bulletins(synthetic):
    units, b, pts = synthetic
    assert len(pts) == len(b) - 3                       # no coords / before 2022 / outside the mesh
    assert pts.crs == CRS_METRIC and pts["event_id"].is_unique
    assert (pts["utb"] == pts["cd_setor"]).all()        # same mesh -> same unit
    assert (pts["month"] == pts["date"].dt.to_period("M").dt.to_timestamp()).all()
    assert (pts["datetime"] - pts["date"] == pd.Timedelta(hours=12)).all()
    assert set(pts["group"]) == {"property", "bodily_harm"}


def test_unit_counts_zero_filled(synthetic, monkeypatch):
    units, _, pts = synthetic
    monkeypatch.setattr(api, "load_points", lambda g="all": pts if g == "all" else pts[pts["group"] == g])
    monkeypatch.setattr(api, "unit_polygons", lambda s: units)
    for s in ("tract", "utb"):
        c = api.unit_counts(s, "all")
        assert list(c.index) == list(units["unit_id"]) and c.sum() == len(pts)
        m = api.unit_counts(s, "property", freq="M")
        assert m.shape == (len(units), 48) and m.values.sum() == (pts["group"] == "property").sum()
        assert m.columns[0] == pd.Timestamp("2022-01-01") and m.columns[-1] == pd.Timestamp("2025-12-01")
        assert (m.loc[:, "2024-01-01":] == 0).all().all()                 # synthetic data ends 2023
        assert api.unit_counts(s, "all", freq="Q").shape == (len(units), 16)
    with pytest.raises(ValueError):
        api.unit_counts("hexagon")
    with pytest.raises(ValueError):
        api.unit_counts("tract", "sexual")
    with pytest.raises(ValueError):
        api.unit_counts("tract", freq="W")


def test_groups_match_taxonomy():
    from etl.taxonomy import CRIME_GROUPS

    assert set(api.GROUPS) - {"all"} <= set(CRIME_GROUPS)


@pytest.mark.skipif(not BULLETINS_PARQUET.exists(), reason="needs outputs/data/bulletins_clean.parquet")
def test_real_counts_agree_across_supports():
    pts = api.load_points()
    assert len(pts) == 107_859 and len(api.load_points("property")) == 90_436
    assert pts["utb"].notna().all()
    for s, n in (("tract", 2_592), ("utb", 93)):
        assert len(api.unit_polygons(s)) == n
        assert api.unit_counts(s).sum() == len(pts)
        assert api.unit_counts(s, freq="M").values.sum() == len(pts)


# ------------------------------------------------------------------ areal interpolation
def test_areal_interpolate_splits_by_area_share():
    from crime.data.units import areal_interpolate

    # two 1 km x 2 km source rectangles, values 100 and 40; targets: 2 x 2 squares of 1 km
    src = gpd.GeoDataFrame({"unit_id": ["a", "b"], "pop": [100.0, 40.0]},
                           geometry=[box(X0, Y0, X0 + 1000, Y0 + 2000),
                                     box(X0 + 1000, Y0, X0 + 2000, Y0 + 2000)], crs=CRS_METRIC)
    tgt = _squares(side=2000.0)
    out = areal_interpolate(src, tgt, ["pop"])
    assert out["pop"].sum() == pytest.approx(140.0)                 # total preserved
    left = tgt.geometry.centroid.x < X0 + 1000
    assert np.allclose(out.loc[tgt.loc[left, "unit_id"], "pop"], 50.0)
    assert np.allclose(out.loc[tgt.loc[~left, "unit_id"], "pop"], 20.0)


def test_areal_interpolate_identity_and_nan():
    from crime.data.units import areal_interpolate

    src = gpd.GeoDataFrame({"unit_id": ["a", "b"], "v": [3.0, np.nan]},
                           geometry=[box(X0, Y0, X0 + 10, Y0 + 10), box(X0 + 10, Y0, X0 + 20, Y0 + 10)],
                           crs=CRS_METRIC)
    out = areal_interpolate(src, src, ["v"])
    assert out.loc["a", "v"] == pytest.approx(3.0) and out.loc["b", "v"] == 0.0
