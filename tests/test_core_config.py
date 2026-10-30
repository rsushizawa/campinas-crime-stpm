"""The core pipeline's configuration and CLI (scripts/04_analyse) — no data needed."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

from crime.data.units import KINDS

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "04_analyse"


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(SCRIPTS))


def test_config_is_consistent_and_serialisable():
    C = _load("core_config")
    json.dumps(C.as_dict())
    assert all(s["kind"] in KINDS for s in C.SUPPORTS.values())
    assert C.MAUP_REFERENCE in C.SUPPORTS and C.PRIMARY_WEIGHTS in C.WEIGHTS
    assert C.PRIMARY_TIME_UNIT in C.TIME_UNITS and C.TSC["time_unit"] in C.TIME_UNITS
    assert set(C.QUICK["supports"]) <= set(C.SUPPORTS) and set(C.QUICK["groups"]) <= set(C.GROUPS)
    assert not set(C.GROUPS) & set(C.TEMPORAL_ONLY_GROUPS)


def test_cli_and_upsert(tmp_path):
    R = _load("run_core")
    a = R.parse_args(["--quick", "--steps", "where", "maup"])
    assert a.quick and a.steps == ["where", "maup"]
    p = tmp_path / "t.csv"
    R.upsert(p, pd.DataFrame({"group": ["a", "b"], "v": [1, 2]}), {"group": ["a", "b"]})
    R.upsert(p, pd.DataFrame({"group": ["a"], "v": [9]}), {"group": ["a"]})       # replaces a, keeps b
    out = pd.read_csv(p).set_index("group")["v"].to_dict()
    assert out == {"a": 9, "b": 2}
