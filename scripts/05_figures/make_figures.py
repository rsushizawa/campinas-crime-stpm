"""Stage 05 — Figures: draw the core results of stage 04 as 300-dpi PNGs.

    python scripts/05_figures/make_figures.py                        # every group (make figures)
    python scripts/05_figures/make_figures.py --groups property drug
    python scripts/05_figures/make_figures.py --core outputs/core --out outputs/figures --basemap

Reads **only** the tables in ``outputs/core/`` (written by
``scripts/04_analyse/run_core.py``; meaning in ``docs/METHODS.md``) and the unit
geometries (``crime.data.units.load_units``). No statistic is computed here and
no database is needed; drawing reuses ``crime.viz``. Basemap tiles are off by
default so the script runs offline.

Per crime group, into ``outputs/figures/<group>/``:

    stl_<g>               monthly counts + STL trend / seasonal / residual
    kde_<g>               kernel density surface over the municipality
    ripley_nni_<g>        Ripley's L(d) - d with CSR envelope; Clark-Evans NNI
    gi_star_<g>           Gi* hot / cold spots, queen weights, every support
    lisa_<g>              LISA clusters / outliers, queen weights, every support
    ehsa_<support>_<g>    EHSA categories, quarterly bins (tract, hex0.5); ehsa_supports_<g> all supports
    tsc_map_<g>, tsc_profiles_<g>   time series clusters (tracts, value method)
    maup_supports_<g>, maup_weights_<g>   label agreement across supports / weights
    knox_<g>              Knox ratio, distance band x time band
    association_<g>, bivariate_local_<g>  Spearman rho and bivariate Moran's I; local map

Temporal-only groups (``core_config.TEMPORAL_ONLY_GROUPS``) get the STL figure only.
``outputs/figures/index.md`` lists every PNG with a one-line caption (built from
the per-group ``captions.json``, so piecemeal runs keep the other groups' entries).
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")

import matplotlib.colors as mcolors  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "04_analyse"))
import core_config as C  # noqa: E402

from crime.core.config import OUTPUTS_DIR  # noqa: E402
from crime.viz.charts import annotated_heatmap, cluster_profiles, seasonal_plot  # noqa: E402
from crime.viz.frame import map_frame  # noqa: E402
from crime.viz.maps import (  # noqa: E402
    category_legend_handles,
    category_map,
    ehsa_legend_handles,
    ehsa_map,
    hotspot_map,
    lisa_map,
)
from crime.viz.style import PlotStyle  # noqa: E402

STYLE = PlotStyle(font_size=9, title_size=10)
FINE_STYLE = replace(STYLE, edge_width=0.05)       # regular grids: hairline edges
PERIOD = f"{C.YEARS[0]}–{C.YEARS[1]}"
SUPPORT_ORDER = ["tract", "utb", "hex0.5", "hex0.1", "sq0.5"]

GROUP_NAMES = {
    "all": "all recorded crime", "property": "property crime", "bodily_harm": "bodily harm",
    "traffic": "traffic crime", "drug": "drug and weapon offences", "violent": "violent crime",
    "sexual": "sexual crime",
}
SUPPORT_NAMES = {
    "tract": "Census tracts (IBGE 2022)", "utb": "UTB planning units",
    "hex0.5": "Hexagons, 0.5 km²", "hex0.1": "Hexagons, 0.1 km²", "sq0.5": "Squares, 0.5 km²",
}
FEATURE_NAMES = {
    "pop_total": "Resident population", "n_commercial": "Commercial addresses",
    "n_education": "Education addresses", "n_health": "Health addresses",
    "n_religious": "Religious addresses", "income_head_mean": "Mean income of household heads",
    "literacy_rate": "Literacy rate, age 15+",
}
GI_LABELS = {"hotspot": "Hot spot (Gi* z > 0, adjusted p < 0.05)",
             "coldspot": "Cold spot (Gi* z < 0, adjusted p < 0.05)",
             "ns": "Not significant", "no data": "No data (unit without neighbours)"}
LISA_LABELS = {"HH": "High-High: high count, high-count neighbours",
               "HL": "High-Low: high count, low-count neighbours",
               "LH": "Low-High: low count, high-count neighbours",
               "LL": "Low-Low: low count, low-count neighbours",
               "ns": "Not significant", "no data": "No data (unit without neighbours)"}
LL_NOTE = ("Low-Low on the fine grids are almost all zero-count cells whose whole neighbourhood is zero: "
           "the esda permutation test counts ties only in the upper tail and labels them significant "
           "(docs/METHODS.md, 'esda tie handling'). They are not low-crime clusters.")


def gname(g: str) -> str:
    return GROUP_NAMES.get(g, g.replace("_", " "))


def sname(s: str) -> str:
    return SUPPORT_NAMES.get(s, s)


# =========================================================================== #
#  inputs
# =========================================================================== #
@functools.lru_cache(maxsize=None)
def load_support(support: str):
    """Unit polygons of ``support`` (``unit_id``, ``area_km2``, geometry, EPSG:31983)."""
    from crime.data.units import load_units

    return load_units(**C.SUPPORTS[support])


@functools.lru_cache(maxsize=None)
def boundary():
    """The municipality: the dissolved census tracts."""
    t = load_support("tract")
    return t[["geometry"]].dissolve()


def supports_with(core: Path, kind: str) -> list[str]:
    extra = sorted(p.stem for p in (core / kind).glob("*.parquet") if p.stem not in SUPPORT_ORDER)
    return [s for s in SUPPORT_ORDER + extra if (core / kind / f"{s}.parquet").exists()]


def read_by_unit(core: Path, kind: str, support: str, **eq) -> pd.DataFrame:
    filters = [(k, "==", v) for k, v in eq.items()]
    return pd.read_parquet(core / kind / f"{support}.parquet", filters=filters or None)


def on_units(support: str, d: pd.DataFrame, cols: list[str], fill: dict | None = None):
    """Every unit of ``support`` with ``cols`` of ``d`` joined on ``unit_id`` (missing -> ``fill``)."""
    u = load_support(support)[["unit_id", "geometry"]]
    g = u.merge(d[["unit_id", *cols]], on="unit_id", how="left")
    for c, v in (fill or {}).items():
        g[c] = g[c].fillna(v)
    return g


# =========================================================================== #
#  output
# =========================================================================== #
class Sink:
    """Saves figures of one group and records their captions."""

    def __init__(self, root: Path, group: str):
        self.dir = root / group
        self.dir.mkdir(parents=True, exist_ok=True)
        self.group = group
        self.captions: dict[str, str] = {}

    def save(self, fig, name: str, caption: str) -> None:
        path = self.dir / f"{name}.png"
        fig.savefig(path, dpi=STYLE.save_dpi, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        self.captions[path.name] = caption
        print(f"  {path}")

    def close(self) -> None:
        (self.dir / "captions.json").write_text(json.dumps(self.captions, indent=2, ensure_ascii=False))


def write_index(root: Path) -> Path:
    groups = [*C.GROUPS, *C.TEMPORAL_ONLY_GROUPS]
    groups += sorted(p.parent.name for p in root.glob("*/captions.json") if p.parent.name not in groups)
    lines = ["# Figures", "",
             "Drawn by `scripts/05_figures/make_figures.py` (`make figures`) from `outputs/core/` only; "
             "methods and caveats in `docs/METHODS.md`. 300 dpi PNG. `all` is the primary group.", ""]
    for g in groups:
        p = root / g / "captions.json"
        if not p.exists():
            continue
        lines += [f"## {g} — {gname(g)}", ""]
        for f, cap in json.loads(p.read_text()).items():
            lines.append(f"- [`{g}/{f}`]({g}/{f}) — {cap}")
        lines.append("")
    out = root / "index.md"
    out.write_text("\n".join(lines))
    return out


def panel_grid(n: int, *, w: float = 5.0, h: float = 4.8):
    """``n`` map panels plus one spare cell (legend / notes) on a grid of up to 3 columns."""
    ncols = 3 if n + 1 > 2 else n + 1
    nrows = math.ceil((n + 1) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(w * ncols, h * nrows), squeeze=False)
    axes = list(axes.ravel())
    for ax in axes[n + 1:]:
        ax.set_axis_off()
    spare = axes[n]
    spare.set_axis_off()
    return fig, axes[:n], spare


def notes(ax, text: str, y: float = 0.42) -> None:
    import textwrap

    ax.text(0.02, y, "\n".join(textwrap.wrap(text, 62)), transform=ax.transAxes, va="top",
            ha="left", fontsize=STYLE.font_size - 1, color="#252525")


def map_style(support: str) -> PlotStyle:
    """Regular grids get hairline edges (their many cells would otherwise read as a mesh)."""
    return FINE_STYLE if support not in ("tract", "utb") else STYLE


# =========================================================================== #
#  1 — when: monthly series + STL
# =========================================================================== #
def fig_stl(core: Path, sink: Sink, g: str) -> None:
    p = core / f"stl_{g}.csv"
    if not p.exists():
        return
    stl = pd.read_csv(p, index_col="month", parse_dates=["month"])
    ms = pd.read_csv(core / "monthly_series.csv", index_col="month", parse_dates=["month"])
    fig, axes = seasonal_plot(SimpleNamespace(stl=stl), style=replace(STYLE, figsize=(9, 8)),
                              title=f"Monthly counts of {gname(g)}, {PERIOD}: STL decomposition "
                                    f"(annual period, robust LOESS)")
    if f"{g}_in_tract" in ms and ms[f"{g}_in_tract"].sum() > 0:
        axes[0].plot(ms.index, ms[f"{g}_in_tract"], color="#e08214", lw=1.0,
                     label="Geocoded inside a census tract (used in the maps)")
        axes[0].lines[0].set_label("All bulletins with an occurrence date in the window")
        lo, hi = axes[0].get_ylim()
        axes[0].set_ylim(lo - 0.45 * (hi - lo), hi)
        axes[0].legend(fontsize=STYLE.font_size - 2, loc="lower center", ncol=2, framealpha=0.9)
    for ax, lab in zip(axes, ("Observed\n(crimes per month)", "Trend\n(crimes per month)",
                              "Seasonal\n(crimes per month)", "Residual\n(crimes per month)")):
        ax.set_ylabel(lab, rotation=0, ha="right", va="center", fontsize=STYLE.font_size - 1)
    axes[-1].set_xlabel("Month of occurrence")
    fig.tight_layout()
    sink.save(fig, f"stl_{g}", f"Monthly counts of {gname(g)}, {PERIOD} (all bulletins and those geocoded "
                               f"in a tract) and its STL trend, seasonal and residual components.")


# =========================================================================== #
#  2 — KDE surface
# =========================================================================== #
def fig_kde(core: Path, sink: Sink, g: str, pts: pd.DataFrame) -> None:
    p = core / f"kde_{g}.parquet"
    if not p.exists():
        return
    k = pd.read_parquet(p)
    xs, xi = np.unique(np.round(k["x"].to_numpy(), 1), return_inverse=True)
    ys, yi = np.unique(np.round(k["y"].to_numpy(), 1), return_inverse=True)
    cell = float(np.median(np.diff(xs))) if len(xs) > 1 else 100.0
    img = np.full((len(ys), len(xs)), np.nan, dtype=np.float32)
    img[yi, xi] = k["density_per_km2"].to_numpy(dtype=np.float32)
    del k
    row = pts[(pts["group"] == g) & (pts["variant"] == "all")]
    bw = float(row["kde_bandwidth_m"].iloc[0]) if len(row) and pd.notna(row["kde_bandwidth_m"].iloc[0]) else None

    b = boundary()
    style = replace(STYLE, figsize=(8.5, 8))
    style.apply()
    fig, ax = plt.subplots(figsize=style.figsize)
    cmap = plt.get_cmap(STYLE.cmap).copy()
    cmap.set_under("#f0f0f0")
    cmap.set_bad((1, 1, 1, 0))
    vmax = float(np.nanmax(img)) if np.isfinite(img).any() else 1.0
    img[np.isfinite(img) & (img < 1.0)] = 0.5          # below the log floor -> "under" colour
    norm = mcolors.LogNorm(vmin=1.0, vmax=max(vmax, 10.0))
    im = ax.imshow(img, origin="lower", cmap=cmap, norm=norm, interpolation="nearest",
                   extent=(xs[0] - cell / 2, xs[-1] + cell / 2, ys[0] - cell / 2, ys[-1] + cell / 2))
    b.boundary.plot(ax=ax, color=STYLE.boundary_color, linewidth=STYLE.boundary_width)
    x0, y0, x1, y1 = b.total_bounds
    pad = 0.02 * (x1 - x0)
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y0 - pad, y1 + pad)
    ax.set_aspect("equal")
    map_frame(ax, b, STYLE)
    fig.colorbar(im, ax=ax, shrink=0.7, extend="min",
                 label="Kernel density of geocoded crimes (crimes per km², log scale; < 1 in grey)")
    bwt = f", bandwidth {bw:,.0f} m" if bw else ""
    ax.set_title(f"Kernel density of {gname(g)}, {PERIOD}\n(quartic kernel{bwt}, {cell:.0f} m cells)",
                 fontsize=STYLE.title_size)
    fig.tight_layout()
    sink.save(fig, f"kde_{g}", f"Quartic kernel density surface of geocoded {gname(g)} {PERIOD} "
                               f"(crimes per km², log colour scale) over the municipal boundary.")


# =========================================================================== #
#  3 — Ripley's L and NNI
# =========================================================================== #
VARIANT_NAMES = {"all": "All geocoded points", "distinct": "Distinct locations (one point per coordinate)"}
VARIANT_COLORS = {"all": "#2c5f9e", "distinct": "#d95f02"}


def fig_ripley(core: Path, sink: Sink, g: str, pts: pd.DataFrame) -> None:
    p = core / f"ripley_{g}.csv"
    if not p.exists():
        return
    r = pd.read_csv(p)
    nn = pts[pts["group"] == g].set_index("variant")
    STYLE.apply()
    fig, (ax, axn) = plt.subplots(1, 2, figsize=(12, 5), gridspec_kw={"width_ratios": [2.6, 1]})
    for v, d in r.groupby("variant", sort=False):
        d = d.sort_values("distance_m")
        c = VARIANT_COLORS.get(v, "black")
        total = int(nn.loc[v, "n_points"]) if v in nn.index else int(d["n_points"].iloc[0])
        used = int(d["n_points"].iloc[0])
        ntxt = f"n = {used:,}" + (f" sampled of {total:,}" if used < total else "")
        ax.fill_between(d["distance_m"], d["env_low"] - d["distance_m"], d["env_high"] - d["distance_m"],
                        color=c, alpha=0.18, lw=0)
        ax.plot(d["distance_m"], d["L_minus_d"], color=c, lw=1.6, marker="o", ms=2.5,
                label=f"{VARIANT_NAMES.get(v, v)} ({ntxt})")
    ax.fill_between([], [], [], color="grey", alpha=0.25,
                    label="CSR envelope: min–max of 99 simulations at the same n")
    ax.axhline(0, color="black", lw=0.7, ls="--")
    ax.set_xlabel("Distance d (m)")
    ax.set_ylabel("L(d) − d (m)   [> envelope = clustered]")
    ax.set_title(f"Ripley's K as Besag's L, {gname(g)}, {PERIOD}\n"
                 "against complete spatial randomness (CSR) in the municipality, no edge correction",
                 fontsize=STYLE.title_size)
    ax.legend(fontsize=STYLE.font_size - 2, loc="upper left", framealpha=0.9)

    vs = [v for v in ("all", "distinct") if v in nn.index]
    ratios = [float(nn.loc[v, "nni_ratio"]) for v in vs]
    axn.bar(range(len(vs)), ratios, color=[VARIANT_COLORS[v] for v in vs], width=0.6)
    axn.axhline(1, color="black", lw=0.8, ls="--")
    axn.text(len(vs) - 0.5, 1.0, "R = 1: random", ha="right", va="bottom", fontsize=STYLE.font_size - 2)
    for i, v in enumerate(vs):
        q = nn.loc[v]
        axn.text(i, ratios[i] + 0.03, f"R = {q['nni_ratio']:.2f}\nobserved {q['nni_observed_m']:.1f} m\n"
                 f"expected {q['nni_expected_m']:.1f} m\nz = {q['nni_z']:,.0f}\nn = {int(q['n_points']):,}",
                 ha="center", va="bottom", fontsize=STYLE.font_size - 2)
    axn.set_xticks(range(len(vs)), ["All points", "Distinct\nlocations"][:len(vs)])
    axn.set_ylim(0, max(1.6, max(ratios, default=1) + 0.6))
    axn.set_ylabel("Nearest-neighbour index R\n(observed / expected mean distance under CSR)")
    axn.set_title("Clark–Evans nearest-neighbour index", fontsize=STYLE.title_size)
    fig.tight_layout()
    sink.save(fig, f"ripley_nni_{g}", f"Ripley's L(d) − d of geocoded {gname(g)} (all points and distinct "
                                      f"locations) with 99-simulation CSR envelopes, and the Clark–Evans "
                                      f"nearest-neighbour index R.")


# =========================================================================== #
#  4/5 — Gi* and LISA panels (queen)
# =========================================================================== #
def _static(core: Path, g: str) -> dict[str, pd.DataFrame]:
    return {s: read_by_unit(core, "static_by_unit", s, group=g, weights=C.PRIMARY_WEIGHTS)
            for s in supports_with(core, "static_by_unit")}


def fig_gi(sink: Sink, g: str, static: dict, basemap) -> None:
    if not static:
        return
    fig, axes, spare = panel_grid(len(static))
    for ax, (s, d) in zip(axes, static.items()):
        gdf = on_units(s, d.rename(columns={"gi_label": "label"}), ["label"], {"label": "no data"})
        n = gdf["label"].value_counts()
        hotspot_map(SimpleNamespace(gdf=gdf, value_col="crime_count"), ax=ax, legend=False, basemap=basemap,
                    mask_ns=False, style=map_style(s),
                    title=f"{sname(s)}\n{n.get('hotspot', 0):,} hot, {n.get('coldspot', 0):,} cold "
                          f"of {len(gdf):,} units")
    keys = ["hotspot", "coldspot", "ns", "no data"]
    spare.legend(handles=category_legend_handles(STYLE.hotspot_palette, GI_LABELS, keys),
                 loc="upper left", title="Gi* category", fontsize=STYLE.font_size, frameon=False)
    notes(spare, "Getis–Ord Gi* z of the crime count per unit, queen contiguity weights; Benjamini–Hochberg "
                 "false discovery rate at 0.05 within each map. Every unit is drawn.")
    fig.suptitle(f"Getis–Ord Gi* hot and cold spots of {gname(g)} counts, {PERIOD}, queen contiguity weights",
                 fontsize=STYLE.title_size + 2)
    fig.tight_layout()
    sink.save(fig, f"gi_star_{g}", f"Gi* category (hot / cold / not significant, FDR 0.05) of {gname(g)} "
                                   f"counts, queen weights, on census tracts, UTBs and the 0.5 / 0.1 km² "
                                   f"hexagon and 0.5 km² square grids.")


def fig_lisa(sink: Sink, g: str, static: dict, basemap) -> None:
    if not static:
        return
    fig, axes, spare = panel_grid(len(static))
    for ax, (s, d) in zip(axes, static.items()):
        gdf = on_units(s, d.rename(columns={"lisa_label": "label"}), ["label", "crime_count"],
                       {"label": "no data"})
        n = gdf["label"].value_counts()
        ll0 = int(((gdf["label"] == "LL") & (gdf["crime_count"] == 0)).sum())
        lisa_map(SimpleNamespace(gdf=gdf, value_col="crime_count"), ax=ax, legend=False, basemap=basemap,
                 mask_ns=False, style=map_style(s),
                 title=f"{sname(s)}, {len(gdf):,} units\nHH {n.get('HH', 0):,} · HL {n.get('HL', 0):,} · "
                       f"LH {n.get('LH', 0):,} · LL {n.get('LL', 0):,} ({ll0:,} zero-count)")
    keys = ["HH", "HL", "LH", "LL", "ns", "no data"]
    spare.legend(handles=category_legend_handles(STYLE.lisa_palette, LISA_LABELS, keys),
                 loc="upper left", title="Local Moran's I (LISA) category", fontsize=STYLE.font_size,
                 frameon=False)
    notes(spare, "Local Moran's I of the crime count per unit, queen weights, 499 permutations, "
                 "Benjamini–Hochberg FDR at 0.05 within each map (on large supports this can leave no "
                 "significant unit). " + LL_NOTE)
    fig.suptitle(f"Local Moran's I (LISA) clusters and outliers of {gname(g)} counts, {PERIOD}, "
                 f"queen contiguity weights", fontsize=STYLE.title_size + 2)
    fig.tight_layout()
    sink.save(fig, f"lisa_{g}", f"LISA cluster / outlier category of {gname(g)} counts, queen weights, FDR "
                                f"0.05, on every support; Low-Low on fine grids are zero-count cells "
                                f"(esda tie rule, METHODS.md).")


# =========================================================================== #
#  6 — EHSA
# =========================================================================== #
EHSA_DETAIL = ("tract", "hex0.5")


def _ehsa(core: Path, g: str) -> dict[str, pd.DataFrame]:
    return {s: read_by_unit(core, "ehsa_by_unit", s, group=g, weights=C.PRIMARY_WEIGHTS,
                            time_unit=C.PRIMARY_TIME_UNIT)
            for s in supports_with(core, "ehsa_by_unit")}


def _family_counts(cats: pd.Series) -> str:
    hot = int(cats.str.endswith("hotspot").sum())
    cold = int(cats.str.endswith("coldspot").sum())
    return f"{hot:,} hot-spot, {cold:,} cold-spot categories of {len(cats):,} units"


def fig_ehsa(sink: Sink, g: str, ehsa: dict, basemap) -> None:
    if not ehsa:
        return
    tu = {"quarter": "quarterly", "month": "monthly"}.get(C.PRIMARY_TIME_UNIT, C.PRIMARY_TIME_UNIT)
    spec = (f"{tu} bins {PERIOD}, queen weights, space-time neighbourhood, Mann–Kendall (Hamed–Rao) "
            f"trend of the Gi* z series")
    frames = {s: on_units(s, d, ["category"], {"category": "no data"}) for s, d in ehsa.items()}
    for s in [s for s in EHSA_DETAIL if s in frames]:
        gdf = frames[s]
        STYLE.apply()
        fig, ax = plt.subplots(figsize=(10.5, 8))
        ehsa_map(SimpleNamespace(gdf=gdf), ax=ax, legend="none", basemap=basemap, mask_ns=False,
                 style=map_style(s), title=f"Emerging hot spot analysis of {gname(g)}, {sname(s)}\n"
                                           f"{_family_counts(gdf['category'])}")
        cnt = gdf["category"].value_counts().to_dict()
        ax.legend(handles=ehsa_legend_handles(gdf["category"].values, counts=cnt, style=STYLE),
                  loc="center left", bbox_to_anchor=(1.09, 0.5), fontsize=STYLE.font_size - 1,
                  title="EHSA category (n units)", framealpha=0.9, handlelength=1.4)
        fig.text(0.01, 0.01, spec, fontsize=STYLE.font_size - 2, color="#404040")
        fig.tight_layout(rect=(0, 0.03, 1, 1))
        sink.save(fig, f"ehsa_{s.replace('.', '_')}_{g}",
                  f"EHSA category of every unit ({sname(s)}) for {gname(g)} ({spec}); "
                  f"'no pattern' in grey.")

    fig, axes, spare = panel_grid(len(frames))
    union = set()
    for ax, (s, gdf) in zip(axes, frames.items()):
        union |= set(gdf["category"])
        ehsa_map(SimpleNamespace(gdf=gdf), ax=ax, legend="none", basemap=basemap, mask_ns=False,
                 style=map_style(s), title=f"{sname(s)}\n{_family_counts(gdf['category'])}")
    spare.legend(handles=ehsa_legend_handles(sorted(union), style=STYLE), loc="upper left",
                 title="EHSA category", fontsize=STYLE.font_size - 1, frameon=False, ncol=2)
    notes(spare, spec[0].upper() + spec[1:] + ". Every unit is drawn; 'no pattern' in grey.", y=0.3)
    fig.suptitle(f"Emerging hot spot analysis of {gname(g)} on every support", fontsize=STYLE.title_size + 2)
    fig.tight_layout()
    sink.save(fig, f"ehsa_supports_{g}", f"EHSA categories of {gname(g)} on every support ({tu} bins, queen "
                                         f"weights, space-time neighbourhood).")


# =========================================================================== #
#  7 — time series clustering
# =========================================================================== #
TSC_SUPPORT, TSC_METHOD = "tract", "value"


def fig_tsc(core: Path, sink: Sink, g: str, basemap) -> None:
    p = core / "tsc_by_unit" / f"{TSC_SUPPORT}.parquet"
    if not p.exists():
        return
    d = read_by_unit(core, "tsc_by_unit", TSC_SUPPORT, group=g, method=TSC_METHOD)
    prof = pd.read_csv(core / "tsc_profiles.csv")
    prof = prof[(prof["group"] == g) & (prof["support"] == TSC_SUPPORT) & (prof["method"] == TSC_METHOD)]
    if d.empty or prof.empty:
        return
    sizes = pd.read_csv(core / "tsc_sizes.csv")
    sizes = sizes[(sizes["group"] == g) & (sizes["support"] == TSC_SUPPORT)
                  & (sizes["method"] == TSC_METHOD)].set_index("cluster")
    k = int(d.loc[d["cluster"] >= 0, "cluster"].nunique())
    cmap = plt.get_cmap("tab10" if k <= 10 else "tab20")

    def lab(c):
        if c < 0:
            return f"Not clustered: no event in {PERIOD} ({int((d['cluster'] < 0).sum()):,} tracts)"
        n = int((d["cluster"] == c).sum())
        m = sizes.loc[c, "mean_total_events"] if c in sizes.index else np.nan
        return f"Cluster {c}: {n:,} tracts, mean {m:,.1f} crimes per tract"

    ids = sorted(d["cluster"].unique())
    d = d.assign(cl=d["cluster"].map({c: lab(c) for c in ids}))
    palette = {lab(c): ("#f0f0f0" if c < 0 else mcolors.to_hex(cmap(c % cmap.N))) for c in ids}
    order = [lab(c) for c in ids if c >= 0] + [lab(c) for c in ids if c < 0]
    gdf = on_units(TSC_SUPPORT, d, ["cl"], {"cl": "no data"})
    fig, ax = category_map(gdf, "cl", palette, order=order + ["no data"], basemap=basemap,
                           label_names={"no data": "No data"},
                           style=replace(STYLE, figsize=(9.5, 8), legend_loc="upper left"),
                           title=f"Time series clusters of monthly {gname(g)} counts, {sname(TSC_SUPPORT)}, "
                                 f"{PERIOD}\n(Esri 'value' method, k = {k} chosen by pseudo-F; 0 = quietest)")
    leg = ax.get_legend()
    if leg is not None:
        leg.set_bbox_to_anchor((1.09, 1.0))
        leg.set_title("Cluster (by mean total crimes)")
    fig.tight_layout()
    sink.save(fig, f"tsc_map_{g}", f"Time-series cluster of every census tract for monthly {gname(g)} counts "
                                   f"(value method, k by pseudo-F; clusters ordered by mean total).")

    prof = prof.assign(cn=prof["cluster"].str.extract(r"(-?\d+)")[0].astype(int))
    wide = prof.pivot(index="cn", columns="period", values="mean_count").sort_index()
    wide = wide.reindex(columns=sorted(wide.columns))
    wide.columns = pd.to_datetime(wide.columns)
    wide.index = [f"Cluster {c}" for c in wide.index]
    cl = d.loc[d["cluster"] >= 0, ["cluster"]]
    fig, (axp, axb) = cluster_profiles(SimpleNamespace(profiles=wide, gdf=cl, method=TSC_METHOD, k=k),
                                       style=replace(STYLE, figsize=(12, 9)),
                                       title=f"Mean monthly profile of each time series cluster, {gname(g)}, "
                                             f"{sname(TSC_SUPPORT)} ({TSC_METHOD} method, k = {k})")
    vals = wide.to_numpy(dtype=float)
    pos = vals[vals > 0]
    if pos.size == vals.size and pos.max() / pos.min() > 20:      # log only without zero months
        axp.set_yscale("log")
        axp.set_ylabel("Mean crimes per tract per month (log scale)")
    else:
        axp.set_ylabel("Mean crimes per tract per month")
    axp.set_xlabel("Month of occurrence")
    axb.set_xlabel("Number of tracts")
    for bar in axb.patches:
        axb.annotate(f"{bar.get_width():,.0f}", (bar.get_width(), bar.get_y() + bar.get_height() / 2),
                     xytext=(3, 0), textcoords="offset points", va="center", fontsize=STYLE.font_size - 1)
    axb.set_xlim(0, axb.get_xlim()[1] * 1.2)
    fig.tight_layout()
    sink.save(fig, f"tsc_profiles_{g}", f"Mean monthly {gname(g)} count per tract in each time-series cluster "
                                        f"(value method) and the number of tracts per cluster.")


# =========================================================================== #
#  8 — MAUP
# =========================================================================== #
METHOD_NAMES = {"gi_star": "Gi* hot spots (static)", "lisa": "LISA (High-High as 'hot')",
                "ehsa_quarter": "EHSA, quarterly bins", "ehsa_month": "EHSA, monthly bins"}


def _pair_panels(fig_axes, mats: list[tuple[pd.DataFrame, str, str]], xlabel: str, ylabel: str) -> None:
    for ax, (m, title, cbar) in zip(fig_axes, mats):
        annotated_heatmap(m, ax=ax, cmap="viridis", vmin=0, vmax=1, cbar_label=cbar, title=title,
                          xlabel=xlabel, ylabel=ylabel, xrotation=30, annot_size=STYLE.font_size - 1, style=STYLE)


def fig_maup(core: Path, sink: Sink, g: str) -> None:
    p = core / "maup_supports.csv"
    if p.exists():
        m = pd.read_csv(p)
        m = m[m["group"] == g]
        if not m.empty:
            cols = [s for s in SUPPORT_ORDER if s in set(m["support"])]
            piv = {c: m.pivot(index="method", columns="support", values=c).reindex(columns=cols)
                   for c in ("hotspot_jaccard", "label_agreement")}
            for c in piv:
                piv[c].index = [METHOD_NAMES.get(i, i) for i in piv[c].index]
                piv[c].columns = [sname(s) for s in piv[c].columns]
            STYLE.apply()
            fig, axes = plt.subplots(1, 2, figsize=(13, 3.8))
            ref = sname(C.MAUP_REFERENCE)
            _pair_panels(axes, [(piv["hotspot_jaccard"], "Hot-spot Jaccard index:\ntracts hot on both maps / hot on either",
                                 "Jaccard index"),
                                (piv["label_agreement"], "Label agreement:\nshare of tracts with the same label",
                                 "Share of tracts")],
                         f"Support overlaid onto the {sname(C.MAUP_REFERENCE)}", "")
            fig.suptitle(f"Modifiable areal unit problem, {gname(g)}: agreement of each support's labels "
                         f"with the {ref} map ({C.PRIMARY_WEIGHTS} weights)", fontsize=STYLE.title_size + 1)
            fig.tight_layout()
            sink.save(fig, f"maup_supports_{g}", f"Hot-spot Jaccard index and label agreement between the "
                                                 f"tract map and each other support overlaid onto tracts "
                                                 f"(Gi* and EHSA), {gname(g)}.")
    p = core / "maup_weights.csv"
    if p.exists():
        m = pd.read_csv(p)
        m = m[m["group"] == g]
        if not m.empty:
            wn = {"queen": "queen", "rook": "rook", "knn": f"{C.KNN_K}-nearest"}
            m = m.assign(pair=m["weights_a"].map(wn).fillna(m["weights_a"]) + " vs "
                         + m["weights_b"].map(wn).fillna(m["weights_b"]),
                         sup=pd.Categorical(m["support"], [s for s in SUPPORT_ORDER if s in set(m["support"])]
                                            + sorted(set(m["support"]) - set(SUPPORT_ORDER))),
                         meth=pd.Categorical(m["method"], [k for k in METHOD_NAMES if k in set(m["method"])]
                                             + sorted(set(m["method"]) - set(METHOD_NAMES))))
            m = m.sort_values(["sup", "meth"])
            m["row"] = [f"{sname(s)} · {METHOD_NAMES.get(k, k)}" for s, k in zip(m["support"], m["method"])]
            pairs = list(dict.fromkeys(m["pair"]))
            rows = list(dict.fromkeys(m["row"]))
            piv = {c: m.pivot(index="row", columns="pair", values=c).reindex(index=rows, columns=pairs)
                   for c in ("hot_jaccard", "label_agreement")}
            STYLE.apply()
            fig, axes = plt.subplots(1, 2, figsize=(13, 0.32 * len(rows) + 2.2))
            _pair_panels(axes, [(piv["hot_jaccard"], "Hot-spot (High-High) Jaccard index:\nunits hot under both / either",
                                 "Jaccard index"),
                                (piv["label_agreement"], "Label agreement:\nshare of units with the same label",
                                 "Share of units")],
                         "Pair of spatial weights", "")
            axes[1].set_yticklabels([])
            fig.text(0.5, 0.005, f"queen / rook: contiguity; {C.KNN_K}-nearest: k = {C.KNN_K} nearest "
                                 f"neighbours between unit centroids", ha="center", fontsize=STYLE.font_size - 1)
            fig.suptitle(f"Sensitivity to the spatial weights, {gname(g)}: agreement of unit labels between "
                         f"weight pairs", fontsize=STYLE.title_size + 1)
            fig.tight_layout()
            sink.save(fig, f"maup_weights_{g}", f"Hot-spot Jaccard index and label agreement between queen, "
                                                f"rook and 5-nearest-neighbour weights, per support and method, "
                                                f"{gname(g)}.")


# =========================================================================== #
#  9 — Knox
# =========================================================================== #
def fig_knox(core: Path, sink: Sink, g: str) -> None:
    p = core / f"knox_{g}.csv"
    if not p.exists():
        return
    k = pd.read_csv(p)
    sb, tb = list(dict.fromkeys(k["space band"])), list(dict.fromkeys(k["time band"]))
    ratio = k.pivot(index="space band", columns="time band", values="ratio").reindex(index=sb, columns=tb)
    sig = k.pivot(index="space band", columns="time band", values="p").reindex(index=sb, columns=tb) < C.ALPHA
    v = ratio.to_numpy(dtype=float)
    norm = mcolors.TwoSlopeNorm(vcenter=1.0, vmin=min(0.9, np.nanmin(v)), vmax=max(1.1, np.nanmax(v)))
    STYLE.apply()
    fig, ax = plt.subplots(figsize=(8, 5))
    annotated_heatmap(ratio, ax=ax, cmap="RdBu_r", norm=norm, marks=sig, xrotation=0, annot_size=STYLE.font_size + 1, style=STYLE,
                      cbar_label="Knox ratio: observed / expected pairs (1 = no interaction)",
                      xlabel="Time between the two events (days)",
                      ylabel="Distance between the two events (m)")
    ax.set_xticklabels([t.replace(" days", "") for t in tb])
    ax.set_yticklabels([s.replace(" m", "") for s in sb])
    n_used, n_tot = int(k["n_events_used"].iloc[0]), int(k["n_events_total"].iloc[0])
    smp = f"random sample of {n_used:,} of {n_tot:,} events" if n_used < n_tot else f"{n_tot:,} events"
    ax.set_title(f"Knox near-repeat test, {gname(g)}, {PERIOD} ({smp})\n"
                 f"bold, * and outline: one-sided permutation p < {C.ALPHA} "
                 f"(999 date permutations, not adjusted across cells)", fontsize=STYLE.title_size)
    fig.tight_layout()
    sink.save(fig, f"knox_{g}", f"Knox ratio (observed / expected event pairs) of {gname(g)} by distance "
                                f"band × time band; cells with permutation p < 0.05 marked.")


# =========================================================================== #
#  10 — association
# =========================================================================== #
SCALE_NAMES = {"count": "raw counts per unit", "per_km2": "densities (per km²)"}


def fig_association(core: Path, sink: Sink, g: str, basemap) -> None:
    p = core / "association.csv"
    if p.exists():
        a = pd.read_csv(p)
        yrs = f"{C.YEARS[0]}-{C.YEARS[1]}"
        a = a[(a["group"] == g) & (a["crime_years"] == yrs)]
        scales = [s for s in ("count", "per_km2") if s in set(a["scale"])]
        if scales:
            cols = [s for s in SUPPORT_ORDER if s in set(a["support"])]
            nfeat = {sc: a.loc[a["scale"] == sc, "feature"].nunique() for sc in scales}
            STYLE.apply()
            fig, axes = plt.subplots(len(scales), 2, figsize=(14, 1.0 + sum(0.55 * n + 1.2 for n in nfeat.values())),
                                     squeeze=False, gridspec_kw={"height_ratios": [nfeat[s] + 1 for s in scales]})
            for r, sc in enumerate(scales):
                d = a[a["scale"] == sc]
                feats = [f for f in FEATURE_NAMES if f in set(d["feature"])] + \
                        sorted(set(d["feature"]) - set(FEATURE_NAMES))
                for c, (val, pcol, stat) in enumerate((
                        ("spearman_rho", "spearman_p", "Spearman's ρ (crime vs feature)"),
                        ("bv_I_crime_lag_feature", "bv_p_crime_lag_feature",
                         "Bivariate Moran's I (crime vs spatial lag of feature)"))):
                    m = d.pivot(index="feature", columns="support", values=val).reindex(index=feats, columns=cols)
                    sig = d.pivot(index="feature", columns="support", values=pcol).reindex(index=feats,
                                                                                           columns=cols) < C.ALPHA
                    unit = " per km²" if sc == "per_km2" else ""
                    m.index = [FEATURE_NAMES.get(f, f) + (unit if f in C.ASSOCIATION["features_all_supports"]
                                                          else "") for f in m.index]
                    m.columns = [sname(s) for s in m.columns]
                    annotated_heatmap(m, ax=axes[r, c], vmin=-1, vmax=1, marks=sig, xrotation=20, annot_size=STYLE.font_size, style=STYLE,
                                      cbar_label=stat.split(" (")[0], title=f"{stat}, {SCALE_NAMES[sc]}")
                    if c == 1:
                        axes[r, c].set_yticklabels([])
            fig.suptitle(f"Association of {gname(g)} ({PERIOD}) with urban features (CNEFE 2022 addresses, "
                         f"2022 census)\nbold, * and outline: p < {C.ALPHA} (Spearman: analytic, no spatial "
                         f"adjustment; Moran: 999 permutations, queen weights)", fontsize=STYLE.title_size + 1)
            fig.tight_layout()
            sink.save(fig, f"association_{g}", f"Spearman's ρ and global bivariate Moran's I between {gname(g)} "
                                               f"and each urban feature, per support, on raw counts and on "
                                               f"densities per km².")
    p = core / "association_local_by_unit.parquet"
    if p.exists():
        d = pd.read_parquet(p, filters=[("group", "==", g)])
        if d.empty:
            return
        s = C.ASSOCIATION["local_support"]
        feat = FEATURE_NAMES.get(C.ASSOCIATION["local_feature"], C.ASSOCIATION["local_feature"]).lower()
        gdf = on_units(s, d, ["label"], {"label": "no data"})
        n = gdf["label"].value_counts()
        names = {"HH": f"High crime, many {feat} nearby ({n.get('HH', 0):,})",
                 "HL": f"High crime, few {feat} nearby ({n.get('HL', 0):,})",
                 "LH": f"Low crime, many {feat} nearby ({n.get('LH', 0):,})",
                 "LL": f"Low crime, few {feat} nearby ({n.get('LL', 0):,})",
                 "ns": f"Not significant ({n.get('ns', 0):,})"}
        fig, ax = lisa_map(SimpleNamespace(gdf=gdf, value_col="crime_count"), basemap=basemap, mask_ns=False,
                           label_names=names, style=replace(STYLE, figsize=(9.5, 8), legend_loc="lower right"),
                           title=f"Local bivariate Moran's I: {gname(g)} count ({PERIOD}) vs spatial lag "
                                 f"of {feat},\n{sname(s)}, queen weights, 499 permutations, FDR 0.05")
        ax.get_legend().set_title("Crime in the tract × feature in its neighbours")
        fig.tight_layout()
        sink.save(fig, f"bivariate_local_{g}", f"Local bivariate Moran category: {gname(g)} count in each tract "
                                               f"vs {feat} in its queen neighbours (FDR 0.05).")


# =========================================================================== #
#  main
# =========================================================================== #
def run_group(core: Path, root: Path, g: str, basemap) -> None:
    sink = Sink(root, g)
    t0 = time.perf_counter()
    print(f"== {g}")
    fig_stl(core, sink, g)
    if g not in C.TEMPORAL_ONLY_GROUPS:
        pts = pd.read_csv(core / "points_summary.csv") if (core / "points_summary.csv").exists() \
            else pd.DataFrame(columns=["group", "variant"])
        fig_kde(core, sink, g, pts)
        fig_ripley(core, sink, g, pts)
        static = _static(core, g)
        fig_gi(sink, g, static, basemap)
        fig_lisa(sink, g, static, basemap)
        del static
        fig_ehsa(sink, g, _ehsa(core, g), basemap)
        fig_tsc(core, sink, g, basemap)
        fig_maup(core, sink, g)
        fig_knox(core, sink, g)
        fig_association(core, sink, g, basemap)
    sink.close()
    plt.close("all")
    print(f"== {g}: {len(sink.captions)} figures in {time.perf_counter() - t0:.1f} s")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--groups", nargs="+", help="crime groups (default: core_config GROUPS + temporal-only)")
    ap.add_argument("--core", type=Path, default=OUTPUTS_DIR / "core", help="stage-04 outputs (default outputs/core)")
    ap.add_argument("--out", type=Path, default=OUTPUTS_DIR / "figures", help="figure root (default outputs/figures)")
    ap.add_argument("--basemap", action="store_true", help="Esri light-grey tiles under the maps (needs network)")
    return ap.parse_args(argv)


def main(argv=None) -> None:
    a = parse_args(argv)
    if not a.core.exists():
        sys.exit(f"{a.core} missing: run `make analyse` first")
    groups = a.groups or [*C.GROUPS, *C.TEMPORAL_ONLY_GROUPS]
    basemap = "gray" if a.basemap else None
    t0 = time.perf_counter()
    for g in groups:
        run_group(a.core, a.out, g, basemap)
    idx = write_index(a.out)
    print(f"make_figures: {len(groups)} groups in {time.perf_counter() - t0:.1f} s; index {idx}")


if __name__ == "__main__":
    main()
