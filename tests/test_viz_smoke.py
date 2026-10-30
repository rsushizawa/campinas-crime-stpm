"""Render-only smoke test of the viz layer on a synthetic lattice (no database,
no basemap tiles). Catches wiring breakage in maps / charts / cubes; not a
visual check."""
from __future__ import annotations

import contextlib
import io

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from shapely.geometry import box  # noqa: E402

import crime  # noqa: E402
from crime.core.dataset import Dataset  # noqa: E402


@pytest.fixture(scope="module")
def results():
    n, T = 8, 12
    rng = np.random.default_rng(3)
    cells = [box(500 * c, 500 * r, 500 * (c + 1), 500 * (r + 1)) for r in range(n) for c in range(n)]
    gdf = gpd.GeoDataFrame({"unit_id": [f"u{i}" for i in range(n * n)]}, geometry=cells,
                           crs="EPSG:31983")
    hot = np.zeros((n, n))
    hot[2:5, 2:5] = 6.0
    lam = hot.ravel()[:, None] + 0.5 + np.linspace(0, 1, T)[None, :]
    matrix = pd.DataFrame(rng.poisson(lam).astype(float), index=gdf["unit_id"],
                          columns=pd.date_range("2022-01-31", periods=T, freq="ME"))
    gdf["crime_count"] = matrix.sum(axis=1).to_numpy()
    ds = Dataset(gdf, "sector", years=(2022, 2022))
    with contextlib.redirect_stdout(io.StringIO()):
        return dict(
            ds=ds, matrix=matrix,
            gi=crime.getis_ord_gi(ds),
            lisa=crime.local_moran(ds, permutations=99),
            moran=crime.global_moran(ds, permutations=99),
            ehsa=crime.emerging_hotspots(ds, matrix=matrix, freq="ME"),
            stl=crime.space_time_lisa(ds, matrix=matrix, permutations=99),
        )


def _close(out):
    fig = out[0] if isinstance(out, tuple) else out
    plt.close(fig)


@pytest.mark.parametrize("draw", [
    lambda r: crime.hotspot_map(r["gi"], r["ds"], basemap=None),
    lambda r: crime.lisa_map(r["lisa"], r["ds"], basemap=None),
    lambda r: crime.ehsa_map(r["ehsa"], r["ds"], basemap=None),
    lambda r: crime.persistence_map(r["ehsa"], r["ds"], basemap=None),
    lambda r: crime.choropleth_map(r["gi"], r["ds"], column="crime_count", basemap=None),
    lambda r: crime.moran_scatter(r["moran"]),
    lambda r: crime.ehsa_slice_maps(r["ehsa"], r["ds"]),
    lambda r: crime.space_time_lisa_cube(r["stl"]),
], ids=["hotspot", "lisa", "ehsa", "persistence", "choropleth", "moran_scatter",
        "slice_maps", "lisa_cube"])
def test_static_figures_render(results, draw):
    _close(draw(results))


def test_interactive_slice_map_builds(results):
    assert crime.interactive_slice_map(results["ehsa"]).data
