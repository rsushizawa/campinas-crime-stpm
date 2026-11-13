"""Publication rendering extracted from the working notebook 11.

Only presentation of persisted analysis outputs; no estimators or database access.
The nested functions share one explicit RenderContext, never a notebook namespace.
"""
from dataclasses import dataclass, field
from pathlib import Path

import contextily as cx
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import MaxNLocator

from . import mapstyle as ms


@dataclass
class RenderContext:
    """Input CSV root, destination, tract geometry and rendering options."""

    input_dir: Path
    output_dir: Path
    tracts: object
    basemap: bool = field(default=False, kw_only=True)
    sources: set[Path] = field(default_factory=set, init=False)
    assets: list[Path] = field(default_factory=list, init=False)

    def __post_init__(self):
        self.input_dir = Path(self.input_dir)
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tracts = self.tracts.rename(columns={"census_tract_id": "unit_id"}).copy()
        if self.tracts.crs is None:
            raise ValueError("Tracts must have a CRS")
        self.tracts = self.tracts.to_crs(31983)
        if self.tracts.unit_id.astype(str).duplicated().any():
            raise ValueError("Tract identifiers must be unique")

    def source(self, notebook, name):
        path = self.input_dir / notebook / name
        self.sources.add(path.resolve())
        return path

    def save(self, fig, path):
        path = Path(path)
        if self.basemap and any(getattr(ax, "_crime_basemap", False) for ax in fig.axes):
            if not any(text.get_gid() == "crime-basemap-attribution" for text in fig.texts):
                text = fig.text(0.99, -0.02,
                                "Basemap tiles: Esri World Light Gray Canvas (Esri, DeLorme, NAVTEQ).",
                                ha="right", va="top", fontsize=5.5, color="0.35")
                text.set_gid("crime-basemap-attribution")
        metadata = {"CreationDate": None, "ModDate": None} if path.suffix == ".pdf" else None
        fig.savefig(path, bbox_inches="tight", dpi=300, metadata=metadata)
        self.assets.append(path)


def render_paper(context):
    """Render all notebook-11 figures and Tables 6–10; return written paths.

    ``context`` supplies persisted CSVs and a GeoDataFrame of census tracts.
    Basemaps default off so a render needs neither a DB nor tile network access.
    """
    existing = set(plt.get_fignums())
    try:
        with plt.rc_context():
            return _render(context)
    finally:
        for number in set(plt.get_fignums()) - existing:
            plt.close(number)


def _render(context):
    OUT, tracts = context.output_dir, context.tracts
    ms.setup()
    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.facecolor": "white", "axes.edgecolor": "#64748b", "text.color": "#172033", "axes.labelcolor": "#172033", "font.size": 9, "axes.titlesize": 8.5, "axes.labelsize": 8, "xtick.labelsize": 7,
                         "ytick.labelsize": 7, "legend.fontsize": 7, "axes.spines.top": False,
                         "axes.spines.right": False, "pdf.fonttype": 42, "savefig.dpi": 300})
    TEXTWIDTH = 7.2      # inches, two-column paper, figure* width

    GROUP_ORDER = ["all", "property", "bodily_harm", "traffic", "drug", "violent"]
    GROUP_LABEL = {"all": "All groups", "property": "Property", "bodily_harm": "Bodily harm", "traffic": "Traffic",
                   "drug": "Drug-related", "violent": "Violent", "sexual": "Sexual"}
    GROUP_COLORS = {"all": "#2a78d6", "property": "#eb6834", "bodily_harm": "#1baf7a",
                    "traffic": "#eda100", "drug": "#e87ba4", "violent": "#008300", "sexual": "#6250d6"}


    def read(nb, name, **kw):
        return pd.read_csv(context.source(nb, name), **kw)


    def save(fig, name):
        path = OUT / name
        context.save(fig, path)
        if path.suffix == ".png":
            context.save(fig, path.with_suffix(".pdf"))
        plt.close(fig)
        print("wrote", path.name)


    def fmt_int(v):
        return f"{int(v):,}"


    def write_table(name, caption, label, colspec, header_lines, body_lines, size="footnotesize"):
        """Same layout as paper/jbcs/tables/*.tex: table*, double hline rules, centering + size."""
        lines = [r"\begin{table*}[!ht]", rf"\caption{{{caption}}}", rf"\label{{{label}}}", rf"\centering\{size}",
                 rf"\begin{{tabular}}{{{colspec}}}", r"\hline\hline", *header_lines, r"\hline", *body_lines,
                 r"\hline\hline", r"\end{tabular}", r"\end{table*}"]
        (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
        context.assets.append(OUT / name)


    def side_legend(ax, groups, counts=None, title=None, fontsize=7, handleheight=1.6):
        """Single-column legend to the right of a map axis: bold group headers, colour + hatch patches,
        optional 'before -> after' counts."""
        handles, texts, bold = [], [], []
        for name, items in groups.items():
            bold.append(len(texts)); handles.append(Patch(visible=False)); texts.append(name)
            for lab, fc, h in items:
                handles.append(Patch(facecolor=fc, hatch=h, edgecolor=ms.hatch_color(fc), linewidth=0.3))
                texts.append(f"{lab}: {counts[lab]}" if counts is not None and lab in counts else lab)
        leg = ax.legend(handles, texts, loc="center left", bbox_to_anchor=(1.04, 0.5), frameon=False, fontsize=fontsize,
                        title=title, title_fontsize=fontsize, handlelength=2.6, handleheight=handleheight, alignment="left")
        for i in bold:
            leg.get_texts()[i].set_fontweight("bold")
        return leg


    ATTRIB = "Basemap tiles: Esri World Light Gray Canvas (Esri, DeLorme, NAVTEQ)."


    def decorate(ax, crs, overlay=None, segments=4, nticks=4, basemap=True):
        """ms.decorate with the tile attribution moved to the figure (one line per figure, see ATTRIB),
        a graticule pruned at the corners (no overlapping lat / lon labels) and a configurable scale bar."""
        ax.set_aspect("equal")
        if basemap and context.basemap:
            try:
                cx.add_basemap(ax, crs=crs, source=cx.providers.Esri.WorldGrayCanvas, attribution=False, zorder=0)
                ax._crime_basemap = True
            except Exception as exc:  # noqa: BLE001 - offline
                raise RuntimeError("Requested publication basemap could not be loaded") from exc
        if overlay is not None:
            ms.add_overlay(ax, overlay)
        ms.graticule(ax, crs, nticks=nticks, fontsize=5.5)
        ax.xaxis.set_major_locator(MaxNLocator(nticks, prune="both"))
        ax.yaxis.set_major_locator(MaxNLocator(nticks, prune="both"))
        ms.add_scalebar(ax, segments=segments, fraction=0.3 if segments == 2 else 0.35, fontsize=5.5, margin=0.06)
        ms.add_north_arrow(ax, xy=(0.94, 0.9), fontsize=7)


    def attribution(fig, y=0.0):
        if context.basemap:
            fig.text(0.99, y, ATTRIB, ha="right", va="top", fontsize=5.5, color="0.35")


    def draw_categories(ax, labels, style):
        ms.plot_categories(ax, tracts, labels, style, hatch_repeat=2, linewidth=0.05, edgecolor="white")
        decorate(ax, tracts.crs, segments=2, nticks=3)


    def panel_label(ax, letter, offset=-18):
        """'(a)' centred under the panel, as in the paper's data-overview figures."""
        ax.annotate(f"({letter})", xy=(0.5, 0), xycoords="axes fraction", xytext=(0, offset),
                    textcoords="offset points", ha="center", va="top", fontsize=8.5)


    def tex_num(v, f="{:.3f}"):
        """Number for LaTeX text mode: a true minus sign instead of a hyphen."""
        t = f.format(v)
        return "$-$" + t[1:] if t.startswith("-") else t


    def tex_int(v):
        return f"{int(v):,}".replace(",", "{,}")

    comp = read("02_stl", "stl_components.csv", header=[0, 1], index_col=0)
    comp.index = pd.to_datetime(comp.index)
    st = read("02_stl", "stl_strength.csv").set_index(["series", "group"])
    STL_ROWS = [("observed", "Observed"), ("trend", "Trend $T_t$"), ("seasonal", "Seasonal $S_t$"),
                ("resid", "Remainder $R_t$")]


    def stl_four(group, path, width=TEXTWIDTH * 0.62):
        """Observed, trend, seasonal and remainder of the monthly series of one group (every bulletin
        dated in the month); open circles: months with robust weight < 0.5. No title: the caption or
        the file name says which group."""
        key = f"all_bulletins|{group}"
        low_w = comp[(key, "robust_weight")] < 0.5
        color = GROUP_COLORS[group]
        fig, axes = plt.subplots(4, 1, figsize=(width, 4.6), sharex=True)
        for ax, (c, lab) in zip(axes, STL_ROWS):
            v = comp[(key, c)]
            if c == "resid":
                ax.vlines(v.index, 0, v, color=color, lw=1.4)
                ax.scatter(v.index[low_w], v[low_w], s=14, facecolor="white", edgecolor="black", zorder=3,
                           label="month with robust weight < 0.5")
                ax.legend(frameon=False, fontsize=6.5, loc="lower left")
            else:
                ax.plot(v.index, v, color=color, lw=1.3)
            if c in ("seasonal", "resid"):
                ax.axhline(0, color="0.4", lw=0.6)
            ax.set_ylabel(lab + "\nbulletins per month", fontsize=7)
            ax.grid(alpha=0.25)
        axes[-1].xaxis.set_major_locator(mdates.YearLocator()); axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        axes[-1].set_xlabel("Month of occurrence")
        fig.tight_layout(h_pad=0.4)
        context.save(fig, path); plt.close(fig)
        print("wrote", path.relative_to(OUT))


    stl_four("all", OUT / "fig_stl.pdf")
    # one image per crime group, for the authors (not used in the paper)
    PER_GROUP = OUT / "stl_by_group"
    PER_GROUP.mkdir(exist_ok=True)
    for g in ["all", "property", "bodily_harm", "traffic", "drug", "violent", "sexual"]:
        stl_four(g, PER_GROUP / f"stl_{g}.png", width=TEXTWIDTH * 0.8)


    # Trend, seasonal and remainder by crime group, split in two figures of three groups each so the lines stay
    # readable. Strengths F_T / F_S are in Table tab_stl.
    def stl_groups(groups, name):
        fig, axes = plt.subplots(3, len(groups), figsize=(TEXTWIDTH, 5.2), sharex=True)
        for j, k in enumerate(groups):
            kk = f"all_bulletins|{k}"
            a, b, r = axes[:, j]
            a.plot(comp.index, comp[(kk, "observed")], color="0.7", lw=0.9)
            a.plot(comp.index, comp[(kk, "trend")], color=GROUP_COLORS[k], lw=2.2)
            a.set_title(GROUP_LABEL[k], fontsize=8)
            a.set_ylim(0, comp[(kk, "observed")].max() * 1.1)
            b.plot(comp.index, comp[(kk, "seasonal")], color=GROUP_COLORS[k], lw=1.1)
            r.vlines(comp.index, 0, comp[(kk, "resid")], color=GROUP_COLORS[k], lw=1.3)
            for ax in (b, r):
                ax.axhline(0, color="0.4", lw=0.6)
            for ax in (a, b, r):
                ax.grid(alpha=0.25); ax.tick_params(labelsize=6.5)
                ax.xaxis.set_major_locator(mdates.YearLocator()); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        axes[0, 0].set_ylabel("Bulletins per month", fontsize=7)
        axes[1, 0].set_ylabel("Seasonal $S_t$,\nbulletins per month", fontsize=7)
        axes[2, 0].set_ylabel("Remainder $R_t$,\nbulletins per month", fontsize=7)
        handles = [Line2D([], [], color="0.7", lw=1.0), Line2D([], [], color="0.15", lw=2.6),
                   Line2D([], [], color="0.15", lw=1.1), Line2D([], [], color="0.15", lw=1.3, marker="|", ls="")]
        fig.legend(handles, ["Observed monthly bulletins (top row)", "Trend $T_t$ (top row)",
                             "Seasonal component $S_t$ (middle row)", "Remainder $R_t$ (bottom row)"],
                   loc="lower center", ncol=2, frameon=False, fontsize=7, bbox_to_anchor=(0.5, -0.06))
        fig.tight_layout(w_pad=0.8, rect=(0, 0.05, 1, 1))
        save(fig, name)


    stl_groups(["property", "bodily_harm", "traffic"], "fig_stl_groups_a.pdf")
    stl_groups(["drug", "violent", "sexual"], "fig_stl_groups_b.pdf")


    MON = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    mk = read("02_stl", "mann_kendall_sen.csv").query("series == 'all_bulletins'").set_index("group")
    body = []
    for k in ["all", "property", "bodily_harm", "traffic", "drug", "violent", "sexual"]:
        a = st.loc[("all_bulletins", k)]
        it = st.loc[("in_tract", k)] if ("in_tract", k) in st.index else None
        m = mk.loc[k]
        pm = "$<0.001$" if m.hamed_rao_p < 0.001 else f"{m.hamed_rao_p:.3f}"
        body.append(f"{GROUP_LABEL[k]} & {a.mean_per_month:,.1f} & {a.trend_strength_FT:.2f} & {a.seasonal_strength_FS:.2f} & "
                    f"{a.seasonal_amplitude:,.0f} & {MON[int(a.seasonal_peak_month) - 1]} / {MON[int(a.seasonal_trough_month) - 1]} & "
                    f"{tex_num(a['trend_change_%'], '{:+.1f}')} & {tex_num(m.sen_slope_per_year, '{:+.1f}')} & {pm} & "
                    + (f"{it.trend_strength_FT:.2f} & {it.seasonal_strength_FS:.2f}" if it is not None else "-- & --") + r" \\")
    write_table(
        "tab_stl.tex",
        r"Temporal components of the monthly bulletin series by crime group, 2022--2025. Trend and seasonal strengths, "
        r"seasonal amplitude and peak / trough months, change of the trend, Sen's slope (bulletins per year) and "
        r"Hamed--Rao autocorrelation-adjusted Mann--Kendall $p$. Main columns: every bulletin dated in the month; last two: bulletins geocoded inside a tract. "
        f"The mapped all-group series averaged {st.loc[('in_tract', 'all'), 'mean_per_month']:,.1f} reports per month. "
        r"Source: SSP-SP; Section~\ref{sec:stl}.",
        "tab:stl", r"@{}lrrrrcrrrrr@{}",
        [r" & \multicolumn{8}{c}{All bulletins} & \multicolumn{2}{c}{In a tract} \\",
         r"Crime group & Mean/month & $F_T$ & $F_S$ & Ampl. & Peak / trough & $\Delta T$ (\%) & Sen/yr & MK $p$ & $F_T$ & $F_S$ \\"],
        body)

    gm = read("04_global_moran", "global_moran.csv")
    sc = read("04_global_moran", "moran_scatter_all_queen.csv")
    d = sc[sc.support == "tract"]; r = gm.query("support == 'tract' and group == 'all' and weights == 'queen'").iloc[0]
    hi = (d.z > 0) & (d.lag_z > 0); lo = (d.z < 0) & (d.lag_z < 0)
    fig, ax = plt.subplots(figsize=(TEXTWIDTH * 0.55, 3.3))
    for m, c, lab in ((hi, "#d7191c", "High among high (HH quadrant)"), (lo, "#2c7bb6", "Low among low (LL quadrant)"),
                      (~(hi | lo), "0.55", "Mixed (HL or LH quadrant)")):
        ax.scatter(d.z[m], d.lag_z[m], s=5, c=c, alpha=0.55, edgecolor="none", label=lab)
    xs = np.linspace(d.z.min(), d.z.max(), 10)
    ax.plot(xs, r.I * xs, color="black", lw=1.1, label="Fitted line; slope = Moran's $I$")
    ax.axhline(0, color="0.6", lw=0.6); ax.axvline(0, color="0.6", lw=0.6)
    ax.set_xlabel("Bulletins 2022–2025 in the tract (z-score)")
    ax.set_ylabel("Mean z-score of its queen neighbours\n(spatial lag)")
    ax.legend(frameon=False, fontsize=6.5, loc="upper left", markerscale=2.5)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    save(fig, "fig_moran_scatter.pdf")
    print(f"I = {r.I:.3f}, z = {r.z_sim:.1f}, p = {r.p_sim:.3f}")


    W_ORDER = ["queen", "rook", "knn5"]
    W_LAB = {"queen": "Queen", "rook": "Rook", "knn5": "5-NN"}


    def cell(r):
        star = "" if r.p_sim <= 0.001 else ("$^{*}$" if r.p_sim <= 0.05 else "$^{\\dagger}$")
        return f"{tex_num(r.I)} ({r.z_sim:.1f}){star}"


    body = []
    for k in GROUP_ORDER:
        row = [GROUP_LABEL[k], fmt_int(gm.query("support == 'tract' and group == @k and weights == 'queen'").events.iloc[0])]
        for w in W_ORDER:
            row.append(cell(gm.query("support == 'tract' and group == @k and weights == @w").iloc[0]))
        body.append(" & ".join(row) + r" \\")
    write_table(
        "tab_global_moran.tex",
        r"Global Moran's $I$ of the 2022--2025 bulletin count per tract, by crime group and neighbourhood definition. "
        r"Each cell: $I$ ($z$-score); unmarked: pseudo $p = 0.001$; $^{*}$: $0.001 < p \le 0.05$. "
        r"Source: SSP-SP, IBGE 2022; Section~\ref{sec:local}.",
        "tab:globalmoran", r"@{}lrrrr@{}",
        ["Crime group & Bulletins & " + " & ".join(W_LAB[w] for w in W_ORDER) + r" \\"],
        body)

    GI_STYLE = {"hot spot 99%": ("#b2182b", ""), "hot spot 95%": ("#ef6548", "//"), "hot spot 90%": ("#fdbb84", ".."),
                "cold spot 99%": ("#2166ac", ""), "cold spot 95%": ("#67a9cf", "//"), "cold spot 90%": ("#d1e5f0", ".."),
                "ns": ("#d9d9d9", "")}
    GI_GROUPS = {"Hot spots": ["hot spot 99%", "hot spot 95%", "hot spot 90%"],
                 "Cold spots": ["cold spot 99%", "cold spot 95%", "cold spot 90%"], "Other": ["ns"]}
    LI_STYLE = {"HH": ("#d7191c", ""), "LL": ("#2c7bb6", ""), "HL": ("#fdae61", "//"), "LH": ("#abd9e9", "\\\\"),
                "ns": ("#d9d9d9", "")}
    LI_GROUPS = {"Clusters": ["HH", "LL"], "Outliers": ["HL", "LH"], "Other": ["ns"]}
    NAMES = {"HH": "HH cluster (high among high)", "LL": "LL cluster (low among low)", "HL": "HL outlier (high among low)",
             "LH": "LH outlier (low among high)", "ns": "not significant"}
    for c in GI_STYLE:
        NAMES.setdefault(c, c)
    lab05 = read("05_local_gi_lisa", "labels_tract_queen.csv", dtype={"unit_id": str})
    ids = tracts["unit_id"].astype(str)


    def labels_for(group, col):
        lab = ids.map(lab05.query("group == @group").set_index("unit_id")[col])
        if lab.isna().any():
            raise ValueError(f"Missing local labels for {group}: {col}")
        return lab.to_numpy()


    MAP_GROUPS = ["all", "property", "bodily_harm", "traffic", "drug", "violent"]
    LEGEND_NOUN = {"all": "All geocoded bulletins", "property": "Property crimes", "bodily_harm": "Bodily harm",
                   "traffic": "Traffic crimes", "drug": "Drug-related crimes", "violent": "Violent crimes"}


    def pair_figure(get_labels, style, legend_groups, group, stat, fname, handleheight=1.6):
        """One crime group: (a) before and (b) after the FDR correction, legend on the right with every
        category and its tract count before -> after; same layout as the local bivariate figure."""
        before, after = get_labels(group, False), get_labels(group, True)
        fig, axes = plt.subplots(1, 2, figsize=(TEXTWIDTH, 3.8))
        fig.subplots_adjust(left=0.06, right=0.99, top=0.98, bottom=0.1, wspace=0.12)
        for ax, lab, letter in zip(axes, (before, after), "ab"):
            draw_categories(ax, lab, style)
            ax.set_title("Unadjusted p" if letter == "a" else "BH-adjusted q", loc="left", fontweight="bold")
            panel_label(ax, letter, offset=-14)
        vb, va = pd.Series(before).value_counts(), pd.Series(after).value_counts()
        side_legend(axes[1], {h: [(NAMES.get(c, c), *style[c]) for c in cs] for h, cs in legend_groups.items()},
                    counts={NAMES.get(c, c): f"{vb.get(c, 0):,} → {va.get(c, 0):,}"
                            for cs in legend_groups.values() for c in cs},
                    title=f"{LEGEND_NOUN[group]}, {stat}:\ntracts before → after FDR"
                    + ("\nEHSA: correction of bin tests only" if stat == "emerging hot spots" else ""), fontsize=8,
                    handleheight=handleheight)
        save(fig, fname)


    for g in MAP_GROUPS:
        pair_figure(lambda g, fdr: labels_for(g, "gi_conf_fdr" if fdr else "gi_conf_raw"), GI_STYLE, GI_GROUPS, g,
                    "$G_i^*$", f"fig_gistar_{g}.png")


    for g in MAP_GROUPS:
        pair_figure(lambda g, fdr: labels_for(g, "lisa_fdr" if fdr else "lisa_raw"), LI_STYLE, LI_GROUPS, g,
                    "local Moran's $I$", f"fig_lisa_{g}.png")
    lc = read("05_local_gi_lisa", "local_counts_all_weights.csv").query("weights == 'queen' and support == 'tract'")
    lc[["group", "lisa_min_p", "lisa_n_at_floor", "lisa_floor_units_needed_for_bh"]]


    def pair(r, a):
        return f"{int(r[a + '_raw']):,} / {int(r[a + '_fdr']):,}"


    body = []
    for k in GROUP_ORDER:
        r = lc.query("group == @k").iloc[0]
        body.append(f"{GROUP_LABEL[k]} & {fmt_int(r.events)} & {pair(r, 'gi_hot')} & {pair(r, 'gi_cold')} & "
                    f"{pair(r, 'lisa_HH')} & {pair(r, 'lisa_LL')} & {pair(r, 'lisa_HL')} & {pair(r, 'lisa_LH')} \\\\")
    write_table(
        "tab_local_fdr.tex",
        r"Tracts with a significant local statistic before / after the false discovery rate correction, by crime group. "
        r"$G_i^*$: hot and cold spots; local Moran's $I$: HH / LL clusters and HL / LH outliers. Each cell: unadjusted "
        r"$p \le 0.05$ / BH $q \le 0.05$. Source: SSP-SP, IBGE 2022; Sections~\ref{sec:local} and~\ref{sec:fdr}.",
        "tab:localfdr", r"@{}lrrrrrrr@{}",
        [r" & & \multicolumn{2}{c}{$G_i^*$} & \multicolumn{4}{c}{Local Moran's $I$} \\",
         r"Crime group & Bulletins & Hot & Cold & HH & LL & HL & LH \\"],
        body)

    PATTERNS = ("new", "consecutive", "intensifying", "persistent", "diminishing", "sporadic", "oscillating", "historical")
    HATCH = dict(zip(PATTERNS, ["", "//", "xx", "..", "\\\\", "oo", "++", "--"]))
    REDS = dict(zip(PATTERNS, ["#fc9272", "#ef3b2c", "#67000d", "#a50f15", "#fcbba1", "#fb6a4a", "#cb181d", "#fee0d2"]))
    BLUES = dict(zip(PATTERNS, ["#9ecae1", "#4292c6", "#08306b", "#08519c", "#c6dbef", "#6baed6", "#2171b5", "#deebf7"]))
    EH_STYLE = {f"{p} hot spot": (REDS[p], HATCH[p]) for p in PATTERNS}
    EH_STYLE |= {f"{p} cold spot": (BLUES[p], HATCH[p]) for p in PATTERNS}
    EH_STYLE["no pattern detected"] = ("#d9d9d9", "")
    EH_STYLE["trend unavailable"] = ("#b8bec8", "xx")
    EH_GROUPS = {"Hot spots": [c for c in EH_STYLE if "hot" in c], "Cold spots": [c for c in EH_STYLE if "cold" in c],
                 "Other": ["no pattern detected", "trend unavailable"]}
    eh = {g: read("06_ehsa", f"ehsa_tract_{g}_quarterly.csv", dtype={"unit_id": str}).set_index("unit_id")
          for g in MAP_GROUPS}


    def ehsa_labels(g, fdr):
        d = eh[g]["category_fdr" if fdr else "category"].reindex(ids)
        if d.isna().any():
            raise ValueError(f"Missing EHSA labels for {g}")
        return d.to_numpy()


    for g in MAP_GROUPS:
        pair_figure(ehsa_labels, EH_STYLE, EH_GROUPS, g, "emerging hot spots", f"fig_ehsa_{g}.png", handleheight=1.1)


    ba = read("06_ehsa", "before_after_fdr_counts.csv", header=[0, 1, 2], index_col=0)
    CATS = [f"{p} {side} spot" for side in ("hot", "cold") for p in PATTERNS] + ["no pattern detected", "trend unavailable"]
    ba = ba.reindex(CATS).fillna(0).astype(int)      # every Esri category, also those no tract has


    def cell(g, cat):
        return f"{ba.loc[cat, (g, 'tract', 'before FDR')]:,} / {ba.loc[cat, (g, 'tract', 'after FDR')]:,}"


    body = [f"{cat} & " + " & ".join(cell(g, cat) for g in MAP_GROUPS) + r" \\" for cat in CATS]
    pat = {g: tuple(int(ba.loc[~ba.index.isin(["no pattern detected", "trend unavailable"]), (g, "tract", w)].sum()) for w in ("before FDR", "after FDR"))
           for g in MAP_GROUPS}
    body.append(r"\hline")
    body.append("Tracts with a pattern & " + " & ".join(f"{pat[g][0]:,} / {pat[g][1]:,}" for g in MAP_GROUPS) + r" \\")
    write_table(
        "tab_ehsa_fdr.tex",
        r"Tracts in each emerging hot spot category before / after the false discovery rate correction, by crime group, "
        r"quarterly cubes 2022Q1--2025Q4. Each cell: bin $p < 0.05$ / bin $q < 0.05$. "
        r"Source: SSP-SP, IBGE 2022; Sections~\ref{sec:ehsa} and~\ref{sec:fdr}.",
        "tab:ehsafdr", r"@{}l" + "r" * len(MAP_GROUPS) + "@{}",
        ["Category & " + " & ".join(GROUP_LABEL[g] for g in MAP_GROUPS) + r" \\"],
        body, size="scriptsize")


    spr = read("09_association", "spearman.csv").query("group == 'all' and period == '2022-2025'")
    bv = read("09_association", "moran_bv.csv").query("group == 'all'")
    FEATS = ["n_commercial", "n_education", "n_health", "n_religious", "population", "income_head_mean", "literacy_rate"]
    FLAB = {"n_commercial": "Other-purpose establishments", "n_education": "Education addresses",
            "n_health": "Health addresses", "n_religious": "Religious addresses", "population": "Resident population",
            "income_head_mean": "Mean income of household heads", "literacy_rate": "Literacy rate (15+)"}
    COLS = [("tract", "count"), ("tract", "per_km2")]
    CLAB = ["Counts", "Per km²"]


    def matrix(df, val, pcol, extra=None):
        M = np.full((len(FEATS), len(COLS)), np.nan); P = np.full_like(M, np.nan)
        for i, f in enumerate(FEATS):
            for j, (s, scale) in enumerate(COLS):
                q = df.query("support == @s and feature == @f and scale == @scale" + (extra or ""))
                if len(q):
                    M[i, j], P[i, j] = q[val].iloc[0], q[pcol].iloc[0]
        return M, P


    R, Rp = matrix(spr, "rho", "p")
    B, Bp = matrix(bv, "I_bv", "p_sim", " and order == 'crime x lag(feature)'")
    fig, axes = plt.subplots(1, 2, figsize=(TEXTWIDTH * 0.8, 3.3), gridspec_kw={"wspace": 0.08})
    for ax, M, P, letter in ((axes[0], R, Rp, "a"), (axes[1], B, Bp, "b")):
        im = ax.imshow(np.ma.masked_invalid(M), cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
        for i in range(M.shape[0]):
            for j in range(M.shape[1]):
                v = M[i, j]
                if np.isnan(v):
                    ax.text(j, i, "n/a", ha="center", va="center", fontsize=6.5, color="0.55")
                else:
                    ns = False  # descriptive coefficients; inference is reported separately
                    ax.text(j, i, f"{v:.2f}" + ("\nns" if ns else ""), ha="center", va="center", fontsize=6.5,
                            color="white" if abs(v) > 0.55 else "black", style="italic" if ns else "normal")
        ax.set_xticks(range(len(COLS)), CLAB, fontsize=6.5)
        ax.set_yticks(range(len(FEATS)), [FLAB[f] for f in FEATS] if ax is axes[0] else [])
        ax.set_title("Spearman ρ" if letter == "a" else "Bivariate Moran I", loc="left", fontweight="bold")
        panel_label(ax, letter, offset=-24)
        ax.tick_params(length=0); [sp_.set_visible(False) for sp_ in ax.spines.values()]
    cb = fig.colorbar(im, ax=axes, fraction=0.03, pad=0.02)
    cb.set_label("Coefficient (−1 to 1)", fontsize=7); cb.ax.tick_params(labelsize=6)
    save(fig, "fig_association.pdf")

    def fmt_p(v, p):
        return "--" if np.isnan(v) else (tex_num(v) + ("$^{\\dagger}$" if p > 0.05 else ""))


    B2, B2p = matrix(bv, "I_bv", "p_sim", " and order == 'feature x lag(crime)'")
    FLAB_TEX = {k: v.replace("%", r"\%") for k, v in FLAB.items()}
    body = []
    for blk, (M, P) in (("Spearman's $\\rho$", (R, Rp)),
                        ("Bivariate Moran's $I$, bulletins $\\times$ lag(feature)", (B, Bp)),
                        ("Bivariate Moran's $I$, feature $\\times$ lag(bulletins)", (B2, B2p))):
        body.append(rf"\multicolumn{{3}}{{@{{}}l}}{{\emph{{{blk}}}}} \\")
        for i, f in enumerate(FEATS):
            body.append(f"\\quad {FLAB_TEX[f]} & " + " & ".join(fmt_p(M[i, j], P[i, j]) for j in range(2)) + r" \\")
    write_table(
        "tab_association.tex",
        r"Association between the 2022--2025 bulletin count of all crime groups and urban features per tract, as counts and "
        r"per km$^2$: Spearman's $\rho$ and bivariate Moran's $I$ in both orders. $^{\dagger}$: $p > 0.05$; --: not defined. "
        r"Source: SSP-SP, IBGE 2022 (CNEFE, Census); Section~\ref{sec:assoc}.",
        "tab:association", r"@{}lrr@{}",
        [r"Feature & counts & per km$^2$ \\"],
        body)
    n_inc = int(spr.query("feature == 'income_head_mean'").n.iloc[0]); print("n income:", n_inc)
    print("Complete income pairs:", n_inc)

    # local bivariate Moran, crime x commerce in the neighbours, tracts, before / after FDR, count and per km^2
    BV_STYLE = {"HH": ("#d7191c", ""), "LL": ("#2c7bb6", ""), "HL": ("#fdae61", "//"), "LH": ("#abd9e9", "\\\\"),
                "ns": ("#d9d9d9", "")}
    BV_NAME = {"HH": "HH: high bulletins,\nhigh commerce around", "LL": "LL: low bulletins,\nlow commerce around",
               "HL": "HL: high bulletins,\nlow commerce around", "LH": "LH: low bulletins,\nhigh commerce around",
               "ns": "not significant"}
    fig, axes = plt.subplots(2, 2, figsize=(TEXTWIDTH * 0.85, 5.8))
    fig.subplots_adjust(left=0.06, right=0.99, top=0.98, bottom=0.05, wspace=0.12, hspace=0.1)
    for i, scale in enumerate(("count", "per_km2")):
        d = read("09_association", f"local_bv_crime_commerce_tract_{scale}.csv", dtype={"unit_id": str}).set_index("unit_id")
        d = d.reindex(tracts["unit_id"].astype(str))
        if d[["raw", "fdr"]].isna().any().any():
            raise ValueError(f"Missing local bivariate labels for {scale}")
        sl = "counts" if scale == "count" else "per km²"
        for j, (col, when) in enumerate((("raw", "before FDR: pseudo p ≤ 0.05"), ("fdr", "after BH-FDR: q ≤ 0.05"))):
            draw_categories(axes[i, j], d[col].to_numpy(), BV_STYLE)
            panel_label(axes[i, j], "abcd"[2 * i + j], offset=-14)
        vr, vf = d["raw"].value_counts(), d["fdr"].value_counts()
        side_legend(axes[i, 1], {"Clusters": [(BV_NAME[c], *BV_STYLE[c]) for c in ("HH", "LL")],
                                 "Outliers": [(BV_NAME[c], *BV_STYLE[c]) for c in ("HL", "LH")],
                                 "Other": [(BV_NAME["ns"], *BV_STYLE["ns"])]},
                    counts={BV_NAME[c]: f"{vr.get(c, 0):,} → {vf.get(c, 0):,}" for c in BV_NAME},
                    title=f"Bulletins vs other-purpose\naddresses, {sl}:\ntracts before → after FDR", fontsize=8)
    save(fig, "fig_bivariate_local.png")
    read("09_association", "local_bv_counts.csv")
    return tuple(context.assets)
