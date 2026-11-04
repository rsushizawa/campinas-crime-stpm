"""Stage 4, load: write the release into the PostGIS warehouse (``make load``).

    python scripts/04_load/load_warehouse.py

Reads the staging tables, rejects and reports of stages 1 to 3, runs
:func:`etl.load.load_pipeline` (schema, writes, rules 23 to 25, ``build``
row) and then profiles the loaded tables (``outputs/reports/profile.md``,
report only). Connection: ``PG*`` variables or ``.env`` (``crime.core.config.DBConfig``).
"""
import geopandas as gpd
import pandas as pd

from crime.core.config import INPUTS_DIR, engine
from etl.load import STAGE, LoadInput, load_pipeline
from etl.pipeline import StageFailed
from etl.postgis import wait_for_db
from etl.profile import profile_warehouse
from etl.stage_io import read_rejects, read_report, save_stage, stage_dir
from etl.steps.acquire import expected_checksums, sha256

STAGES = ("acquire", "clean", "units")


def main() -> None:
    eng = engine()
    wait_for_db(eng)
    d = stage_dir("units")
    expected = expected_checksums()
    raw = {name: sha256(INPUTS_DIR / name) for name in expected}
    changed = sorted(n for n in expected if raw[n] != expected[n])
    if changed:   # rule 1 again: the release must record the files the stages actually read
        raise StageFailed(f"rule 1, raw inputs changed since SHA256SUMS: {changed}; rebuild with `make reload`")
    x = LoadInput(
        engine=eng,
        bulletins=gpd.read_parquet(d / "bulletins.parquet"),
        tracts=gpd.read_parquet(d / "tracts.parquet"),
        poi=gpd.read_parquet(d / "poi.parquet"),
        rejects=pd.concat([read_rejects(s) for s in STAGES], ignore_index=True),
        stage_reports={s: read_report(s) for s in STAGES},
        raw_inputs=raw,
    )
    result = load_pipeline().run(x)
    save_stage(STAGE, result, "Load: write the warehouse release (rules 23-25)")
    for row in result.extra["funnel"]:
        print(f"{row['all']:>9,}  {row['property']:>9,}  {row['stage']}")
    print(profile_warehouse(eng))


if __name__ == "__main__":
    main()
