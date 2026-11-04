"""Stage 3, units: tracts, 2022 attributes, POIs and the tract of each bulletin (``make units``).

    python scripts/03_units/build_units.py

Reads the clean-stage bulletins, runs :func:`etl.steps.units.units_pipeline`
(rules 16 to 22) and writes ``tracts.parquet``, ``poi.parquet`` and
``bulletins.parquet`` (with ``census_tract_id`` and an EPSG:31983 point) under
``outputs/data/staging/units/``, plus the buffered rejects and the report.
"""
import pandas as pd

from etl.stage_io import save_stage, stage_dir
from etl.steps.units import STAGE, UnitsInput, units_pipeline


def main() -> None:
    bulletins = pd.read_parquet(stage_dir("clean") / "bulletins.parquet")
    result = units_pipeline().run(UnitsInput(bulletins=bulletins))
    u = result.kept
    d = stage_dir(STAGE)
    u.tracts.to_parquet(d / "tracts.parquet", index=False)
    u.poi.to_parquet(d / "poi.parquet", index=False)
    u.bulletins.to_parquet(d / "bulletins.parquet", index=False)
    save_stage(STAGE, result, "Units: tracts, attributes, POIs, tract of each bulletin (rules 16-22)")


if __name__ == "__main__":
    main()
