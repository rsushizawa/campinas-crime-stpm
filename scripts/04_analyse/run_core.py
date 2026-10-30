"""Stage 04 — Analyse: the core space-time pattern mining pipeline.

    python scripts/04_analyse/run_core.py                      # everything (make analyse)
    python scripts/04_analyse/run_core.py --quick              # property, tract only -> outputs/core_quick
    python scripts/04_analyse/run_core.py --steps where change --groups property drug --supports tract utb

Reads ``outputs/data/bulletins_clean.parquet`` (stage 02) and the raw tract /
CNEFE inputs; no database. All parameters live in ``core_config.py`` (every
value there is a default the authors may change). Steps, in order:

    when    monthly series + STL per group; descriptive table per support
    where   global Moran's I, Gi*, LISA per group x support x weights
    change  EHSA (space-time Gi* + Mann-Kendall) and space-time LISA per
            group x support x weights x time unit
    tsc     time series clustering per group x support x method
    maup    label agreement across supports (overlay onto tracts) and weights
    points  Ripley's L, Clark-Evans NNI (all points and distinct locations), KDE
    knox    Knox near-repeat table per group
    assoc   Spearman + bivariate Moran (crime x urban features); local bivariate
            Moran crime x commerce on tracts

Summary tables are **upserted** (rows for the groups/supports of this run are
replaced, others kept), so the pipeline can be run piecemeal. ``maup`` reads
the per-unit outputs of ``where`` and ``change``. Outputs: ``outputs/core/``;
``manifest.json`` records provenance, configuration and step timings.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import core_config as C
import geopandas as gpd
import numpy as np
import pandas as pd

from crime.core.config import BULLETINS_PARQUET, CNEFE_JSON, CRS_METRIC, CRS_WGS84, OUTPUTS_DIR
from crime.core.dataset import Dataset
from crime.core.results import family, jaccard
from crime.data.provenance import provenance

log = logging.getLogger("run_core")

EHSA_CATEGORIES = [f"{p} {s}spot" for s in ("hot", "cold") for p in
                   ("new", "consecutive", "intensifying", "persistent", "diminishing",
                    "sporadic", "oscillating", "historical")] + ["no pattern"]
QUADS = ("HH", "LL", "HL", "LH")


# =========================================================================== #
#  helpers
# =========================================================================== #
@contextlib.contextmanager
def quiet():
    """Silence the library's progress prints (results are logged by this script)."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


@contextlib.contextmanager
def timed(label: str, sink: dict | None = None):
    t0 = time.perf_counter()
    yield
    dt = time.perf_counter() - t0
    log.info("  %-58s %7.1f s", label, dt)
    if sink is not None:
        sink[label] = round(dt, 2)


def upsert(path: Path, df: pd.DataFrame, keys: dict[str, list]) -> None:
    """Write ``df`` to ``path`` (csv/parquet), replacing existing rows whose
    key columns take the values of this run (``keys``: column -> values)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        drop = np.ones(len(old), dtype=bool)
        for col, vals in keys.items():
            if col in old:
                drop &= old[col].astype(str).isin([str(v) for v in vals]).to_numpy()
        df = pd.concat([old[~drop], df], ignore_index=True)
    if path.suffix == ".parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provenance": provenance(), **payload}, indent=2, default=str))


class Context:
    """Lazy caches shared by the steps: bulletins, units, weights, datasets."""

    def __init__(self, groups, supports, out: Path):
        self.groups, self.supports, self.out = list(groups), list(supports), out
        self._b = None
        self._units, self._w, self._ds = {}, {}, {}
        self._tract_attr = None

    @property
    def bulletins(self) -> pd.DataFrame:
        if self._b is None:
            self._b = pd.read_parquet(BULLETINS_PARQUET)
        return self._b

    def in_window(self) -> pd.DataFrame:
        b = self.bulletins
        when = pd.to_datetime(b["DATA_OCORRENCIA_BO"], errors="coerce")
        lo, hi = pd.Timestamp(C.YEARS[0], 1, 1), pd.Timestamp(C.YEARS[1] + 1, 1, 1)
        return b[when.ge(lo) & when.lt(hi)]

    def units(self, support: str) -> gpd.GeoDataFrame:
        if support not in self._units:
            from crime.data.units import load_units
            self._units[support] = load_units(**C.SUPPORTS[support])
        return self._units[support]

    def weights(self, support: str, kind: str):
        key = (support, kind)
        if key not in self._w:
            from crime.esri.weights import spatial_weights
            with quiet():
                self._w[key] = spatial_weights(self.units(support), kind=kind, k=C.KNN_K)
        return self._w[key]

    def dataset(self, group: str, support: str) -> Dataset:
        key = (group, support)
        if key not in self._ds:
            from crime.data.units import unit_dataset
            spec = C.SUPPORTS[support]
            self._ds[key] = unit_dataset(spec["kind"], area_km2=spec.get("area_km2"),
                                         crime_group=None if group == "all" else group,
                                         years=C.YEARS, bulletins=self.bulletins,
                                         units=self.units(support))
        return self._ds[key]

    def tract_attributes(self) -> gpd.GeoDataFrame:
        if self._tract_attr is None:
            from crime.data.cleaning import build_tract_attributes
            self._tract_attr = build_tract_attributes()
        return self._tract_attr

    def points(self, group: str) -> gpd.GeoDataFrame:
        """Geocoded bulletins of ``group`` in the window that lie in a 2022 tract
        (stage 02 assignment), as metric points with an occurrence date."""
        b = self.in_window()
        if group != "all":
            b = b[b["crime_group"].eq(group).fillna(False).astype(bool)]
        b = b[b["cd_setor"].notna()]
        g = gpd.GeoDataFrame({"date": pd.to_datetime(b["DATA_OCORRENCIA_BO"]).to_numpy()},
                             geometry=gpd.points_from_xy(b["LONGITUDE"], b["LATITUDE"]), crs=CRS_WGS84)
        return g.to_crs(CRS_METRIC)

    def boundary(self) -> gpd.GeoDataFrame:
        return self.units("tract")[["geometry"]]


# =========================================================================== #
#  0 — weights diagnostics (always run: it is cheap and fixes KNN_K's rationale)
# =========================================================================== #
def weights_info(ctx: Context) -> dict:
    rows = []
    for s in ctx.supports:
        for k in C.WEIGHTS:
            w = ctx.weights(s, k)
            card = np.array(list(w.cardinalities.values()))
            rows.append(dict(support=s, weights=k, n_units=int(w.n), mean_neighbours=float(card.mean()),
                             median_neighbours=float(np.median(card)), min_neighbours=int(card.min()),
                             max_neighbours=int(card.max()), islands=len(w.islands)))
    tw = ctx.weights("tract", "queen")
    med = float(np.median(list(tw.cardinalities.values())))
    log.info("median queen neighbour count of tracts = %g (KNN_K = %d)", med, C.KNN_K)
    if med != C.KNN_K:
        log.warning("KNN_K (%d) differs from the median tract queen neighbour count (%g)", C.KNN_K, med)
    df = pd.DataFrame(rows)
    upsert(ctx.out / "weights_info.csv", df, {"support": ctx.supports})
    write_json(ctx.out / "weights_info.json", {"median_queen_neighbours_tract": med, "knn_k": C.KNN_K,
                                               "table": "weights_info.csv"})
    return {"median_queen_neighbours_tract": med}


# =========================================================================== #
#  1 — when
# =========================================================================== #
def step_when(ctx: Context, t: dict) -> None:
    from crime.stats.eda import stl_decompose

    b = ctx.in_window()
    month = pd.to_datetime(b["DATA_OCORRENCIA_BO"]).dt.to_period("M").dt.to_timestamp()
    months = pd.date_range(f"{C.YEARS[0]}-01-01", f"{C.YEARS[1]}-12-01", freq="MS")
    series, summ = {}, []
    for g in list(ctx.groups) + list(C.TEMPORAL_ONLY_GROUPS):
        m = np.ones(len(b), bool) if g == "all" else b["crime_group"].eq(g).fillna(False).to_numpy(bool)
        allb = month[m].value_counts().reindex(months, fill_value=0)
        geo = month[m & b["cd_setor"].notna().to_numpy()].value_counts().reindex(months, fill_value=0)
        with timed(f"when: STL {g}", t):
            stl = stl_decompose(allb.astype(float), **C.STL)
        stl.index.name = "month"
        stl["n_in_tract"] = geo.to_numpy()
        stl.to_csv(ctx.out / f"stl_{g}.csv")
        series[f"{g}_all"], series[f"{g}_in_tract"] = allb, geo
        summ.append(dict(group=g, n_bulletins=int(allb.sum()), n_in_tract=int(geo.sum()),
                         share_in_tract=float(geo.sum() / allb.sum()) if allb.sum() else np.nan,
                         trend_first=float(stl["trend"].iloc[0]), trend_last=float(stl["trend"].iloc[-1]),
                         seasonal_min=float(stl["seasonal"].min()), seasonal_max=float(stl["seasonal"].max()),
                         resid_sd=float(stl["resid"].std()),
                         peak_seasonal_month=int(stl["seasonal"].groupby(stl.index.month).mean().idxmax())))
    ms = pd.DataFrame(series)
    ms.index.name = "month"
    ms.to_csv(ctx.out / "monthly_series.csv")
    upsert(ctx.out / "stl_summary.csv", pd.DataFrame(summ), {"group": [s["group"] for s in summ]})

    rows = []
    for g in ctx.groups:
        for s in ctx.supports:
            with timed(f"when: descriptive {g} x {s}", t):
                gdf = ctx.dataset(g, s).gdf
                y = gdf["crime_count"].astype(float)
                rows.append(dict(group=g, support=s, n_units=len(gdf), n_events=int(y.sum()),
                                 mean=y.mean(), sd=y.std(), var_mean_ratio=y.var() / y.mean() if y.mean() else np.nan,
                                 median=y.median(), p90=y.quantile(0.9), max=y.max(),
                                 share_zero=float((y == 0).mean()),
                                 mean_area_km2=gdf["area_km2"].mean(), median_area_km2=gdf["area_km2"].median()))
    upsert(ctx.out / "descriptive.csv", pd.DataFrame(rows), {"group": ctx.groups, "support": ctx.supports})


# =========================================================================== #
#  2 — where (static)
# =========================================================================== #
def step_where(ctx: Context, t: dict) -> None:
    from crime.esri.local import getis_ord_gi, local_moran
    from crime.esri.moran import global_moran

    rows = []
    for s in ctx.supports:
        per_unit = []
        for g in ctx.groups:
            ds = ctx.dataset(g, s)
            for k in C.WEIGHTS:
                w = ctx.weights(s, k)
                with timed(f"where: {g} x {s} x {k}", t), quiet():
                    mi = global_moran(ds, weights=w, permutations=C.MORAN_PERMUTATIONS, alpha=C.ALPHA, seed=C.SEED)
                    gi = getis_ord_gi(ds, weights=w, alpha=C.ALPHA, fdr=C.FDR)
                    li = local_moran(ds, weights=w, permutations=C.LISA_PERMUTATIONS, alpha=C.ALPHA,
                                     fdr=C.FDR, seed=C.SEED)
                gl, ll = gi.gdf["label"].value_counts(), li.gdf["label"].value_counts()
                rows.append(dict(group=g, support=s, weights=k, n_units=len(ds.gdf),
                                 n_events=int(ds.gdf["crime_count"].sum()),
                                 moran_I=mi.I, moran_EI=mi.EI, moran_z_sim=mi.z_sim, moran_p_sim=mi.p_sim,
                                 moran_z_norm=mi.z_norm, moran_p_norm=mi.p_norm,
                                 gi_hot=int(gl.get("hotspot", 0)), gi_cold=int(gl.get("coldspot", 0)),
                                 gi_ns=int(gl.get("ns", 0)), gi_no_data=int(gl.get("no data", 0)),
                                 **{f"lisa_{q}": int(ll.get(q, 0)) for q in QUADS},
                                 lisa_ns=int(ll.get("ns", 0)), lisa_no_data=int(ll.get("no data", 0))))
                per_unit.append(pd.DataFrame(dict(
                    group=g, weights=k, unit_id=ds.gdf["unit_id"].to_numpy(),
                    crime_count=ds.gdf["crime_count"].to_numpy(),
                    gi_z=gi.gdf["gi_z"].to_numpy(), gi_p_adj=gi.gdf["p_adjusted"].to_numpy(),
                    gi_label=gi.gdf["label"].to_numpy(), lisa_I=li.gdf["lisa_I"].to_numpy(),
                    lisa_p_adj=li.gdf["p_adjusted"].to_numpy(), lisa_label=li.gdf["label"].to_numpy())))
        upsert(ctx.out / "static_by_unit" / f"{s}.parquet", pd.concat(per_unit, ignore_index=True),
               {"group": ctx.groups})
    upsert(ctx.out / "static_summary.csv", pd.DataFrame(rows), {"group": ctx.groups, "support": ctx.supports})


# =========================================================================== #
#  3 — how it changes
# =========================================================================== #
def step_change(ctx: Context, t: dict) -> None:
    from crime.esri.ehsa import emerging_hotspots
    from crime.esri.stlisa import space_time_lisa

    rows = []
    for s in ctx.supports:
        per_unit = []
        for g in ctx.groups:
            ds = ctx.dataset(g, s)
            for k in C.WEIGHTS:
                w = ctx.weights(s, k)
                for tu, freq in C.TIME_UNITS.items():
                    with timed(f"change: {g} x {s} x {k} x {tu}", t), quiet():
                        eh = emerging_hotspots(ds, freq=freq, weights=w, alpha=C.ALPHA, fdr=C.FDR, **C.EHSA)
                        st = space_time_lisa(ds, freq=freq, weights=w, permutations=C.LISA_PERMUTATIONS,
                                             alpha=C.ALPHA, fdr=C.FDR, seed=C.SEED)
                    cat = eh.gdf["category"].value_counts()
                    sl = st.labels.stack().value_counts()
                    unknown = set(cat.index) - set(EHSA_CATEGORIES)
                    if unknown:
                        log.warning("unexpected EHSA categories: %s", unknown)
                    rows.append(dict(group=g, support=s, weights=k, time_unit=tu, freq=freq,
                                     n_units=len(ds.gdf), n_bins=eh.z_matrix.shape[1],
                                     n_events=int(ds.gdf["crime_count"].sum()),
                                     **{c: int(cat.get(c, 0)) for c in EHSA_CATEGORIES},
                                     **{f"stlisa_{q}": int(sl.get(q, 0)) for q in (*QUADS, "ns")},
                                     stlisa_no_data=int(sl.get("no data", 0)),
                                     stlisa_units_ever_HH=int((st.gdf["n_hh"] > 0).sum()),
                                     stlisa_units_ever_LL=int((st.gdf["n_ll"] > 0).sum())))
                    per_unit.append(pd.DataFrame(dict(
                        group=g, weights=k, time_unit=tu, unit_id=eh.gdf["unit_id"].to_numpy(),
                        category=eh.gdf["category"].to_numpy(), pct_hot=eh.gdf["pct_hot"].to_numpy(),
                        pct_cold=eh.gdf["pct_cold"].to_numpy(), mk_z=eh.gdf["mk_z"].to_numpy(),
                        mk_p=eh.gdf["mk_p"].to_numpy(), mk_p_fdr=eh.gdf["mk_p_fdr"].to_numpy(),
                        stlisa_n_hh=st.gdf["n_hh"].to_numpy(), stlisa_n_ll=st.gdf["n_ll"].to_numpy(),
                        stlisa_modal=st.gdf["modal_label"].to_numpy())))
        upsert(ctx.out / "ehsa_by_unit" / f"{s}.parquet", pd.concat(per_unit, ignore_index=True),
               {"group": ctx.groups})
    upsert(ctx.out / "ehsa_summary.csv", pd.DataFrame(rows), {"group": ctx.groups, "support": ctx.supports})


# =========================================================================== #
#  4 — time series clustering
# =========================================================================== #
def step_tsc(ctx: Context, t: dict) -> None:
    from crime.esri.cube import space_time_cube
    from crime.esri.tsclust import time_series_clustering

    freq = C.TIME_UNITS[C.TSC["time_unit"]]
    rows, sizes, profiles = [], [], []
    for s in ctx.supports:
        per_unit = []
        for g in ctx.groups:
            cube = space_time_cube(ctx.dataset(g, s), freq=freq)
            for m in C.TSC["methods"]:
                try:
                    with timed(f"tsc: {g} x {s} x {m}", t), quiet():
                        r = time_series_clustering(cube, method=m, k=None, k_range=tuple(C.TSC["k_range"]),
                                                   min_total=C.TSC["min_total"], seed=C.SEED)
                except ValueError as e:                    # too few units with events
                    log.warning("tsc %s x %s x %s skipped: %s", g, s, m, e)
                    rows.append(dict(group=g, support=s, method=m, time_unit=C.TSC["time_unit"],
                                     k=np.nan, note=str(e)))
                    continue
                cl = r.gdf["cluster"]
                rows.append(dict(group=g, support=s, method=m, time_unit=C.TSC["time_unit"], k=r.k,
                                 pseudo_f=r.pseudo_f, n_clustered=int((cl >= 0).sum()),
                                 n_excluded=int((cl < 0).sum()),
                                 pseudo_f_by_k=";".join(f"{kk}:{v:.1f}" for kk, v in r.scores.items()),
                                 note=""))
                tot = cube.wide.sum(axis=1).reindex(r.gdf["unit_id"]).to_numpy()
                for c, n in cl.value_counts().sort_index().items():
                    sizes.append(dict(group=g, support=s, method=m, cluster=int(c), n_units=int(n),
                                      mean_total_events=float(tot[cl.to_numpy() == c].mean())))
                p = r.profiles.copy()
                p.columns = [str(pd.Timestamp(c).date()) for c in p.columns]
                p = p.reset_index(names="cluster").melt(id_vars="cluster", var_name="period",
                                                        value_name="mean_count")
                profiles.append(p.assign(group=g, support=s, method=m))
                per_unit.append(pd.DataFrame(dict(group=g, method=m, unit_id=r.gdf["unit_id"].to_numpy(),
                                                  cluster=cl.to_numpy())))
        if per_unit:
            upsert(ctx.out / "tsc_by_unit" / f"{s}.parquet", pd.concat(per_unit, ignore_index=True),
                   {"group": ctx.groups})
    keys = {"group": ctx.groups, "support": ctx.supports}
    upsert(ctx.out / "tsc_summary.csv", pd.DataFrame(rows), keys)
    if sizes:
        upsert(ctx.out / "tsc_sizes.csv", pd.DataFrame(sizes), keys)
        upsert(ctx.out / "tsc_profiles.csv", pd.concat(profiles, ignore_index=True), keys)


# =========================================================================== #
#  5 — MAUP: supports and weights
# =========================================================================== #
def _read_by_unit(ctx: Context, kind: str, support: str) -> pd.DataFrame | None:
    p = ctx.out / kind / f"{support}.parquet"
    if not p.exists():
        log.warning("maup: %s missing (run the %s step first)", p, "where" if kind == "static_by_unit" else "change")
        return None
    return pd.read_parquet(p)


def _labels(df: pd.DataFrame, group: str, weights: str, col: str, units: gpd.GeoDataFrame,
            time_unit: str | None = None) -> gpd.GeoDataFrame | None:
    sel = (df["group"] == group) & (df["weights"] == weights)
    if time_unit is not None:
        sel &= df["time_unit"] == time_unit
    d = df[sel]
    if d.empty:
        return None
    lab = d.set_index("unit_id")[col].reindex(units["unit_id"]).fillna("no data")
    return gpd.GeoDataFrame({"unit_id": units["unit_id"].to_numpy(), "category": lab.to_numpy()},
                            geometry=units.geometry.values, crs=units.crs)


def _pair_metrics(a: pd.Series, b: pd.Series, method: str) -> dict:
    from sklearn.metrics import cohen_kappa_score

    if method == "lisa":
        fa, fb = a.to_numpy(), b.to_numpy()
        hot, cold = "HH", "LL"
    else:
        fa, fb = family(a), family(b)
        hot, cold = "hotspot", "coldspot"
    same = float((a.to_numpy() == b.to_numpy()).mean())
    with np.errstate(all="ignore"):
        kappa = float(cohen_kappa_score(fa, fb)) if len(set(fa) | set(fb)) > 1 else float("nan")
    return dict(label_agreement=same, family_agreement=float((fa == fb).mean()),
                hot_jaccard=jaccard(fa, fb, hot), cold_jaccard=jaccard(fa, fb, cold), kappa=kappa,
                n_hot_a=int((fa == hot).sum()), n_hot_b=int((fb == hot).sum()),
                n_cold_a=int((fa == cold).sum()), n_cold_b=int((fb == cold).sum()))


def step_maup(ctx: Context, t: dict) -> None:
    from crime.esri.maup import support_sensitivity

    ref = C.MAUP_REFERENCE
    primary_tu, pw = C.PRIMARY_TIME_UNIT, C.PRIMARY_WEIGHTS
    supports = [s for s in C.SUPPORTS if s in ctx.supports or s == ref]
    static = {s: _read_by_unit(ctx, "static_by_unit", s) for s in supports}
    change = {s: _read_by_unit(ctx, "ehsa_by_unit", s) for s in supports}

    # -- across supports: each support's labels overlaid onto the reference tracts
    rows = []
    for g in ctx.groups:
        for method, tables, col, tu in (("gi_star", static, "gi_label", None),
                                         (f"ehsa_{primary_tu}", change, "category", primary_tu)):
            if tables.get(ref) is None:
                continue
            ref_lab = _labels(tables[ref], g, pw, col, ctx.units(ref), tu)
            if ref_lab is None:
                continue
            others = {}
            for s in supports:
                if s == ref or tables.get(s) is None:
                    continue
                lab = _labels(tables[s], g, pw, col, ctx.units(s), tu)
                if lab is not None:
                    others[s] = SimpleNamespace(gdf=lab)
            if not others:
                continue
            with timed(f"maup: supports {g} x {method}", t), quiet():
                labels, agr = support_sensitivity(SimpleNamespace(gdf=ref_lab), others)
            for s, r in agr.iterrows():
                rows.append(dict(group=g, method=method, weights=pw, reference=ref, support=s,
                                 n_ref_units=len(labels),
                                 ref_hot=int((labels["ref"] == "hotspot").sum()),
                                 support_hot_on_ref=int((labels[s] == "hotspot").sum()),
                                 ref_cold=int((labels["ref"] == "coldspot").sum()),
                                 support_cold_on_ref=int((labels[s] == "coldspot").sum()),
                                 **{c: float(r[c]) for c in ("label_agreement", "hotspot_jaccard",
                                                             "coldspot_jaccard", "patterned_jaccard",
                                                             "kappa", "uncovered_ref_units")}))
    if rows:
        upsert(ctx.out / "maup_supports.csv", pd.DataFrame(rows), {"group": ctx.groups})

    # -- across weights within each support
    rows = []
    pairs = [(a, b) for i, a in enumerate(C.WEIGHTS) for b in C.WEIGHTS[i + 1:]]
    for s in ctx.supports:
        for g in ctx.groups:
            specs = []
            if static.get(s) is not None:
                specs += [("gi_star", static[s], "gi_label", None), ("lisa", static[s], "lisa_label", None)]
            if change.get(s) is not None:
                specs += [(f"ehsa_{tu}", change[s], "category", tu) for tu in C.TIME_UNITS]
            for method, df, col, tu in specs:
                lab = {k: _labels(df, g, k, col, ctx.units(s), tu) for k in C.WEIGHTS}
                for a, b in pairs:
                    if lab[a] is None or lab[b] is None:
                        continue
                    rows.append(dict(group=g, support=s, method=method, weights_a=a, weights_b=b,
                                     **_pair_metrics(lab[a]["category"], lab[b]["category"],
                                                     "lisa" if method == "lisa" else "family")))
    if rows:
        upsert(ctx.out / "maup_weights.csv", pd.DataFrame(rows), {"group": ctx.groups, "support": ctx.supports})


# =========================================================================== #
#  6 — points
# =========================================================================== #
def step_points(ctx: Context, t: dict) -> None:
    from crime.points.kde import kde_surface
    from crime.points.nni import nearest_neighbour_index
    from crime.points.ripley import ripley_l

    P = C.POINTS
    boundary = ctx.boundary()
    rows = []
    for g in ctx.groups:
        pts = ctx.points(g)
        xy = pd.DataFrame({"x": pts.geometry.x.round(3), "y": pts.geometry.y.round(3)})
        stacked = float(xy.duplicated(keep=False).mean())
        distinct = pts.loc[~xy.duplicated(keep="first").to_numpy()]
        rip_tables = []
        for variant, p in (("all", pts), ("distinct", distinct)):
            with timed(f"points: {g} {variant} (n={len(p)})", t), quiet():
                rp = ripley_l(p, boundary, distances_m=P["distances_m"], n_simulations=P["n_simulations"],
                              seed=C.SEED, sample=P["sample"])
                nn = nearest_neighbour_index(p, boundary)
            tb = rp.table.copy()
            tb["state"] = np.select([tb["L"] > tb["env_high"], tb["L"] < tb["env_low"]],
                                    ["clustered", "dispersed"], default="CSR")
            rip_tables.append(tb.assign(variant=variant, n_points=rp.n_points))
            at = tb.set_index("distance_m")
            rows.append(dict(group=g, variant=variant, n_points=nn.n_points, share_stacked_all=stacked,
                             nni_ratio=nn.ratio, nni_observed_m=nn.observed_m, nni_expected_m=nn.expected_m,
                             nni_z=nn.z, nni_p=nn.p, nni_n_coincident=nn.n_coincident,
                             ripley_n=rp.n_points, ripley_sampled=rp.n_points < len(p),
                             ripley_n_clustered_distances=int((tb["state"] == "clustered").sum()),
                             ripley_n_distances=len(tb),
                             **{f"L_minus_d_{d}m": float(at.loc[d, "L_minus_d"]) for d in (100, 500, 1000, 3000)
                                if d in at.index},
                             L_minus_d_max=float(tb["L_minus_d"].max()),
                             L_minus_d_argmax_m=float(tb.loc[tb["L_minus_d"].idxmax(), "distance_m"])))
        pd.concat(rip_tables, ignore_index=True).to_csv(ctx.out / f"ripley_{g}.csv", index=False)
        with timed(f"points: {g} KDE", t), quiet():
            kd = kde_surface(pts, boundary, cell_m=P["kde_cell_m"], kernel=P["kde_kernel"])
        cells = kd.cells()
        pd.DataFrame({"x": cells.geometry.x, "y": cells.geometry.y, "density_per_km2": cells["density"]}
                     ).to_parquet(ctx.out / f"kde_{g}.parquet", index=False)
        rows[-2].update(kde_bandwidth_m=kd.bandwidth_m, kde_cell_m=kd.cell_m,
                        kde_max_per_km2=float(np.nanmax(kd.density)), kde_integral=kd.total)
    upsert(ctx.out / "points_summary.csv", pd.DataFrame(rows), {"group": ctx.groups})


# =========================================================================== #
#  7 — Knox
# =========================================================================== #
def step_knox(ctx: Context, t: dict) -> None:
    from crime.stats.knox import knox_table

    K = C.KNOX
    rows = []
    for g in ctx.groups:
        pts = ctx.points(g)
        ev = pd.DataFrame({"x": pts.geometry.x, "y": pts.geometry.y, "date": pts["date"]})
        sample = K["max_events"] if len(ev) > K["max_events"] else None
        with timed(f"knox: {g} (n={len(ev)}{', sample ' + str(sample) if sample else ''})", t):
            kt = knox_table(ev, space_bands_m=list(K["space_bands_m"]), time_bands_days=list(K["time_bands_days"]),
                            permutations=K["permutations"], seed=C.SEED, sample=sample)
        long = kt.stack("time band", future_stack=True).reset_index()
        long.insert(0, "group", g)
        long["n_events_used"] = kt.attrs["n_events"]
        long["n_events_total"] = len(ev)
        long["sampled"] = sample is not None
        long.to_csv(ctx.out / f"knox_{g}.csv", index=False)
        # headline cell: the first (smallest) space band x the first time band
        first = long[(long["space band"] == kt.index[0])
                     & (long["time band"] == kt["ratio"].columns[0])].iloc[0]
        rows.append(dict(group=g, n_events_total=len(ev), n_events_used=kt.attrs["n_events"],
                         sampled=sample is not None, space_band=first["space band"],
                         time_band=first["time band"], observed=first["observed"],
                         expected=first["expected"], ratio=first["ratio"], p=first["p"],
                         n_cells_p_lt_alpha=int((long["p"] < C.ALPHA).sum()), n_cells=len(long)))
    upsert(ctx.out / "knox_summary.csv", pd.DataFrame(rows), {"group": ctx.groups})


# =========================================================================== #
#  8 — association
# =========================================================================== #
def _support_features(ctx: Context, s: str, cnefe: gpd.GeoDataFrame) -> pd.DataFrame:
    """POI counts (CNEFE, point-in-polygon) and population (tract value, or
    area-share interpolation of it) per unit; income / literacy on tracts."""
    from crime.data.cleaning import POI_SPECIES
    from crime.data.units import areal_interpolate, assign_points

    A = C.ASSOCIATION
    u = ctx.units(s)
    uid = assign_points(cnefe, u)
    poi = pd.crosstab(uid, cnefe["poi"]).reindex(index=u["unit_id"], columns=list(POI_SPECIES.values()),
                                                  fill_value=0)
    feats = poi.copy()
    ta = ctx.tract_attributes()
    if s == "tract":
        tt = ta.set_index("unit_id")
        feats["pop_total"] = tt["pop_total"].reindex(u["unit_id"]).to_numpy()
        for c in A["features_tract_only"]:
            feats[c] = tt[c].reindex(u["unit_id"]).to_numpy()
    else:
        feats["pop_total"] = areal_interpolate(ta, u, ["pop_total"])["pop_total"].reindex(u["unit_id"]).to_numpy()
    feats.index.name = "unit_id"
    return feats


def step_assoc(ctx: Context, t: dict) -> None:
    from scipy.stats import spearmanr

    from crime.data.cleaning import cnefe_poi_points
    from crime.stats.bivariate import bivariate_moran, local_bivariate_moran

    A = C.ASSOCIATION
    cnefe = cnefe_poi_points(CNEFE_JSON).to_crs(CRS_METRIC)
    rows, local_rows, local_units = [], [], []
    for s in ctx.supports:
        feats = _support_features(ctx, s, cnefe)
        u = ctx.units(s)
        fcols = [c for c in (*A["features_all_supports"], *(A["features_tract_only"] if s == "tract" else ()))
                 if c in feats]
        for g in ctx.groups:
            ev = ctx.dataset(g, s).events
            year = pd.to_datetime(ev["data_ocorrencia"]).dt.year
            for y0, y1 in A["crime_years"]:
                cnt = ev.loc[year.between(y0, y1), "unit_id"].value_counts()
                gdf = u[["unit_id", "geometry"]].copy()
                gdf["crime_count"] = gdf["unit_id"].map(cnt).fillna(0).astype(float).to_numpy()
                for c in fcols:
                    gdf[c] = feats[c].reindex(gdf["unit_id"]).to_numpy(dtype=float)
                ds = Dataset(gdf=gdf, unit=s, years=(y0, y1))
                with timed(f"assoc: {g} x {s} x {y0}-{y1}", t), quiet():
                    for f in fcols:
                        ok = gdf[[f, "crime_count"]].notna().all(axis=1)
                        rho, rp = spearmanr(gdf.loc[ok, f], gdf.loc[ok, "crime_count"])
                        # prebuilt weights only when no unit is dropped; otherwise rebuilt on the subset
                        w = ctx.weights(s, A["weights"]) if ok.all() else A["weights"]
                        fx = bivariate_moran(ds, f, "crime_count", weights=w, permutations=A["permutations"],
                                             seed=C.SEED)
                        cx = bivariate_moran(ds, "crime_count", f, weights=w, permutations=A["permutations"],
                                             seed=C.SEED)
                        rows.append(dict(group=g, crime_years=f"{y0}-{y1}", support=s, feature=f, n=int(ok.sum()),
                                         spearman_rho=float(rho), spearman_p=float(rp),
                                         bv_I_feature_lag_crime=fx.I, bv_z_feature_lag_crime=fx.z_sim,
                                         bv_p_feature_lag_crime=fx.p_sim,
                                         bv_I_crime_lag_feature=cx.I, bv_z_crime_lag_feature=cx.z_sim,
                                         bv_p_crime_lag_feature=cx.p_sim))
                if s == A["local_support"] and (y0, y1) == tuple(C.YEARS):
                    with timed(f"assoc: local bivariate {g} crime x lag({A['local_feature']})", t), quiet():
                        lb = local_bivariate_moran(ds, "crime_count", A["local_feature"],
                                                   weights=ctx.weights(s, A["weights"]),
                                                   permutations=C.LISA_PERMUTATIONS, alpha=C.ALPHA,
                                                   fdr=C.FDR, seed=C.SEED)
                    vc = lb.gdf["label"].value_counts()
                    local_rows.append(dict(group=g, support=s, crime_years=f"{y0}-{y1}", x="crime_count",
                                           y=A["local_feature"], **{q: int(vc.get(q, 0)) for q in (*QUADS, "ns")}))
                    local_units.append(pd.DataFrame(dict(group=g, unit_id=lb.gdf["unit_id"].to_numpy(),
                                                         lisa_bv_I=lb.gdf["lisa_bv_I"].to_numpy(),
                                                         p_adj=lb.gdf["p_adjusted"].to_numpy(),
                                                         label=lb.gdf["label"].to_numpy())))
    keys = {"group": ctx.groups, "support": ctx.supports}
    upsert(ctx.out / "association.csv", pd.DataFrame(rows), keys)
    if local_rows:
        upsert(ctx.out / "association_local.csv", pd.DataFrame(local_rows), keys)
        upsert(ctx.out / "association_local_by_unit.parquet", pd.concat(local_units, ignore_index=True),
               {"group": ctx.groups})


STEP_FUNCS = {"when": step_when, "where": step_where, "change": step_change, "tsc": step_tsc,
              "maup": step_maup, "points": step_points, "knox": step_knox, "assoc": step_assoc}


# =========================================================================== #
#  main
# =========================================================================== #
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--groups", nargs="+", choices=C.GROUPS, help="crime groups (default: all configured)")
    ap.add_argument("--supports", nargs="+", choices=list(C.SUPPORTS), help="supports (default: all)")
    ap.add_argument("--steps", nargs="+", choices=C.STEPS, help="steps to run (default: all, in order)")
    ap.add_argument("--quick", action="store_true", help="one group, tract only (writes outputs/core_quick)")
    ap.add_argument("--out", type=Path, help="output directory (default outputs/core)")
    return ap.parse_args(argv)


def main(argv=None) -> None:
    a = parse_args(argv)
    groups = a.groups or (C.QUICK["groups"] if a.quick else C.GROUPS)
    supports = a.supports or (C.QUICK["supports"] if a.quick else tuple(C.SUPPORTS))
    steps = [s for s in C.STEPS if s in (a.steps or C.STEPS)]
    out = a.out or OUTPUTS_DIR / ("core_quick" if a.quick else "core")
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(out / "run_core.log", mode="a")])
    if not BULLETINS_PARQUET.exists():
        sys.exit(f"{BULLETINS_PARQUET} missing: run `make acquire clean-data` first")
    log.info("run_core: groups=%s supports=%s steps=%s -> %s", list(groups), list(supports), steps, out)
    ctx = Context(groups, supports, out)
    if "maup" in steps and C.MAUP_REFERENCE not in supports:
        log.info("maup: reference support %s is read from earlier outputs", C.MAUP_REFERENCE)

    man_path = out / "manifest.json"
    manifest = json.loads(man_path.read_text()) if man_path.exists() else {"steps": {}}
    t_all = time.perf_counter()
    with timed("weights diagnostics"):
        winfo = weights_info(ctx)
    for step in steps:
        log.info("== %s", step)
        t: dict = {}
        t0 = time.perf_counter()
        STEP_FUNCS[step](ctx, t)
        total = time.perf_counter() - t0
        log.info("== %s done in %.1f s", step, total)
        manifest["steps"][step] = {"seconds": round(total, 1), "groups": list(groups), "supports": list(supports),
                                   "finished_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
                                   "timings": t}
    manifest.update(provenance=provenance(), config=C.as_dict(), weights=winfo,
                    last_run={"groups": list(groups), "supports": list(supports), "steps": steps,
                              "seconds": round(time.perf_counter() - t_all, 1)})
    man_path.write_text(json.dumps(manifest, indent=2, default=str))
    log.info("run_core finished in %.1f s", time.perf_counter() - t_all)


if __name__ == "__main__":
    main()
