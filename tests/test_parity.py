"""Parity: the warehouse-backed pipeline reproduces the paper's numbers (rule 30).

``tests/baseline/`` holds the results of every notebook as they were before
the warehouse redesign (``MANIFEST.json``: source commit, SHA-256 per file).
After ``make load notebooks``, every result the paper still uses must be
identical:

* the funnel stored in the warehouse equals ``baseline/data/funnel.json``;
* ``dedup_report.json`` and ``acquire_report.json`` are equal as dictionaries;
* every CSV and ``.tex`` file of the notebooks kept in the paper is equal,
  after removing what the scope change removed on purpose: the UTB support
  (rows with ``support == "utb"``, ``utb`` columns, ``*utb*`` files) and the
  notebooks the paper does not use (03, 07, 08, 10).

Files listed in ``MANIFEST.json`` under ``excluded_from_parity`` change between
runs (wall-clock timings) and are skipped. Nothing else is skipped: a missing
output or an unreachable warehouse fails the test, and ``make notebooks``
clears ``outputs/nb/`` first, so a stale file from an earlier run cannot pass.
Figures and ``06_ehsa/gi_bins_quarterly.parquet`` are not compared; the tables
they are drawn from are.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from crime.core.config import NOTEBOOK_OUTPUTS_DIR, OUTPUT_DATA_DIR

BASE = Path(__file__).resolve().parent / "baseline"
MANIFEST = json.loads((BASE / "MANIFEST.json").read_text())
REMOVED_NOTEBOOKS = {"03_point_patterns", "07_time_series_clustering", "08_knox", "10_maup"}
#: Columns that held UTB values in the baseline.
UTB_COLUMNS = {"utb", "UTB"}
#: Tables that list only the rows with a nonzero count: a row that was nonzero only
#: because of the UTB columns disappears with them.
NONZERO_ROW_TABLES = {"nb/06_ehsa/category_counts.csv"}


def _kept_files():
    for rel in sorted(MANIFEST["sha256"]):
        p = Path(rel)
        if p.parts[0] != "nb" or rel in MANIFEST["excluded_from_parity"]:
            continue
        if p.parts[1] in REMOVED_NOTEBOOKS or "utb" in p.name.lower() or p.suffix not in (".csv", ".tex"):
            continue
        yield rel


def _drop_utb(df: pd.DataFrame) -> pd.DataFrame:
    """The baseline frame without its UTB rows and columns."""
    if isinstance(df.columns, pd.MultiIndex):
        keep = [c for c in df.columns if "utb" not in c]
        return df[keep]
    df = df.drop(columns=[c for c in df.columns if c in UTB_COLUMNS or "/utb/" in c])
    if "support" in df.columns:
        df = df[df["support"] != "utb"].reset_index(drop=True)
    first = df.columns[0]
    if df[first].eq("utb").any():
        df = df[df[first] != "utb"].reset_index(drop=True)
    return df


def _header_rows(path: Path) -> int:
    """Rows of column header in a CSV written from a MultiIndex-column frame."""
    lines = path.read_text().splitlines()[:4]
    return sum(1 for ln in lines if ln.split(",")[0] in ("", "group", "support", "labels"))


@pytest.mark.parametrize("rel", list(_kept_files()))
def test_notebook_result_unchanged(rel):
    new = NOTEBOOK_OUTPUTS_DIR / Path(rel).relative_to("nb")
    old = BASE / rel
    if not new.exists():
        pytest.fail(f"{rel}: not produced (run `make notebooks`)")
    if old.suffix == ".tex":
        assert new.read_text() == old.read_text(), f"{rel} differs"
        return
    h = _header_rows(old)
    if h > 1:
        o = pd.read_csv(old, header=list(range(h)), index_col=0, dtype=str, keep_default_na=False)
        n = pd.read_csv(new, header=list(range(h)), index_col=0, dtype=str, keep_default_na=False)
    else:
        # every cell as text: the numbers must match as written, digit for digit
        o = pd.read_csv(old, dtype=str, keep_default_na=False)
        n = pd.read_csv(new, dtype=str, keep_default_na=False)
    o = _drop_utb(o)
    if rel in NONZERO_ROW_TABLES:
        o = o[~(o.iloc[:, 1:] == "0").all(axis=1) | (o.iloc[:, 0] == "no pattern detected")].reset_index(drop=True)
    pd.testing.assert_frame_equal(n.reset_index(drop=h <= 1), o.reset_index(drop=h <= 1), check_exact=True,
                                  check_dtype=False, obj=rel)


def test_funnel_unchanged():
    from crime.data import Warehouse

    assert Warehouse().build()["funnel"] == json.loads((BASE / "data" / "funnel.json").read_text())


@pytest.mark.parametrize("name", ["dedup_report.json", "acquire_report.json"])
def test_stage_reports_unchanged(name):
    new = OUTPUT_DATA_DIR / name
    if not new.exists():
        pytest.fail(f"{name} not built (make load)")
    assert json.loads(new.read_text()) == json.loads((BASE / "data" / name).read_text())
