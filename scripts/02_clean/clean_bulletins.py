"""Stage 2, clean: offence records to one row per bulletin in 2022-2025 (``make clean``).

    python scripts/02_clean/clean_bulletins.py

Reads ``outputs/data/crimes_campinas.csv`` (stage 1), runs
:func:`etl.steps.clean.clean_pipeline` (rules 9 to 15) and writes, under
``outputs/data/staging/clean/``, ``bulletins.parquet``, the buffered rejects
and the stage report. ``outputs/data/dedup_report.json`` and
``dedup_group_transitions.csv`` describe the one-row-per-bulletin collapse.
"""
import json

from crime.core.config import CRIMES_CSV, OUTPUT_DATA_DIR
from etl import sources
from etl.stage_io import save_stage, stage_dir
from etl.steps.clean import STAGE, clean_pipeline


def main() -> None:
    records = sources.extract_crimes(CRIMES_CSV)
    result = clean_pipeline().run(records)
    b = result.kept
    for c in b.select_dtypes("object").columns:
        b[c] = b[c].astype("string")
    b.to_parquet(stage_dir(STAGE) / "bulletins.parquet", index=False)
    rep = dict(result.extra["dedup_report"])
    rep["unparseable_occurrence_dates"] = result.extra["unparseable_occurrence_dates"]
    (OUTPUT_DATA_DIR / "dedup_report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    result.extra["dedup_group_transitions"].to_csv(OUTPUT_DATA_DIR / "dedup_group_transitions.csv", index=False)
    save_stage(STAGE, result, "Clean: offence records to bulletins in 2022-2025 (rules 9-15)")
    print(f"{len(b):,} bulletins with an occurrence date in the study window")


if __name__ == "__main__":
    main()
