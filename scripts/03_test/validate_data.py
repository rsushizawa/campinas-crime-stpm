"""Stage 03 — Test: validate the cleaned data against pandera schemas.

    python scripts/03_test/validate_data.py          # parquet + PostGIS (fails if the DB is unreachable)
    python scripts/03_test/validate_data.py --no-db  # parquet only (make validate-no-db)

Checks (etl/schemas.py): unique bulletin key after dedup, slugs in the
taxonomy, no (0,0) coordinate, coordinates in the Campinas box or missing,
counts equal to outputs/data/funnel.json; for the cube input also the date
window and every point inside the municipality. Exits non-zero on failure.
"""
import json
import sys

from crime.core.config import BULLETINS_PARQUET, FUNNEL_JSON
from etl import schemas, sources


def main() -> int:
    funnel = json.loads(FUNNEL_JSON.read_text())
    bulletins = sources.extract_bulletins(BULLETINS_PARQUET)
    tracts = sources.extract_census_tracts()
    schemas.validate(schemas.bulletin_schema(funnel), bulletins)
    print(f"OK bulletins_clean: {len(bulletins):,} rows")
    cube = schemas.cube_input_from_bulletins(bulletins, tracts)
    schemas.validate(schemas.cube_input_schema(funnel), cube)
    print(f"OK cube input (parquet): {len(cube):,} rows")
    if "--no-db" not in sys.argv:
        from crime.core.config import engine
        eng = engine()
        try:
            eng.connect().close()
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL cube input (PostGIS): database not reachable ({exc.__class__.__name__}); "
                  "start it (make db) or pass --no-db to validate the parquet only")
            return 1
        db = schemas.cube_input_from_db(eng)
        schemas.validate(schemas.cube_input_schema(funnel), db)
        print(f"OK cube input (PostGIS fato_crimes): {len(db):,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
