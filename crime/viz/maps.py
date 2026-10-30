"""Static (matplotlib) and interactive (plotly) unit-level maps.

Consumes: ``GiStarResult`` (hotspot_map), ``LisaResult`` (lisa_map),
``EhsaResult`` (ehsa_map, persistence_map), a cube
(``CubeResult``/``SpaceTimeCube``: history_map, trend_map, grid_heatmap), or
any result with ``.gdf`` / a bare GeoDataFrame (choropleth_map,
bivariate_choropleth, interactive_map). ``dataset`` supplies the boundary
overlay and id/value column names. Statistics come from :mod:`crime.esri`.

    from crime import hotspot_map, lisa_map, ehsa_map, choropleth_map, interactive_map

Space-time summary maps (one map instead of 16 EHSA categories):
  ``history_map(cube)``       — total crime over the whole period
  ``persistence_map(ehsa)``   — red ramp = share of slices hot, blue = cold
  ``trend_map(cube, on=…)``   — per-unit Theil-Sen slope (count or Gi* z)
  ``grid_heatmap(cube)``      — rasterise a 200 m grid result (legible where polygons are not)

Static maps return ``(fig, ax)`` (choropleth/history add bin edges as a third value) and draw the article map frame; interactive
maps return a plotly ``Figure``.
"""
from typing import TYPE_CHECKING

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import to_hex
from matplotlib.ticker import PercentFormatter

from crime.core.config import CRS_METRIC
from crime.viz.basemap import add_basemap
from crime.viz.classify import bin_index, classify
from crime.viz.frame import boundary_overlay, finish, map_axes, map_frame
from crime.viz.style import PlotStyle

if TYPE_CHECKING:
    import geopandas as gpd

# one basemap for every static map — Esri light-grey canvas (falls back to OSM)
DEFAULT_BASEMAP = "gray"

_HOTSPOT_LABELS = {"hotspot": "Hot spot", "coldspot": "Cold spot", "ns": "Not significant"}
_LISA_LABELS = {"HH": "High-High", "HL": "High-Low", "LH": "Low-High",
                "LL": "Low-Low", "ns": "Not significant"}
_LISA_ORDER = ["HH", "HL", "LH", "LL", "ns"]
_NS_VALUES = {"ns", "no pattern"}                 # drawn recessive when mask_ns=True
_BIVAR_GRID = np.array([["#e8e8e8", "#ace4e4", "#5ac8c8"],
                        ["#dfb0d6", "#a5add3", "#5698b9"],
                        ["#be64ac", "#8c62aa", "#3b4994"]])


def _overlay(ax, dataset, overlay, style):
    if overlay and dataset is not None and dataset.overlay is not None:
        boundary_overlay(ax, dataset.overlay, style)


def _basemap(ax, gdf, basemap):
    if basemap:
        add_basemap(ax, gdf, source="gray" if basemap is True else basemap)


# --------------------------------------------------------------------------- #
#  choropleth
# --------------------------------------------------------------------------- #
def choropleth_map(result, dataset=None, *, column: str | None = None, title: str = "",
                   scheme: str = "quantile", k: int = 5, edges: np.ndarray | None = None,
                   overlay: bool = False,
                   basemap=DEFAULT_BASEMAP, style: PlotStyle = PlotStyle()):
    """``scheme`` classes a numeric column into ``k`` bins —
    ``"quantile"`` (default), ``"equal_interval"``, or ``"natural"`` (Jenks-like);
    ``scheme=None`` keeps the continuous ramp. Categorical columns ignore it.
    ``edges`` reuses previously computed bin edges, e.g. for a companion histogram.
    Returns ``(fig, ax, edges)``; edges is None for unclassified maps."""
    gdf = getattr(result, "gdf", result).copy()
    column = column or getattr(result, "value_col", "crime_count")
    fig, ax = map_axes(style, title or column)
    categorical = gdf[column].dtype == object

    if not categorical and scheme:
        if edges is None:
            edges, labels = classify(gdf[column], scheme=scheme, k=k)
        else:
            edges = np.asarray(edges)
            def fmt(x):
                return f"{x:,.0f}" if abs(x) >= 100 else f"{x:.3g}"
            labels = [f"{fmt(lo)} – {fmt(hi)}" for lo, hi in zip(edges[:-1], edges[1:])]
        gdf["_cls"] = bin_index(gdf[column], edges)
        cmap = plt.get_cmap(style.cmap, len(labels))
        gdf.plot(column="_cls", cmap=cmap, ax=ax, categorical=True,
                 alpha=0.8 if basemap else 1.0, edgecolor=style.edge_color,
                 linewidth=style.edge_width, legend=False,
                 missing_kwds={"color": "#e8e8e8", "label": "no data"})
        ax.legend(handles=[mpatches.Patch(color=cmap(i), label=labels[i]) for i in range(len(labels))],
                  loc=style.legend_loc, framealpha=0.9, title=f"{column} ({scheme})",
                  fontsize=style.font_size - 2)
    else:
        edges = None
        legend_kwds = {"loc": style.legend_loc} if categorical else {"shrink": 0.6}
        gdf.plot(column=column, cmap=style.cmap, ax=ax, legend=True, categorical=categorical,
                 alpha=0.8 if basemap else 1.0, edgecolor=style.edge_color,
                 linewidth=style.edge_width, legend_kwds=legend_kwds)
    map_frame(ax, gdf, style)
    _overlay(ax, dataset, overlay, style)
    _basemap(ax, gdf, basemap)
    return finish(fig), ax, edges


# --------------------------------------------------------------------------- #
#  categorical maps (Gi* / LISA / EHSA)
# --------------------------------------------------------------------------- #
def _category_map(gdf, values, palette, label_names, order, title, style, dataset,
                  overlay, basemap, mask_ns):
    fig, ax = map_axes(style, title)
    values = pd.Series(values, index=gdf.index)
    colors = values.map(palette).fillna(palette["ns"])
    ns = values.isin(_NS_VALUES) if mask_ns else pd.Series(False, index=gdf.index)
    base_alpha = 0.8 if basemap else 1.0
    if ns.any():
        gdf[ns].plot(color=colors[ns], ax=ax, alpha=0.25 * base_alpha,
                     edgecolor="none", linewidth=0)
    gdf[~ns].plot(color=colors[~ns], ax=ax, alpha=base_alpha,
                  edgecolor=style.edge_color, linewidth=style.edge_width)
    present = [k for k in order if k in set(values)]
    ax.legend(handles=[mpatches.Patch(color=palette[k], label=label_names[k],
                                      alpha=0.3 if k in _NS_VALUES and mask_ns else 1.0)
                       for k in present],
              loc=style.legend_loc, framealpha=0.9)
    map_frame(ax, gdf, style)
    _overlay(ax, dataset, overlay, style)
    _basemap(ax, gdf, basemap)
    return finish(fig), ax


def hotspot_map(result, dataset=None, *, title: str = "", overlay: bool = False,
                basemap=DEFAULT_BASEMAP, mask_ns: bool = True, style: PlotStyle = PlotStyle()):
    return _category_map(
        result.gdf, result.gdf["label"].values, style.hotspot_palette, _HOTSPOT_LABELS,
        list(_HOTSPOT_LABELS), title or f"Gi* — {result.value_col}", style, dataset,
        overlay, basemap, mask_ns,
    )


def lisa_map(result, dataset=None, *, title: str = "", overlay: bool = False,
             basemap=DEFAULT_BASEMAP, mask_ns: bool = True, style: PlotStyle = PlotStyle()):
    return _category_map(
        result.gdf, result.gdf["label"].values, style.lisa_palette, _LISA_LABELS, _LISA_ORDER,
        title or f"LISA — {result.value_col}", style, dataset, overlay, basemap, mask_ns,
    )


_EHSA_PATTERNS = ["new", "consecutive", "intensifying", "persistent",
                  "diminishing", "sporadic", "oscillating", "historical"]


def ehsa_map(result, dataset=None, *, title: str = "", overlay: bool = False,
             basemap=DEFAULT_BASEMAP, mask_ns: bool = False, legend: str = "hierarchical",
             hatch: bool = False, style: PlotStyle = PlotStyle()):
    """EHSA category map — hot categories on a red ramp, cold on a blue ramp.

    Every spatial unit is drawn; "no pattern" renders solid gray so the full
    study extent stays visible (``mask_ns=True`` fades it instead).
    ``legend``: ``"hierarchical"`` (default — family headers with pattern rows;
    reads the ramp as darker = more entrenched), ``"family"`` (hot / cold / none
    only), ``"full"`` (flat list), or ``"none"``. ``hatch=True`` restores the
    per-pattern hatch fill (fiddly at print size and invisible on a basemap).
    """
    palette = style.ehsa_palette
    hatches = style.ehsa_hatches if hatch else {k: None for k in style.ehsa_hatches}
    gdf = result.gdf
    fig, ax = map_axes(style, title or "Emerging Hot Spot Analysis")
    cats = gdf["category"].where(gdf["category"].isin(palette), "no pattern")
    lines = gdf.geom_type.str.endswith("LineString").all()
    base_alpha = 0.8 if basemap else 1.0
    for cat, sub in gdf.groupby(cats):
        faded = mask_ns and cat == "no pattern"
        a = 0.25 * base_alpha if faded else base_alpha
        lw = style.boundary_width if (lines and "hotspot" in cat) else style.edge_width
        if lines:
            sub.plot(ax=ax, color=palette[cat], linewidth=lw * (2.5 if "hotspot" in cat else 1),
                     alpha=a)
        else:
            sub.plot(ax=ax, color=palette[cat], hatch=None if faded else hatches[cat],
                     edgecolor="none" if faded else style.boundary_color,
                     linewidth=style.edge_width, alpha=a)

    def _patch(c):
        return mpatches.Patch(facecolor=palette[c], hatch=None if lines else hatches.get(c),
                              edgecolor=style.boundary_color, linewidth=0.4, label=c)

    if legend == "family":
        fam = {"hot spot": "#d7191c", "cold spot": "#2c7bb6", "no pattern": "#d9d9d9"}
        present = [f for f, key in (("hot spot", "hotspot"), ("cold spot", "coldspot"),
                                    ("no pattern", "no pattern")) if cats.str.contains(key).any()]
        ax.legend(handles=[mpatches.Patch(facecolor=fam[f], edgecolor=style.boundary_color,
                                          linewidth=0.4, label=f) for f in present],
                  loc="upper center", bbox_to_anchor=(0.5, -0.05), ncol=3, framealpha=0.9,
                  fontsize=style.font_size - 2)
    elif legend == "hierarchical":
        handles, blank = [], mpatches.Patch(alpha=0, label="")
        for fam, key in (("Hot spot", "hotspot"), ("Cold spot", "coldspot")):
            rows = [f"{p} {key}" for p in _EHSA_PATTERNS if f"{p} {key}" in cats.values]
            if rows:
                handles.append(mpatches.Patch(alpha=0, label=fam))
                handles += [_patch(c) for c in rows]
        if (cats == "no pattern").any():
            handles += [blank, _patch("no pattern")]
        ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.01, 0.5),
                  framealpha=0.9, fontsize=style.font_size - 3, handlelength=1.4)
        finish(fig)
        fig.subplots_adjust(right=0.78)
        _overlay(ax, dataset, overlay, style)
        map_frame(ax, gdf, style)
        _basemap(ax, gdf, basemap)
        return fig, ax
    elif legend != "none":
        present = [c for c in palette if c in cats.values]
        ax.legend(handles=[_patch(c) for c in present],
                  loc="upper center", bbox_to_anchor=(0.5, -0.05), ncol=3, framealpha=0.9,
                  fontsize=style.font_size - 2)
    map_frame(ax, gdf, style)
    _overlay(ax, dataset, overlay, style)
    _basemap(ax, gdf, basemap)
    return finish(fig), ax


def bivariate_choropleth(result, dataset=None, *, x_col: str = "crime_count",
                         y_col: str = "income_mean", x_label: str | None = None,
                         y_label: str | None = None, title: str = "",
                         overlay: bool = False, basemap=False, style: PlotStyle = PlotStyle()):
    """Value-based terciles keep ties together. ``x_label``/``y_label`` name the
    legend axes (default: column names); low values are left/bottom.
    Constant columns use the low class; duplicate quantile breaks collapse.
    """
    gdf = getattr(result, "gdf", result)
    valid = gdf.dropna(subset=[x_col, y_col])

    def tercile(s):
        return pd.qcut(s, 3, labels=False, duplicates="drop").fillna(0).astype(int)

    tx, ty = tercile(valid[x_col]), tercile(valid[y_col])
    color = _BIVAR_GRID[ty.to_numpy(dtype=int), tx.to_numpy(dtype=int)]
    fig, ax = map_axes(style, title or f"{x_col} × {y_col}")
    gdf.plot(color="#ffffff", hatch="///", ax=ax, edgecolor=style.edge_color,
             linewidth=style.edge_width)
    valid.plot(color=color, ax=ax, edgecolor=style.edge_color, linewidth=style.edge_width)

    legend = ax.inset_axes([0.02, 0.02, 0.18, 0.18])
    for i in range(3):
        for j in range(3):
            legend.add_patch(mpatches.Rectangle((j, i), 1, 1, facecolor=_BIVAR_GRID[i, j]))
    legend.set_xlim(0, 3)
    legend.set_ylim(0, 3)
    legend.set_xticks([])
    legend.set_yticks([])
    legend.set_xlabel(f"{x_label or x_col} →", fontsize=style.font_size - 3)
    legend.set_ylabel(f"{y_label or y_col} →", fontsize=style.font_size - 3)
    for spine in legend.spines.values():
        spine.set_visible(False)
    map_frame(ax, gdf, style)
    _overlay(ax, dataset, overlay, style)
    _basemap(ax, gdf, basemap)
    return finish(fig), ax


# --------------------------------------------------------------------------- #
#  space-time summary maps  (one map instead of 16 categories)
# --------------------------------------------------------------------------- #
def _wide(cube):
    return getattr(cube, "wide", cube)


def history_map(cube, dataset=None, **kw):
    """Cube collapsed to its column sum — a plain choropleth of total crime over
    the whole period (the denominator every EHSA claim is compared against).
    Returns ``(fig, ax, edges)`` so a companion histogram can use identical bins."""
    g = _wide(cube)
    gdf = getattr(cube, "gdf", getattr(dataset, "gdf", None)).copy()
    gdf["_total"] = g.reindex(gdf["unit_id"]).sum(axis=1).to_numpy()
    kw.setdefault("title", "Total crime, whole period")
    return choropleth_map(gdf, dataset, column="_total", **kw)


def persistence_map(result, dataset=None, *, title: str = "", overlay: bool = False,
                    basemap=DEFAULT_BASEMAP, style: PlotStyle = PlotStyle()):
    """Single continuous choropleth of an EHSA result: red ramp = share of
    slices a unit was significantly *hot*, blue ramp = share significantly
    *cold*. Often clearer than the 16-category map."""
    gdf = result.gdf.copy()
    hot = gdf.get("pct_hot")
    cold = gdf.get("pct_cold")
    if hot is None:
        raise ValueError("need an EhsaResult with pct_hot / pct_cold columns.")
    gdf["_persist"] = hot.fillna(0) - cold.fillna(0)          # +1 always hot … -1 always cold
    fig, ax = map_axes(style, title or "Hot / cold spot persistence")
    gdf.plot(column="_persist", cmap="RdBu_r", vmin=-1, vmax=1, ax=ax,
             legend=True, alpha=0.85 if basemap else 1.0,
             edgecolor=style.edge_color, linewidth=style.edge_width,
             legend_kwds={"shrink": 0.6, "format": PercentFormatter(xmax=1, decimals=0),
                          "label": "hot-month share minus cold-month share"})
    map_frame(ax, gdf, style)
    _overlay(ax, dataset, overlay, style)
    _basemap(ax, gdf, basemap)
    return finish(fig), ax


def trend_values(cube, dataset=None, *, on: str = "count", weights: str = "queen") -> "gpd.GeoDataFrame":
    """Per-unit Theil-Sen slopes in ``_slope``, reusable across map panels
    (slopes from :func:`crime.esri.trend.theil_sen_slopes`)."""
    from crime.esri.trend import theil_sen_slopes

    wide = _wide(cube).astype(float)
    gdf = getattr(cube, "gdf", getattr(dataset, "gdf", None)).copy()
    mat = wide
    if on == "gi":
        from crime.esri.ehsa import gi_time_series
        from crime.esri.weights import spatial_weights
        w = spatial_weights(gdf, kind=weights)
        z, _, _, _ = gi_time_series(wide.reindex(gdf["unit_id"]).fillna(0), w)
        mat = pd.DataFrame(z, index=gdf["unit_id"], columns=wide.columns)
    gdf["_slope"] = theil_sen_slopes(mat).reindex(gdf["unit_id"]).to_numpy()

    return gdf


def draw_trend(ax, gdf, *, norm, style: PlotStyle = PlotStyle()):
    """Draw one trend panel with a shared Normalize; caller adds the colorbar."""
    gdf.plot(column="_slope", cmap="RdBu_r", norm=norm, ax=ax,
             edgecolor=style.edge_color, linewidth=style.edge_width)
    ax.set_axis_off()


def trend_map(cube, dataset=None, *, on: str = "count", weights: str = "queen",
              title: str = "", overlay: bool = False, basemap=DEFAULT_BASEMAP,
              style: PlotStyle = PlotStyle()):
    """Per-unit robust (Theil–Sen) slope of the time series → diverging
    choropleth. ``on="count"`` slopes the raw counts; ``on="gi"`` slopes the
    Gi\\*-z trajectory (needs ``weights``). "Where is crime rising / falling."
    """
    from matplotlib.colors import Normalize

    gdf = trend_values(cube, dataset, on=on, weights=weights)
    fig, ax = map_axes(style, title or f"Trend ({on}, Theil–Sen slope per bin)")
    vmax = float(np.nanpercentile(np.abs(gdf["_slope"]), 98) or 1e-6)
    norm = Normalize(vmin=-vmax, vmax=vmax)
    gdf.plot(column="_slope", cmap="RdBu_r", norm=norm, ax=ax, legend=True,
             alpha=0.85 if basemap else 1.0, edgecolor=style.edge_color,
             linewidth=style.edge_width,
             legend_kwds={"shrink": 0.6, "extend": "both",
                          "label": "<- falling    slope / bin    rising ->"})
    map_frame(ax, gdf, style)
    _overlay(ax, dataset, overlay, style)
    _basemap(ax, gdf, basemap)
    return finish(fig), ax


def grid_heatmap(cube, dataset=None, *, column: str | None = None, agg: str = "sum",
                 title: str = "", style: PlotStyle = PlotStyle()):
    """Rasterise a 200 m IBGE statistical-grid result to an image — legible where
    ~15 k polygons are not. Parses the ``NNNMEeeeeeNnnnnn`` grid id for the
    cell's row / col; falls back to a centroid raster otherwise."""
    style.apply()
    gdf = getattr(cube, "gdf", getattr(dataset, "gdf", None)).copy()
    if column is None:
        w = _wide(cube)
        gdf["_v"] = (w.sum(axis=1) if agg == "sum" else w.mean(axis=1)) \
            .reindex(gdf["unit_id"]).to_numpy()
        column = "_v"

    ids = gdf["unit_id"].astype(str)
    ext = ids.str.extract(r"E(\d+)N(\d+)")
    ok = ext.notna().all(axis=1).all()
    fig, ax = plt.subplots(figsize=(style.figsize[0], style.figsize[1]))
    if ok:
        e = ext[0].astype(int)
        n = ext[1].astype(int)
        col = (e.rank(method="dense").astype(int) - 1).to_numpy()          # compact col index
        row = ((-n).rank(method="dense").astype(int) - 1).to_numpy()       # N descending = row 0 top
        img = np.full((row.max() + 1, col.max() + 1), np.nan)
        img[row, col] = gdf[column].to_numpy()
        im = ax.imshow(img, cmap=style.cmap, interpolation="nearest")
    else:                                                     # centroid raster fallback
        c = gdf.to_crs(CRS_METRIC).geometry.centroid
        nb = 200
        xi = np.clip(((c.x - c.x.min()) / (c.x.max() - c.x.min()) * (nb - 1)).astype(int), 0, nb - 1)
        yi = np.clip(((c.y.max() - c.y) / (c.y.max() - c.y.min()) * (nb - 1)).astype(int), 0, nb - 1)
        img = np.full((nb, nb), np.nan)
        img[yi, xi] = gdf[column].to_numpy()
        im = ax.imshow(img, cmap=style.cmap, interpolation="nearest")
    ax.set_axis_off()
    fig.colorbar(im, ax=ax, shrink=0.6, label=column)
    ax.set_title(title or "Grid heatmap", fontsize=style.title_size)
    return finish(fig), ax


# --------------------------------------------------------------------------- #
#  interactive plotly maps
# --------------------------------------------------------------------------- #
def _all_palettes(style):
    return {**style.lisa_palette, **style.hotspot_palette,
            **style.ehsa_palette, **style.gi_bin_palette}


def _pick_column(gdf, result, dataset, column, extra):
    if column is not None:
        return column
    val = getattr(result, "value_col", None) or getattr(dataset, "value_col", "crime_count")
    for c in (*extra, val):
        if c is not None and c in gdf:
            return c
    raise ValueError("No plottable column found — pass column=.")


def interactive_map(result, dataset=None, *, column: str | None = None, title: str = "",
                    simplify: float = 20.0, style: PlotStyle = PlotStyle()):
    """Interactive plotly choropleth; categorical columns use the style
    palettes, numeric columns the style cmap."""
    import plotly.express as px

    gdf = getattr(result, "gdf", result)
    column = _pick_column(gdf, result, dataset, column,
                          ("category", "label", "modal_label", "risk_probability"))
    id_col = getattr(dataset, "id_col", "unit_id")
    cols = [c for c in dict.fromkeys((id_col, column)) if c in gdf]
    g = gdf[cols + [gdf.geometry.name]].to_crs(CRS_METRIC)
    g.geometry = g.geometry.simplify(simplify)
    g = g.to_crs("EPSG:4326")

    if g[column].dtype == object:
        palette = _all_palettes(style)
        order = [k for k in palette if k in g[column].values]
        fig = px.choropleth(g, geojson=g.geometry, locations=g.index, color=column,
                            color_discrete_map=palette, category_orders={column: order},
                            hover_data=cols)
    else:
        cmap = plt.get_cmap(style.cmap)
        fig = px.choropleth(g, geojson=g.geometry, locations=g.index, color=column,
                            color_continuous_scale=[to_hex(cmap(i / 10)) for i in range(11)],
                            hover_data=cols)
    fig.update_traces(marker_line_width=0.3, marker_line_color=style.edge_color)
    fig.update_geos(fitbounds="locations", visible=False, projection_type="mercator")
    fig.update_layout(title=title or column, template="simple_white",
                      width=int(style.figsize[0] * 100), height=int(style.figsize[1] * 100),
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig
