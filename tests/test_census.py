"""Known-answer tests for etl.census (synthetic data; no database, no raw files)."""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from etl.census import assign_poi_tracts, cnefe_poi_points, poi_counts, tract_attributes


def _grid(n=2, size=1000.0):
    """n x n square tracts of ``size`` metres in EPSG:31983."""
    geoms, ids = [], []
    for i in range(n):
        for j in range(n):
            geoms.append(box(i * size, j * size, (i + 1) * size, (j + 1) * size))
            ids.append(f"t{i}_{j}")
    return gpd.GeoDataFrame({"cd_setor": ids}, geometry=geoms, crs="EPSG:31983")


def test_tract_attributes_keep_missing_and_literacy_blank_rule():
    g = _grid()
    ids = g["cd_setor"].tolist()
    poi = pd.DataFrame({"n_education": [1], "n_health": [0], "n_commercial": [4], "n_religious": [0]}, index=[ids[0]])
    out = tract_attributes(
        g,
        census=pd.DataFrame({"cd_setor": ids, "populacao_total": [100, 0, 50, 10], "dom_total": [30, 0, 20, 4]}),
        income=pd.DataFrame({"cd_setor": ids[:3], "income_head_mean": [1e3, 2e3, np.nan],
                             "income_head_median": [900, 1800, np.nan]}),
        literacy=pd.DataFrame({"cd_setor": ids, "alfa_15_mais_sabe": [90, 80, 70, np.nan],
                               "alfa_15_mais_nao_sabe": [10, np.nan, 30, np.nan]}),
        poi=poi,
    )
    assert out.index.tolist() == ids
    assert out["income_head_mean"].isna().tolist() == [False, False, True, True]
    assert out["literacy_rate"].round(3).tolist()[0] == 0.9
    # blank illiterate count with the literate count filled -> 0 (literacy 1.0); both blank stays missing
    assert out["literacy_rate"].iloc[1] == 1.0 and np.isnan(out["literacy_rate"].iloc[3])
    assert out["illiterate_15_plus"].iloc[1] == 0
    assert out["n_commercial"].tolist() == [4, 0, 0, 0]          # absent from CNEFE -> 0
    assert out["population"].tolist() == [100, 0, 50, 10]


def test_poi_dedup_on_address_and_use_type(tmp_path):
    """IC-Crime#18: one CNEFE row is one use type at one address. An address with a shop and a
    school counts once in each; an exact repeat counts once; dwellings (type 1) and points outside
    every tract are not counted."""
    g = _grid().rename(columns={"cd_setor": "unit_id"})
    xy = [(500, 500), (500, 500), (500, 500), (1500, 500), (1500, 500), (5000, 5000)]
    pts = gpd.GeoDataFrame(
        {"COD_UNICO_ENDERECO": ["A", "A", "A", "B", "C", "D"], "COD_ESPECIE": ["6", "4", "6", "1", "8", "6"]},
        geometry=gpd.points_from_xy(*zip(*xy)), crs="EPSG:31983").to_crs(4674)
    path = tmp_path / "cnefe.geojson"
    pts.to_file(path, driver="GeoJSON")
    points, n_dup = cnefe_poi_points(path)
    assert n_dup == 1
    assert sorted(points["poi"]) == ["n_commercial", "n_commercial", "n_education", "n_religious"]
    tract = assign_poi_tracts(points, g)
    out = poi_counts(points, tract)
    assert out.loc["t0_0", "n_commercial"] == 1 and out.loc["t0_0", "n_education"] == 1
    assert out.loc["t1_0", "n_religious"] == 1
    assert int(out.to_numpy().sum()) == 3                       # D lies outside every tract
    assert list(out.columns) == ["n_education", "n_health", "n_commercial", "n_religious"]
