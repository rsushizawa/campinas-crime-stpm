"""Pandera validation (stage 03, ``etl/schemas.py``).

* Synthetic-fixture tests always run: valid rows pass, and each planted
  violation fails with its own check.
* Integration tests on the real cleaned data are skipped when
  ``outputs/data`` has not been built (``make acquire clean-data``); the
  PostGIS case also needs the database (``-m db``).
"""
from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from crime.core.config import BULLETINS_PARQUET, FUNNEL_JSON

pytest.importorskip("pandera")
from etl import schemas  # noqa: E402

needs_data = pytest.mark.skipif(not (BULLETINS_PARQUET.exists() and FUNNEL_JSON.exists()),
                                reason="outputs/data not built (make acquire clean-data)")


# --------------------------------------------------------------------------- #
#  synthetic fixtures — always run
# --------------------------------------------------------------------------- #
def _bulletins() -> pd.DataFrame:
    return pd.DataFrame({
        "NUM_BO": ["1", "2", "3", "4"],
        "ANO_BO": [2022, 2023, 2024, 2025],
        "NOME_DELEGACIA": ["D1", "D1", "D2", "D2"],
        "DATA_OCORRENCIA_BO": pd.to_datetime(["2022-03-01", "2023-06-01", "2021-12-30", "2025-12-31"]),
        "NATUREZA_APURADA": ["Furto - Outros", "Roubo - Outros", "Lesão Corporal Dolosa", "Furto - Veículo"],
        "crime_slug": ["furto_outros", "roubo_outros", "lesao_corporal_dolosa", "furto_veiculo"],
        "crime_group": ["property", "property", "bodily_harm", "property"],
        "COORD_STATUS": ["ok", "fixed_decimal", "zero", "ok"],
        "LATITUDE": [-22.90, -22.91, None, -22.92],
        "LONGITUDE": [-47.06, -47.07, None, -47.08],
        "n_records": [1, 2, 1, 1],
        "cd_setor": ["T1", "T1", None, "T1"],
    })


def _funnel(b: pd.DataFrame) -> list[dict]:
    prop = b["crime_group"].eq("property")
    occ = b["DATA_OCORRENCIA_BO"]
    cube = prop & occ.ge(schemas.WINDOW[0]) & occ.lt(schemas.WINDOW[1]) & b["cd_setor"].notna()
    return [{"stage": schemas.BULLETIN_STAGE, "all": len(b), "property": int(prop.sum())},
            {"stage": schemas.CUBE_STAGE, "all": int(cube.sum()), "property": int(cube.sum())}]


def _tracts() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({"cd_setor": ["T1"]}, geometry=[box(-47.2, -23.0, -47.0, -22.8)], crs="EPSG:4326")


def _fails(schema, df, expected: str) -> str:
    with pytest.raises(AssertionError) as e:
        schemas.validate(schema, df)
    assert expected in str(e.value), str(e.value)
    return str(e.value)


def test_synthetic_valid_rows_pass():
    b = _bulletins()
    f = _funnel(b)
    schemas.validate(schemas.bulletin_schema(f), b)
    cube = schemas.cube_input_from_bulletins(b, _tracts())
    assert len(cube) == 3
    schemas.validate(schemas.cube_input_schema(f), cube)


@pytest.mark.parametrize("plant, expected", [
    (lambda b: b.assign(LATITUDE=[0.0, -22.91, None, -22.92], LONGITUDE=[0.0, -47.07, None, -47.08]),
     "coordinate is (0, 0)"),
    (lambda b: b.assign(NUM_BO=["1", "1", "3", "4"], ANO_BO=[2022, 2022, 2024, 2025]), "uniqueness"),
    (lambda b: b.assign(crime_slug=["not_a_slug", "roubo_outros", "lesao_corporal_dolosa", "furto_veiculo"]),
     "crime_slug: isin"),
    (lambda b: b.assign(LATITUDE=[-21.0, -22.91, None, -22.92]), "LATITUDE: in_range"),
    (lambda b: b.assign(COORD_STATUS=["missing", "fixed_decimal", "zero", "ok"]),
     "coordinate present iff COORD_STATUS"),
    (lambda b: b.assign(crime_group=["drug", "property", "bodily_harm", "property"]),
     "crime_group matches crime_slug"),
    (lambda b: b.iloc[:3], "row count differs"),
])
def test_synthetic_bulletin_violation_fails(plant, expected):
    b = _bulletins()
    _fails(schemas.bulletin_schema(_funnel(b)), plant(b.copy()), expected)


def test_synthetic_cube_input_violations_fail():
    b = _bulletins()
    f = _funnel(b)
    cube = schemas.cube_input_from_bulletins(b, _tracts())
    late = cube.copy()
    late.loc[late.index[0], "data_ocorrencia"] = pd.Timestamp("2026-01-05")
    _fails(schemas.cube_input_schema(f), late, "occurrence after")
    outside = cube.copy()
    outside.loc[outside.index[0], "in_municipality"] = False
    _fails(schemas.cube_input_schema(f), outside, "point outside the municipality")
    other = cube.copy()
    other.loc[other.index[0], "crime_slug"] = "lesao_corporal_dolosa"
    _fails(schemas.cube_input_schema(f), other, "crime_slug: isin")
    _fails(schemas.cube_input_schema(f), cube.iloc[:2], "row count differs")


# --------------------------------------------------------------------------- #
#  integration — the real cleaned data
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def funnel():
    return json.loads(FUNNEL_JSON.read_text())


@pytest.fixture(scope="module")
def bulletins():
    from etl import sources
    return sources.extract_bulletins(BULLETINS_PARQUET)


@needs_data
def test_bulletin_table(funnel, bulletins):
    schemas.validate(schemas.bulletin_schema(funnel), bulletins)


@needs_data
def test_cube_input_from_parquet(funnel, bulletins):
    from etl import sources
    cube = schemas.cube_input_from_bulletins(bulletins, sources.extract_census_tracts())
    schemas.validate(schemas.cube_input_schema(funnel), cube)


@needs_data
@pytest.mark.db
def test_cube_input_from_postgis(funnel):
    from crime.core.config import engine
    eng = engine()
    try:
        eng.connect().close()
    except Exception:  # noqa: BLE001
        pytest.skip("PostGIS not reachable")
    schemas.validate(schemas.cube_input_schema(funnel), schemas.cube_input_from_db(eng))
