"""Stage 5, validate: pandera checks on the loaded warehouse (``make validate``).

The database constraints (``database/schema.sql``) already enforce keys,
foreign keys and value ranges. These checks add the rules that need the data
as a whole:

:func:`fact_schema` (``fact_bulletin``)
    bulletin key unique; occurrence date in the window; slug in the taxonomy;
    no ``(0, 0)`` coordinate; coordinates inside the Campinas box or missing;
    a coordinate is present exactly when ``coord_status`` is ``ok`` or
    ``fixed_decimal``; row count equal to the funnel's in-window stage.
:func:`tract_schema` (``dim_census_tract``)
    2,592 unique tract ids starting with the Campinas municipality code.
The funnel stored in ``build`` must equal the funnel recomputed from the
tables (:func:`crime.data.warehouse.funnel`).

    from etl import schemas
    schemas.validate(schemas.fact_schema(funnel), df)

References
----------
Niels Bantilan (2020). pandera: Statistical data validation of pandas
dataframes. Proceedings of the 19th Python in Science Conference.
"""
from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

from crime.core import taxonomy
from crime.core.config import CODE_MUNI_CAMPINAS, DATE_END, DATE_START
from etl.acquire import LAT_RANGE, LON_RANGE

SLUGS = sorted(taxonomy.SLUG_TO_GROUP)
COORD_OK = {"ok", "fixed_decimal"}
COORD_STATUS = sorted(COORD_OK | {"zero", "redacted", "missing", "invalid"})
IN_WINDOW_STAGE = "occurrence date in window"
N_TRACTS = 2592


def funnel_count(funnel: list[dict], stage: str, col: str = "all") -> int:
    for row in funnel:
        if row["stage"] == stage:
            return int(row[col])
    raise KeyError(f"funnel stage {stage!r} not found")


def fact_schema(funnel: list[dict]) -> DataFrameSchema:
    """Checks on ``fact_bulletin`` (see the module docstring)."""
    n = funnel_count(funnel, IN_WINDOW_STAGE)
    lo, hi = pd.Timestamp(DATE_START), pd.Timestamp(DATE_END)
    return DataFrameSchema(
        {
            "bulletin_id": Column(str, unique=True, nullable=False),
            "occurrence_date": Column("datetime64[ns]", Check.in_range(lo, hi), nullable=False),
            "crime_slug": Column(str, Check.isin(SLUGS), nullable=False),
            "coord_status": Column(str, Check.isin(COORD_STATUS), nullable=False),
            "latitude": Column(float, Check.in_range(*LAT_RANGE), nullable=True),
            "longitude": Column(float, Check.in_range(*LON_RANGE), nullable=True),
        },
        checks=[
            Check(lambda d: ~(d["latitude"].eq(0) & d["longitude"].eq(0)), name="no (0,0) coordinate"),
            Check(lambda d: (d["latitude"].notna() & d["longitude"].notna()).eq(d["coord_status"].isin(COORD_OK)),
                  name="coordinate present iff coord_status in {ok, fixed_decimal}"),
            Check(lambda d: len(d) == n, name=f"row count == funnel in-window stage ({n:,})"),
        ],
        strict=False,
        name="fact_bulletin",
    )


def tract_schema() -> DataFrameSchema:
    """Checks on ``dim_census_tract``."""
    return DataFrameSchema(
        {"census_tract_id": Column(str, [Check.str_startswith(str(CODE_MUNI_CAMPINAS))], unique=True)},
        checks=[Check(lambda d: len(d) == N_TRACTS, name=f"{N_TRACTS:,} tracts")],
        strict=False,
        name="dim_census_tract",
    )


def validate(schema: DataFrameSchema, df: pd.DataFrame) -> pd.DataFrame:
    """Lazy validation: every failing check is collected before raising ``AssertionError``."""
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
