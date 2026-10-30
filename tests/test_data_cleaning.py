"""Known-answer tests for crime.data.cleaning (synthetic data; no database, no raw files)."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from crime.data.cleaning import assign_tracts, filter_events, tract_attributes


def _grid(n=2, size=1000.0):
    """n x n square tracts of ``size`` metres in EPSG:31983."""
    geoms, ids = [], []
    for i in range(n):
        for j in range(n):
            geoms.append(box(i * size, j * size, (i + 1) * size, (j + 1) * size))
            ids.append(f"t{i}_{j}")
    return gpd.GeoDataFrame({"cd_setor": ids}, geometry=geoms, crs="EPSG:31983")


def test_filter_events_bounds_and_bad_dates():
    ev = pd.DataFrame({"crime_slug": ["a", "a", "a", "a", "x"],
                       "data_ocorrencia": ["2021-12-31", "2022-01-01", "2025-12-31", "1202-02-28", "2023-05-05"]})
    out, log = filter_events(ev, slugs=("a",))
    assert out["data_ocorrencia"].dt.strftime("%Y-%m-%d").tolist() == ["2022-01-01", "2025-12-31"]
    assert out["year"].tolist() == [2022, 2025]
    assert log["rows_before_start"] == 1 and log["rows_bad_date"] == 1 and log["rows_slug"] == 4


def test_filter_events_without_slugs_keeps_all_types():
    ev = pd.DataFrame({"crime_slug": ["a", "x"], "data_ocorrencia": ["2023-01-01", "2023-01-02"]})
    out, _ = filter_events(ev)
    assert out["crime_slug"].tolist() == ["a", "x"]


def test_assign_tracts_within_and_outside():
    g = _grid().rename(columns={"cd_setor": "unit_id"})
    pts = gpd.GeoSeries(gpd.points_from_xy([500, 1500, 5000], [500, 500, 5000]), crs="EPSG:31983").to_crs(4326)
    ev = pd.DataFrame({"long": list(pts.x) + [np.nan], "lat": list(pts.y) + [np.nan]})
    out = assign_tracts(ev, g)
    assert out.iloc[0] == "t0_0" and out.iloc[1] == "t1_0"
    assert pd.isna(out.iloc[2]) and pd.isna(out.iloc[3])


def test_tract_attributes_keep_missing_and_literacy_blank_rule():
    g = _grid()
    ids = g["cd_setor"].tolist()
    out = tract_attributes(
        g,
        census=pd.DataFrame({"cd_setor": ids, "populacao_total": [100, 0, 50, 10]}),
        income=pd.DataFrame({"cd_setor": ids[:3], "income_head_mean": [1e3, 2e3, np.nan],
                             "income_head_median": [900, 1800, np.nan]}),
        literacy=pd.DataFrame({"cd_setor": ids, "alfa_15_mais_sabe": [90, 80, 70, np.nan],
                               "alfa_15_mais_nao_sabe": [10, np.nan, 30, np.nan]}),
        n_commercial=pd.Series({ids[0]: 4}),
    )
    assert np.allclose(out["area_km2"], 1.0)
    assert out["income_head_mean"].isna().tolist() == [False, False, True, True]
    assert out["literacy_rate"].round(3).tolist()[0] == 0.9
    # blank "nao sabe" with "sabe" filled -> 0 (literacy 1.0); both blank stays NaN
    assert out["literacy_rate"].iloc[1] == 1.0 and np.isnan(out["literacy_rate"].iloc[3])
    assert out["n_commercial"].tolist() == [4, 0, 0, 0]


def test_poi_counts_dedup_on_address_and_use_type(tmp_path):
    """Issue #18: one CNEFE row is one use type at one address. An address with
    a shop and a school counts once in each; an exact repeat counts once; other
    use types (1 = dwelling) and points outside every tract are not counted."""
    from crime.data.cleaning import poi_counts

    g = _grid().rename(columns={"cd_setor": "unit_id"})
    xy = [(500, 500), (500, 500), (500, 500), (1500, 500), (1500, 500), (5000, 5000)]
    pts = gpd.GeoDataFrame(
        {"COD_UNICO_ENDERECO": ["A", "A", "A", "B", "C", "D"],
         "COD_ESPECIE": ["6", "4", "6", "1", "8", "6"]},
        geometry=gpd.points_from_xy(*zip(*xy)), crs="EPSG:31983").to_crs(4674)
    path = tmp_path / "cnefe.geojson"
    pts.to_file(path, driver="GeoJSON")
    out = poi_counts(path, g)
    assert out.loc["t0_0", "n_commercial"] == 1        # A/6 twice -> once
    assert out.loc["t0_0", "n_education"] == 1         # A/4 kept although A/6 exists
    assert out.loc["t1_0", "n_religious"] == 1
    assert out.loc["t1_0"].sum() == 1                   # B is a dwelling, not counted
    assert int(out.to_numpy().sum()) == 3               # D lies outside every tract
    assert list(out.columns) == ["n_education", "n_health", "n_commercial", "n_religious"]


def test_cnefe_poi_points_dedup_and_type(tmp_path):
    """The shared CNEFE reader keeps only POI use types, one row per
    (address, use type), and names the type in ``poi``."""
    from crime.data.cleaning import cnefe_poi_points

    pts = gpd.GeoDataFrame(
        {"COD_UNICO_ENDERECO": ["A", "A", "A", "B"], "COD_ESPECIE": ["6", "6", "5", "1"]},
        geometry=gpd.points_from_xy([0, 0, 0, 1], [0, 0, 0, 1]), crs="EPSG:31983").to_crs(4674)
    path = tmp_path / "cnefe.geojson"
    pts.to_file(path, driver="GeoJSON")
    out = cnefe_poi_points(path)
    assert sorted(out["poi"]) == ["n_commercial", "n_health"]
