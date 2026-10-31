"""scripts/05_figures/make_figures.py on the synthetic outputs of run_core (test_run_core's
fake municipality: tract + 0.5 km² hexagons), one group: every figure is written, and the
script reads nothing but the stage-04 tables and the unit geometries."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from test_run_core import run_synthetic, synthetic_units

FIG = Path(__file__).resolve().parents[1] / "scripts" / "05_figures"

EXPECTED = ["stl_all", "kde_all", "ripley_nni_all", "gi_star_all", "lisa_all", "ehsa_tract_all",
            "ehsa_hex0_5_all", "ehsa_supports_all", "tsc_map_all", "tsc_profiles_all", "maup_supports_all",
            "maup_weights_all", "knox_all", "association_all", "bivariate_local_all"]


@pytest.fixture(scope="module")
def mf():
    sys.path.insert(0, str(FIG))
    try:
        yield importlib.import_module("make_figures")
    finally:
        sys.path.remove(str(FIG))


def test_make_figures_synthetic(rc, mf, tmp_path, monkeypatch):
    out, tracts, _ = run_synthetic(rc, tmp_path, monkeypatch, groups=("all",))
    specs = {"tract": {"kind": "tract"}, "hex0.5": {"kind": "hexagon", "area_km2": 0.5}}
    mf.load_support.cache_clear()
    mf.boundary.cache_clear()
    monkeypatch.setattr(mf, "load_support", lambda s: synthetic_units(tracts, specs[s]))

    figs = tmp_path / "figures"
    mf.main(["--groups", "all", "--core", str(out), "--out", str(figs)])

    written = sorted(p.stem for p in (figs / "all").glob("*.png"))
    assert written == sorted(EXPECTED)
    assert all((figs / "all" / f"{n}.png").stat().st_size > 10_000 for n in EXPECTED)
    caps = json.loads((figs / "all" / "captions.json").read_text())
    assert set(caps) == {f"{n}.png" for n in EXPECTED} and all(caps.values())
    index = (figs / "index.md").read_text()
    assert all(f"all/{n}.png" in index for n in EXPECTED)
