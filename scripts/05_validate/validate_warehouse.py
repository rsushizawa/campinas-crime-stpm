"""Stage 5, validate: pandera checks on the loaded warehouse (``make validate``).

    python scripts/05_validate/validate_warehouse.py

Reads ``fact_bulletin`` and ``dim_census_tract`` through
:class:`crime.data.Warehouse` (so it also fails when the database is down or
holds another schema version), applies :mod:`etl.schemas`, and checks that the
funnel stored in ``build`` equals the funnel recomputed from the tables.
Exits non-zero on the first failure.
"""
import sys

import pandas as pd

from crime.data import CrimeQuery, Warehouse
from crime.data.warehouse import funnel
from etl import schemas


def main() -> int:
    wh = Warehouse()
    stored = wh.build()["funnel"]
    fact = wh._sql("SELECT bulletin_id, occurrence_date, crime_slug, coord_status, latitude, longitude "
                   "FROM fact_bulletin", parse_dates=["occurrence_date"])
    schemas.validate(schemas.fact_schema(stored), fact)
    print(f"OK fact_bulletin: {len(fact):,} rows")
    schemas.validate(schemas.tract_schema(), pd.DataFrame(wh.census_tracts().drop(columns="geometry")))
    print("OK dim_census_tract")
    if funnel(wh.engine) != stored:
        print("FAIL funnel in build differs from the funnel recomputed from the tables")
        return 1
    print("OK funnel recomputed from the tables equals build.funnel")
    n = int(wh.counts(CrimeQuery()).loc[:, "count"].sum())
    if n != schemas.funnel_count(stored, "... inside a 2022 Campinas tract (cube input)"):
        print(f"FAIL spatial event set {n:,} differs from the funnel")
        return 1
    print(f"OK spatial event set: {n:,} bulletins in a tract")
    print(wh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
