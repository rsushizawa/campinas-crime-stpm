"""Stage 03 — data validation schemas (pandera), issue #13.

Two tables are validated:

* :func:`bulletin_schema` — ``outputs/data/bulletins_clean.parquet`` (one row
  per bulletin, all offences, all dates).
* :func:`cube_input_schema` — the events the primary space-time cube is built
  from (property group, occurrence date in the window, inside a 2022 tract),
  read either from the cleaned parquet or from PostGIS ``fato_crimes``.

Both check: bulletin key unique, slugs in the taxonomy, no ``(0, 0)``
coordinate, coordinates inside the Campinas bounding box or missing, and the
row count equal to the matching stage of ``outputs/data/funnel.json``. The cube
input additionally checks the date window and that every point lies inside
the municipality (the union of the 2022 tracts).

    from etl import schemas
    schemas.bulletin_schema(funnel).validate(df, lazy=True)
"""
from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

from crime.data.cleaning import DATE_END, DATE_START
from etl import taxonomy
from etl.acquire import LAT_RANGE, LON_RANGE

SLUGS = sorted(set(taxonomy.NATUREZA_TO_SLUG.values()))
GROUPS = sorted(taxonomy.CRIME_GROUPS)
PROPERTY = sorted(taxonomy.CRIME_GROUPS["property"])
COORD_OK = {"ok", "fixed_decimal"}
COORD_STATUS = sorted(COORD_OK | {"zero", "redacted", "missing", "invalid"})
WINDOW = (pd.Timestamp(DATE_START), pd.Timestamp(DATE_END) + pd.Timedelta(days=1))

BULLETIN_STAGE = "bulletins (one row per NUM_BO+ANO_BO+NOME_DELEGACIA)"
CUBE_STAGE = "... inside a 2022 Campinas tract (cube input)"


def funnel_count(funnel: list[dict], stage: str, col: str) -> int:
    for row in funnel:
        if row["stage"] == stage:
            return int(row[col])
    raise KeyError(f"funnel stage {stage!r} not found")


def _never_zero_zero(lat: str, lon: str) -> Check:
    return Check(lambda d: ~(d[lat].eq(0) & d[lon].eq(0)), name="no (0,0) coordinate",
                 error="coordinate is (0, 0)")


def _row_count(n: int, label: str) -> Check:
    return Check(lambda d: len(d) == n, name=f"row count == funnel[{label}] ({n:,})",
                 error=f"row count differs from funnel ({n:,})")


def bulletin_schema(funnel: list[dict]) -> DataFrameSchema:
    n_all = funnel_count(funnel, BULLETIN_STAGE, "all")
    n_prop = funnel_count(funnel, BULLETIN_STAGE, "property")
    return DataFrameSchema(
        {
            "NUM_BO": Column(str, nullable=False),
            "ANO_BO": Column(int, Check.in_range(2022, 2025), coerce=True),
            "NOME_DELEGACIA": Column(str, nullable=False),
            "DATA_OCORRENCIA_BO": Column("datetime64[ns]", nullable=True),
            "NATUREZA_APURADA": Column(str, nullable=False),
            "crime_slug": Column(str, Check.isin(SLUGS), nullable=False),
            "crime_group": Column(str, Check.isin(GROUPS), nullable=False),
            "COORD_STATUS": Column(str, Check.isin(COORD_STATUS), nullable=False),
            "LATITUDE": Column(float, Check.in_range(*LAT_RANGE), nullable=True),
            "LONGITUDE": Column(float, Check.in_range(*LON_RANGE), nullable=True),
            "n_records": Column(int, Check.ge(1), coerce=True),
        },
        checks=[
            _never_zero_zero("LATITUDE", "LONGITUDE"),
            Check(lambda d: (d["LATITUDE"].notna() & d["LONGITUDE"].notna()).eq(d["COORD_STATUS"].isin(COORD_OK)),
                  name="coordinate present iff COORD_STATUS in {ok, fixed_decimal}"),
            Check(lambda d: (d["crime_group"].map(taxonomy.CRIME_GROUPS.get)
                             .combine(d["crime_slug"], lambda slugs, s: s in slugs)),
                  name="crime_group matches crime_slug"),
            _row_count(n_all, "bulletins/all"),
            Check(lambda d: int(d["crime_group"].eq("property").sum()) == n_prop,
                  name=f"property bulletins == funnel ({n_prop:,})"),
        ],
        unique=["NUM_BO", "ANO_BO", "NOME_DELEGACIA"],
        report_duplicates="all",
        strict=False,
        name="bulletins_clean",
    )


def cube_input_schema(funnel: list[dict]) -> DataFrameSchema:
    """Columns: num_bo, ano_bo, nome_delegacia, data_ocorrencia, crime_slug,
    lat, long, unit_id, in_municipality (bool, computed by the caller)."""
    n = funnel_count(funnel, CUBE_STAGE, "property")
    return DataFrameSchema(
        {
            "num_bo": Column(str, nullable=False),
            "ano_bo": Column(int, Check.in_range(2022, 2025), coerce=True),
            "nome_delegacia": Column(str, nullable=False),
            "data_ocorrencia": Column("datetime64[ns]", [
                Check.ge(WINDOW[0], error=f"occurrence before {DATE_START}"),
                Check.lt(WINDOW[1], error=f"occurrence after {DATE_END}")], nullable=False),
            "crime_slug": Column(str, Check.isin(PROPERTY), nullable=False),
            "lat": Column(float, Check.in_range(*LAT_RANGE), nullable=False),
            "long": Column(float, Check.in_range(*LON_RANGE), nullable=False),
            "unit_id": Column(str, nullable=False),
            "in_municipality": Column(bool, Check.eq(True, error="point outside the municipality")),
        },
        checks=[_never_zero_zero("lat", "long"), _row_count(n, "cube input/property")],
        unique=["num_bo", "ano_bo", "nome_delegacia"],
        report_duplicates="all",
        strict=False,
        name="cube_input",
    )


def validate(schema: DataFrameSchema, df: pd.DataFrame) -> pd.DataFrame:
    """Lazy validation: every failing check is collected before raising."""
    try:
        return schema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        cases = exc.failure_cases
        wide = cases["schema_context"].eq("DataFrameSchema")
        cases = cases.assign(column=cases["column"].where(~wide, "<table>"))
        summary = (cases.groupby(["column", "check"], dropna=False)["index"].nunique(dropna=False)
                   .rename("n").reset_index())
        lines = "\n".join(f"  {r.column}: {r.check} ({r.n} row(s))" for r in summary.itertuples())
        raise AssertionError(f"{schema.name}: {len(cases)} failure case(s)\n{lines}") from exc


# --------------------------------------------------------------------------- #
#  cube-input frames (same columns from either source)
# --------------------------------------------------------------------------- #
def cube_input_from_bulletins(bulletins: pd.DataFrame, tracts) -> pd.DataFrame:
    """Property bulletins in the window with a tract, from the cleaned parquet."""
    import geopandas as gpd

    b = bulletins
    occ = b["DATA_OCORRENCIA_BO"]
    m = (b["crime_group"].eq("property") & occ.ge(WINDOW[0]) & occ.lt(WINDOW[1])
         & b["cd_setor"].notna())
    d = b.loc[m, ["NUM_BO", "ANO_BO", "NOME_DELEGACIA", "DATA_OCORRENCIA_BO", "crime_slug",
                  "LATITUDE", "LONGITUDE", "cd_setor"]]
    d.columns = ["num_bo", "ano_bo", "nome_delegacia", "data_ocorrencia", "crime_slug", "lat", "long",
                 "unit_id"]
    muni = tracts.to_crs("EPSG:4326").geometry.union_all()
    pts = gpd.GeoSeries(gpd.points_from_xy(d["long"], d["lat"]), crs="EPSG:4326", index=d.index)
    d = d.astype({"num_bo": str, "nome_delegacia": str, "crime_slug": str, "unit_id": str})
    return d.assign(in_municipality=pts.within(muni).to_numpy())


def cube_input_from_db(eng) -> pd.DataFrame:
    """The same frame from PostGIS, with the exact filter the cube loader uses
    (``crime.data.query.CrimeQuery`` window + group, ``cd_setor IS NOT NULL``)."""
    from sqlalchemy import text

    from crime.data.query import CrimeQuery

    where, params = CrimeQuery(years=(2022, 2025), crime_group="property").where("cd_setor IS NOT NULL")
    # "inside the municipality" = within some 2022 tract polygon, tested in PostGIS
    # (indexed EXISTS; testing against ST_Union of all tracts per row is far slower)
    sql = (
        "SELECT num_bo, ano_bo, nome_delegacia, data_ocorrencia, crime_slug, lat, long, "
        "cd_setor AS unit_id, EXISTS (SELECT 1 FROM dim_setor_censitario t "
        "WHERE ST_Within(f.geometry, t.geometry)) AS in_municipality "
        f"FROM fato_crimes f {where}"
    )
    d = pd.read_sql(text(sql), eng, params=params, parse_dates=["data_ocorrencia"])
    return d.astype({"in_municipality": bool})
