"""Spatial supports (crime.data.units) on synthetic data — no DB, no real files."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely.geometry import Point, box

from crime.core.config import CRS_METRIC, CRS_WGS84
from crime.data.units import assign_points, tessellation, unit_dataset

X0, Y0 = 280_000.0, 7_460_000.0          # somewhere in UTM 23S (Campinas-ish)
SIDE = 4_000.0                           # 4 km x 4 km study square


def _boundary(side=SIDE):
    return gpd.GeoDataFrame(geometry=[box(X0, Y0, X0 + side, Y0 + side)], crs=CRS_METRIC)


# ------------------------------------------------------------------ tessellation
def test_square_tessellation_exact_cover():
    t = tessellation(_boundary(), shape="square", area_km2=1.0)
    assert len(t) == 16                                     # 4 x 4 cells of 1 km²
    assert list(t.columns) == ["unit_id", "area_km2", "geometry"]
    assert t.crs == CRS_METRIC
    assert np.allclose(t["area_km2"], 1.0)
    assert t["unit_id"].is_unique and t["unit_id"].str.match(r"^S1000_\d{6}$").all()


@pytest.mark.parametrize("shape", ["hexagon", "square"])
def test_tessellation_covers_boundary(shape):
    b = _boundary()
    t = tessellation(b, shape=shape, area_km2=0.25)
    assert t["area_km2"].sum() == pytest.approx(16.0, rel=1e-9)          # partition of the square
    assert shapely.union_all(t.geometry.values).symmetric_difference(b.geometry[0]).area < 1e-3
    assert (t["area_km2"] <= 0.25 + 1e-9).all() and (t["area_km2"] > 0).all()
    if shape == "hexagon":
        assert np.isclose(t["area_km2"].max(), 0.25)                     # interior hexagons are whole
        assert t["unit_id"].str.startswith("H250_").all()
    # stable ids
    assert t["unit_id"].tolist() == tessellation(b, shape=shape, area_km2=0.25)["unit_id"].tolist()


def test_tessellation_rejects_bad_args():
    with pytest.raises(ValueError):
        tessellation(_boundary(), shape="triangle", area_km2=1)
    with pytest.raises(ValueError):
        tessellation(_boundary(), shape="square", area_km2=0)


# ------------------------------------------------------------------ assign_points
def test_assign_points_edges_and_outside():
    units = tessellation(_boundary(), shape="square", area_km2=1.0)
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
    units = tessellation(_boundary(), shape="square", area_km2=1.0)
    out = assign_points(gpd.GeoDataFrame(geometry=[], crs=CRS_METRIC), units)
    assert out.empty


# ------------------------------------------------------------------ unit_dataset
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
        "crime_slug": np.where(rng.random(n) < 0.7, "furto_outros", "lesao_corporal_dolosa"),
    })
    df["crime_group"] = np.where(df["crime_slug"] == "furto_outros", "property", "bodily_harm")
    # rows that must be dropped: no coordinates, outside the window, outside the units
    extra = df.iloc[:3].copy()
    extra.loc[extra.index[0], ["LATITUDE", "LONGITUDE"]] = np.nan
    extra.loc[extra.index[1], "DATA_OCORRENCIA_BO"] = pd.Timestamp("2021-06-01")
    far = gpd.GeoSeries([Point(X0 - 5000, Y0 - 5000)], crs=CRS_METRIC).to_crs(CRS_WGS84)
    extra.loc[extra.index[2], ["LATITUDE", "LONGITUDE"]] = [far.y[0], far.x[0]]
    return pd.concat([df, extra], ignore_index=True)


def _tract_like():
    """Irregular polygons (a 'tract' mesh): a 5 x 5 grid split diagonally in half."""
    polys = []
    s = SIDE / 5
    for i in range(5):
        for j in range(5):
            x, y = X0 + i * s, Y0 + j * s
            polys += [shapely.Polygon([(x, y), (x + s, y), (x + s, y + s)]),
                      shapely.Polygon([(x, y), (x + s, y + s), (x, y + s)])]
    return gpd.GeoDataFrame({"unit_id": [f"T{k:03d}" for k in range(len(polys))]},
                            geometry=polys, crs=CRS_METRIC)


@pytest.fixture(scope="module")
def bulletins():
    return _bulletins()


@pytest.mark.parametrize("kind,units", [
    ("tract", _tract_like()),
    ("hexagon", tessellation(_boundary(), shape="hexagon", area_km2=0.25)),
])
def test_unit_dataset_feeds_gi_and_cube(kind, units, bulletins):
    from crime.esri.cube import space_time_cube
    from crime.esri.local import getis_ord_gi

    ds = unit_dataset(kind, years=(2022, 2023), bulletins=bulletins, units=units,
                      area_km2=0.25 if kind == "hexagon" else None)
    assert len(ds.gdf) == len(units) and ds.gdf["unit_id"].tolist() == units["unit_id"].tolist()
    assert {"unit_id", "area_km2", "crime_count", "geometry"} <= set(ds.gdf.columns)
    n_valid = len(bulletins) - 3                                       # the three planted drops
    assert ds.gdf["crime_count"].sum() == n_valid == len(ds.events)
    assert (ds.gdf["crime_count"] == 0).any() or kind == "tract"       # empty units kept with 0
    assert {"unit_id", "data_ocorrencia", "hora_ocorrencia", "periodo",
            "crime_slug", "crime_group"} <= set(ds.events.columns)

    gi = getis_ord_gi(ds)
    assert len(gi.gdf) == len(units)
    hot_units = set(gi.gdf.loc[gi.gdf["label"] == "hotspot", "unit_id"])
    assert hot_units                                                   # the planted hot corner shows

    cube = space_time_cube(ds, freq="ME")
    assert cube.wide.shape == (len(units), 24)
    assert cube.wide.to_numpy().sum() == n_valid
    assert (cube.wide.sum(axis=1).reindex(ds.gdf["unit_id"]).to_numpy()
            == ds.gdf["crime_count"].to_numpy()).all()


def test_unit_dataset_crime_group_filter(bulletins):
    units = tessellation(_boundary(), shape="square", area_km2=1.0)
    allg = unit_dataset("square", area_km2=1.0, years=(2022, 2023), bulletins=bulletins, units=units)
    prop = unit_dataset("square", area_km2=1.0, years=(2022, 2023), bulletins=bulletins, units=units,
                        crime_group="property")
    assert set(prop.events["crime_group"]) == {"property"}
    assert 0 < prop.gdf["crime_count"].sum() < allg.gdf["crime_count"].sum()
    assert prop.meta.crime_group == "property" and prop.years == (2022, 2023)


def test_unit_dataset_pandas_string_dtype(bulletins):
    """The real parquet uses nullable string columns, with missing groups."""
    b = bulletins.astype({"crime_group": "string", "crime_slug": "string"})
    b.loc[b.index[:5], "crime_group"] = pd.NA
    units = tessellation(_boundary(), shape="square", area_km2=1.0)
    ds = unit_dataset("square", area_km2=1.0, years=(2022, 2023), bulletins=b, units=units,
                      crime_group="property")
    assert ds.gdf["crime_count"].sum() > 0


# ------------------------------------------------------------------ areal interpolation
def test_areal_interpolate_splits_by_area_share():
    from crime.data.units import areal_interpolate

    # two 1 km x 2 km source rectangles, values 100 and 40; targets: 2 x 2 squares of 1 km
    src = gpd.GeoDataFrame({"unit_id": ["a", "b"], "pop": [100.0, 40.0]},
                           geometry=[box(X0, Y0, X0 + 1000, Y0 + 2000),
                                     box(X0 + 1000, Y0, X0 + 2000, Y0 + 2000)], crs=CRS_METRIC)
    tgt = tessellation(gpd.GeoDataFrame(geometry=[box(X0, Y0, X0 + 2000, Y0 + 2000)], crs=CRS_METRIC),
                       shape="square", area_km2=1.0)
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
