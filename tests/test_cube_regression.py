"""Regression gate for the SpaceTimeCube refactor.

``space_time_cube`` and ``emerging_hotspots`` must stay byte-identical on the
live PostGIS DB while the cube becomes a first-class object. The baseline hashes
in ``tests/fixtures/cube_baseline.json`` were captured on the pre-refactor code
(property-crime census-tract cube, 2022-2025).

Run directly (``python tests/test_cube_regression.py``) or under pytest.
Needs the database up (``docker compose -f database/docker-compose.yml up -d``).
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import crime

FIXTURE = Path(__file__).parent / "fixtures" / "cube_baseline.json"


def _hash(obj) -> str:
    if isinstance(obj, pd.DataFrame):
        b = (pd.util.hash_pandas_object(obj, index=True).values.tobytes()
             + repr(list(obj.columns)).encode())
    elif isinstance(obj, pd.Series):
        b = pd.util.hash_pandas_object(obj, index=True).values.tobytes()
    elif isinstance(obj, np.ndarray):
        b = np.ascontiguousarray(obj).tobytes()
    else:
        b = repr(obj).encode()
    return hashlib.sha256(b).hexdigest()


def _snapshot() -> dict:
    ds = crime.load_sectors(years=(2022, 2025), crime_group="property", events=True)
    snap: dict = {}
    for freq in ("ME", "YE"):
        cube = crime.space_time_cube(ds, freq=freq)
        # new object surface must not disturb the old attributes
        assert isinstance(cube, crime.SpaceTimeCube)
        assert cube.wide is cube.layer("count")
        snap[f"cube_{freq}_wide"] = _hash(cube.wide)
        snap[f"cube_{freq}_wide_shape"] = list(cube.wide.shape)
        snap[f"cube_{freq}_wide_sum"] = float(cube.wide.values.sum())
        snap[f"cube_{freq}_panel"] = _hash(cube.panel)
        # Frozen historical gate deliberately uses the pre-review trend rule.
        # Current inference is validated independently on synthetic examples.
        ehsa = crime.emerging_hotspots(ds, freq=freq, weights="queen", trend_method="legacy")
        snap[f"ehsa_{freq}_category"] = _hash(ehsa.gdf["category"])
        snap[f"ehsa_{freq}_category_counts"] = ehsa.gdf["category"].value_counts().to_dict()
        snap[f"ehsa_{freq}_zmatrix"] = _hash(ehsa.z_matrix)
        snap[f"ehsa_{freq}_mk_z"] = _hash(np.round(ehsa.gdf["mk_z"].to_numpy(), 10))
    return snap


def test_cube_regression() -> None:
    baseline = json.loads(FIXTURE.read_text())
    with contextlib.redirect_stdout(io.StringIO()):
        got = _snapshot()
    diffs = {k: (baseline.get(k), got.get(k)) for k in baseline if baseline.get(k) != got.get(k)}
    assert not diffs, "cube behaviour changed:\n" + json.dumps(diffs, indent=2, sort_keys=True)


if __name__ == "__main__":
    try:
        test_cube_regression()
    except AssertionError as e:
        print("FAIL:", e)
        sys.exit(1)
    print("OK — space_time_cube / emerging_hotspots byte-identical vs baseline")
