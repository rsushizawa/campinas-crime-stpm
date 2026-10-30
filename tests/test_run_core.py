"""scripts/04_analyse/run_core.py helpers — no PostGIS, no real files."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "04_analyse"


@pytest.fixture(scope="module")
def rc():
    sys.path.insert(0, str(SCRIPTS))
    try:
        yield importlib.import_module("run_core")
    finally:
        sys.path.remove(str(SCRIPTS))


# ------------------------------------------------------------------ upsert
def test_upsert_replaces_only_this_runs_rows(rc, tmp_path):
    p = tmp_path / "t.csv"
    pd.DataFrame({"group": ["a", "b"], "support": ["tract", "tract"], "v": [1, 2]}).to_csv(p, index=False)
    rc.upsert(p, pd.DataFrame({"group": ["a"], "support": ["tract"], "v": [9]}),
              {"group": ["a"], "support": ["tract"]})
    out = pd.read_csv(p).sort_values("group")
    assert out["v"].tolist() == [9, 2]


def test_upsert_missing_key_column_keeps_old_rows(rc, tmp_path):
    """An old file without a key column must not lose every row."""
    p = tmp_path / "t.csv"
    pd.DataFrame({"group": ["a", "b"], "v": [1, 2]}).to_csv(p, index=False)      # no "support"
    rc.upsert(p, pd.DataFrame({"group": ["a"], "support": ["tract"], "v": [9]}),
              {"group": ["a"], "support": ["tract"]})
    out = pd.read_csv(p)
    assert len(out) == 3 and set(out["v"]) == {1, 2, 9}
