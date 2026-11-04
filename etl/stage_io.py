"""Hand-over files between the Makefile stages.

Every stage script writes, under ``outputs/data/staging/<stage>/``, its output
tables, ``rejects.parquet`` (the rows its rules removed, see
:class:`etl.pipeline.RejectBuffer`) and ``report.json`` (its report lines). It
also prints the report and saves it as ``outputs/reports/<stage>.md``. The
load stage reads all of them back.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from crime.core.config import REPORTS_DIR, STAGING_DIR
from etl.pipeline import ReportLine, StepResult, report_frame, report_table


def stage_dir(stage: str) -> Path:
    d = STAGING_DIR / stage
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_stage(stage: str, result: StepResult, title: str) -> None:
    """Write ``rejects.parquet``, ``report.json`` and ``outputs/reports/<stage>.md``; print the report."""
    d = stage_dir(stage)
    result.rejects.to_parquet(d / "rejects.parquet", index=False)
    lines = [r.__dict__ for r in result.report]
    (d / "report.json").write_text(json.dumps(lines, indent=2, ensure_ascii=False))
    md = f"# {title}\n\n{report_table(result.report)}\n"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"{stage}.md").write_text(md)
    print(md)
    print(f"{len(result.rejects):,} rejected row(s) buffered in {d / 'rejects.parquet'}")


def read_report(stage: str) -> list[dict]:
    return json.loads((STAGING_DIR / stage / "report.json").read_text())


def read_rejects(stage: str) -> pd.DataFrame:
    return pd.read_parquet(STAGING_DIR / stage / "rejects.parquet")


__all__ = ["stage_dir", "save_stage", "read_report", "read_rejects", "ReportLine", "report_frame"]
