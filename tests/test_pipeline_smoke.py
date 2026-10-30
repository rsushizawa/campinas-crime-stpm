"""Fast end-to-end smoke test of the classical (ESRI-style) pipeline.

Space-time cube -> Gi* / EHSA / space-time LISA / global Moran, on a small
low-volume slice, so signature or wiring breakage is caught in ~1 min. Not a
numeric check — that is ``test_cube_regression.py``. Needs the PostGIS DB up.

    python tests/test_pipeline_smoke.py        # or: pytest tests/test_pipeline_smoke.py
"""
from __future__ import annotations

import contextlib
import io
import sys

import crime


def test_pipeline_smoke() -> None:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        ds = crime.load_sectors(years=(2022, 2025), crime_slug="furto_veiculo",
                                events=True, overlay=True)

        # 1 — SpaceTimeCube object + layers
        cube = crime.space_time_cube(ds, freq="ME")
        assert isinstance(cube, crime.SpaceTimeCube)
        assert cube.wide is cube.layer("count")
        panel = cube.to_panel(["count"])
        assert set(panel.columns) == {"unit_id", "period", "count"}
        past, future = cube.split_time(cube.periods[20])
        assert past.shape[1] + future.shape[1] == cube.shape[1]

        # 2 — static ESDA
        mi = crime.global_moran(ds, permutations=999)
        assert -1.0 <= mi.I <= 1.0
        gi = crime.getis_ord_gi(ds, permutations=999, fdr=True)
        assert set(gi.gdf["label"]).issubset({"hotspot", "coldspot", "ns"})
        li = crime.local_moran(ds, permutations=999, fdr=True)
        assert "label" in li.gdf

        # 3 — space-time stack
        mk = crime.emerging_hotspots(ds, freq="YE")
        assert "category" in mk.gdf and mk.z_matrix.shape[0] == len(ds.gdf)
        mk2 = crime.emerging_hotspots(ds, freq="ME", rate=True, fdr=False)
        assert mk2.z_matrix.shape[1] == cube.shape[1]
        mkst = crime.emerging_hotspots(ds, freq="YE", neighbourhood="spacetime", time_step=1)
        assert mkst.z_matrix.shape == mk.z_matrix.shape
        mkcp = crime.emerging_hotspots(ds, freq="YE", permutations=99, fdr=False)
        assert "category" in mkcp.gdf
        ds_grid = crime.load_grid(years=(2022, 2025), crime_slug="furto_veiculo", events=True)
        mk_grid = crime.emerging_hotspots(ds_grid, freq="YE", permutations=99, fdr=False)
        labels, agreement = crime.support_sensitivity(mk, {"grid": mk_grid})
        assert "grid" in agreement.index and set(labels["ref"]) <= {"hotspot", "coldspot", "no pattern"}
        assert "label_agreement" in agreement and "kappa" in agreement
        stl = crime.space_time_lisa(ds, freq="YE")
        assert "modal_label" in stl.gdf
        tsc = crime.time_series_clustering(cube, method="profile", k=3, min_total=1)
        assert tsc.profiles.shape[0] <= 3 and "cluster" in tsc.gdf
        # matrix= hook — run EHSA on an arbitrary unit x period frame
        m = cube.wide.reindex(ds.gdf["unit_id"]).fillna(0)
        mkm = crime.emerging_hotspots(ds, matrix=m, freq="ME")
        assert mkm.z_matrix.shape == m.shape

        # 4 — correlation / EDA
        sp = crime.feature_correlation(crime.load_sectors(years=(2022, 2022),
                                                         crime_slug="furto_veiculo"))
        assert sp.target_corr is not None
        vif = crime.feature_collinearity(ds)
        assert vif.vif is not None

        # 4b — new viz surfaces (render only; no numeric check)
        import matplotlib
        matplotlib.use("Agg")
        spec = crime.DatasetSpec().years(2022, 2025).crime(slug="furto_veiculo").with_events()
        assert len(spec.scope("sector").load().gdf) == len(ds.gdf)
        for fn in (lambda: crime.emergence_timeline(mk2),
                   lambda: crime.emergence_curve(mk2),
                   lambda: crime.persistence_map(mk2, ds),
                   lambda: crime.trend_map(cube, ds),
                   lambda: crime.history_map(cube, ds),
                   lambda: crime.ehsa_map(mk2, ds),
                   lambda: crime.cluster_profiles(tsc)):
            # trend_map also returns its reusable slope frame.
            f = fn()[0]
            matplotlib.pyplot.close(f)
        assert crime.ehsa_transition_sankey(mk2).data

        # 5 — weights sensitivity + artifact round-trip
        import shutil
        import tempfile
        from pathlib import Path

        ws = crime.weights_sensitivity(ds, stat="gi", kinds=("queen", "rook"))
        assert ws is not None

        tmp = Path(tempfile.mkdtemp())
        try:
            mk.save(tmp / "ehsa")
            mk_r = crime.EhsaResult.load(tmp / "ehsa")
            assert (mk_r.gdf["category"].values == mk.gdf["category"].values).all()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        prov = crime.provenance(extra={"stage": "smoke"})
        assert prov["ic_crime_version"] and "numpy" in prov["libraries"]


if __name__ == "__main__":
    try:
        test_pipeline_smoke()
    except AssertionError as e:
        print("FAIL:", e)
        sys.exit(1)
    print("OK — classical pipeline smoke passed")
