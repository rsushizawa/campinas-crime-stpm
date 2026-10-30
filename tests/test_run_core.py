"""scripts/04_analyse/run_core.py on synthetic data — no PostGIS, no real files.

A tiny fake municipality (32 triangular "tracts" + a 0.5 km² hexagon grid),
synthetic bulletins, tract attributes and CNEFE POIs; every step of the
pipeline runs end to end into ``tmp_path`` with reduced permutation counts.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

from crime.core.config import CRS_METRIC, CRS_WGS84

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "04_analyse"
X0, Y0, SIDE = 285_000.0, 7_465_000.0, 4_000.0      # a 4 x 4 km box in EPSG:31983 (Campinas zone)


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


# ------------------------------------------------------------------ synthetic inputs
def _tracts() -> gpd.GeoDataFrame:
    s = SIDE / 4
    polys = []
    for i in range(4):
        for j in range(4):
            x, y = X0 + i * s, Y0 + j * s
            polys += [shapely.Polygon([(x, y), (x + s, y), (x + s, y + s)]),
                      shapely.Polygon([(x, y), (x + s, y + s), (x, y + s)])]
    g = gpd.GeoDataFrame({"unit_id": [f"35095020{k:07d}" for k in range(len(polys))]},
                         geometry=polys, crs=CRS_METRIC)
    g["area_km2"] = g.geometry.area / 1e6
    return g[["unit_id", "area_km2", "geometry"]]


def _bulletins(tracts: gpd.GeoDataFrame, n: int = 900, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    hot = rng.normal([X0 + 900, Y0 + 900], 300, size=(n // 2, 2))
    bg = rng.uniform([X0, Y0], [X0 + SIDE, Y0 + SIDE], size=(n - n // 2, 2))
    xy = np.clip(np.vstack([hot, bg]), [X0 + 1, Y0 + 1], [X0 + SIDE - 1, Y0 + SIDE - 1])
    pts = gpd.GeoSeries(gpd.points_from_xy(xy[:, 0], xy[:, 1]), crs=CRS_METRIC)
    from crime.data.units import assign_points

    cd = assign_points(gpd.GeoDataFrame(geometry=pts), tracts)
    ll = pts.to_crs(CRS_WGS84)
    slug = np.where(rng.random(n) < 0.7, "furto_outros", "lesao_corporal_dolosa")
    df = pd.DataFrame({
        "LATITUDE": ll.y.to_numpy(), "LONGITUDE": ll.x.to_numpy(),
        "DATA_OCORRENCIA_BO": pd.Timestamp("2022-01-01") + pd.to_timedelta(rng.integers(0, 730, n), unit="D"),
        "HORA_OCORRENCIA_BO": "12:00", "DESC_PERIODO": "A tarde", "crime_slug": slug,
        "crime_group": np.where(slug == "furto_outros", "property", "bodily_harm"),
        "cd_setor": cd.to_numpy(),
    })
    df.loc[df.index[:15], "cd_setor"] = None          # geocoded but not in a tract: excluded everywhere
    return df


def _tract_attributes(tracts: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    rng = np.random.default_rng(1)
    g = tracts.copy()
    g["pop_total"] = rng.integers(200, 2000, len(g)).astype(float)
    g["income_head_mean"] = rng.normal(3000, 800, len(g))
    g["literacy_rate"] = rng.uniform(0.85, 0.99, len(g))
    return g


def _cnefe(n: int = 600) -> gpd.GeoDataFrame:
    from crime.data.cleaning import POI_SPECIES

    rng = np.random.default_rng(2)
    xy = rng.uniform([X0, Y0], [X0 + SIDE, Y0 + SIDE], size=(n, 2))
    g = gpd.GeoDataFrame({"poi": rng.choice(list(POI_SPECIES.values()), n)},
                         geometry=gpd.points_from_xy(xy[:, 0], xy[:, 1]), crs=CRS_METRIC)
    return g.to_crs(CRS_WGS84)


# ------------------------------------------------------------------ end to end
def test_run_core_end_to_end_synthetic(rc, tmp_path, monkeypatch):
    import crime.data.cleaning as cleaning
    from crime.data.units import tessellation

    tracts = _tracts()
    bpath = tmp_path / "bulletins_clean.parquet"
    bul = _bulletins(tracts)
    bul.to_parquet(bpath, index=False)
    n_in_tract = int(bul["cd_setor"].notna().sum())

    C = rc.C
    monkeypatch.setattr(rc, "BULLETINS_PARQUET", bpath)
    monkeypatch.setattr(C, "YEARS", (2022, 2023))
    monkeypatch.setattr(C, "SUPPORTS", {"tract": {"kind": "tract"},
                                        "hex0.5": {"kind": "hexagon", "area_km2": 0.5}})
    monkeypatch.setattr(C, "LISA_PERMUTATIONS", 99)
    monkeypatch.setattr(C, "MORAN_PERMUTATIONS", 99)
    monkeypatch.setattr(C, "POINTS", {**C.POINTS, "distances_m": (100, 500, 1000), "n_simulations": 9})
    monkeypatch.setattr(C, "KNOX", {**C.KNOX, "permutations": 19})
    monkeypatch.setattr(C, "TSC", {**C.TSC, "k_range": (2, 4)})
    monkeypatch.setattr(C, "ASSOCIATION", {**C.ASSOCIATION, "permutations": 99,
                                           "crime_years": ((2022, 2023), (2022, 2022))})

    def units(self, support):
        if support not in self._units:
            spec = C.SUPPORTS[support]
            self._units[support] = (tracts if spec["kind"] == "tract" else
                                    tessellation(tracts, shape=spec["kind"], area_km2=spec["area_km2"]))
        return self._units[support]

    monkeypatch.setattr(rc.Context, "units", units)
    monkeypatch.setattr(rc.Context, "tract_attributes", lambda self: _tract_attributes(tracts))
    monkeypatch.setattr(cleaning, "cnefe_poi_points", lambda path: _cnefe())

    out = tmp_path / "core"
    rc.main(["--groups", "all", "property", "--supports", "tract", "hex0.5", "--out", str(out)])

    # every support counts the same in-tract event set (finding: like-with-like MAUP)
    desc = pd.read_csv(out / "descriptive.csv")
    alln = desc[desc["group"] == "all"].set_index("support")["n_events"]
    assert alln["tract"] == alln["hex0.5"] == n_in_tract

    static = pd.read_csv(out / "static_summary.csv")
    assert set(static["support"]) == {"tract", "hex0.5"} and set(static["weights"]) == set(C.WEIGHTS)
    ehsa = pd.read_csv(out / "ehsa_summary.csv").set_index("time_unit")
    assert (ehsa.loc["quarter", "n_bins"] == 8).all() and (ehsa.loc["month", "n_bins"] == 24).all()

    maup = pd.read_csv(out / "maup_supports.csv")
    assert set(maup["support"]) == {"hex0.5"} and maup["label_agreement"].between(0, 1).all()
    assert not pd.read_csv(out / "maup_weights.csv").empty

    pts = pd.read_csv(out / "points_summary.csv")
    assert set(pts["variant"]) == {"all", "distinct"}
    assert pts.loc[(pts["group"] == "all") & (pts["variant"] == "all"), "n_points"].item() == n_in_tract

    assoc = pd.read_csv(out / "association.csv")
    assert set(assoc["scale"]) == {"count", "per_km2"}
    dens = assoc[assoc["scale"] == "per_km2"]
    assert set(dens["feature"]) == set(C.ASSOCIATION["features_all_supports"])   # intensive ones: count only
    assert {"income_head_mean", "literacy_rate"} <= set(assoc.loc[assoc["support"] == "tract", "feature"])
    assert not pd.read_csv(out / "association_local.csv").empty

    sizes = pd.read_csv(out / "tsc_sizes.csv")
    for _, d in sizes.groupby(["group", "support", "method"]):
        m = d.sort_values("cluster")["mean_total_events"].to_numpy()
        assert (np.diff(m) >= 0).all()                              # 0 = quietest

    man = json.loads((out / "manifest.json").read_text())
    assert set(man["steps"]) == set(C.STEPS)
    assert "db" not in man["provenance"] and "git_commit" in man["provenance"]
