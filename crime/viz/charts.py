"""Non-map charts.

    from crime import time_series, seasonal_plot, correlation_heatmap, moran_scatter
    from crime import cube_profiles, cluster_profiles

Space-time 2D view (the information-dense companion to the 3D cubes):
  ``cube_profiles(cube, units)`` — per-unit count + Gi* trajectory + trend

Consumes: ``TrendResult`` (time_series, seasonal_plot), ``CorrelationResult``
(correlation/clustered heatmaps), ``MoranResult`` (moran_scatter), a cube
(+ optional ``EhsaResult``; cube_profiles), ``TSClusterResult``
(cluster_profiles).

All return ``(fig, ax)``.
"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from libpysal.weights import lag_spatial

from crime.viz.frame import finish
from crime.viz.style import PlotStyle


def bar_chart(data, *, title: str = "", style: PlotStyle = PlotStyle()):
    """Horizontal bar of a labelled count series (crime types, weekdays, …)."""
    style.apply()
    series = data.iloc[:, 0] if isinstance(data, pd.DataFrame) else data
    fig, ax = plt.subplots(figsize=(style.figsize[0], style.figsize[1] * 0.6))
    series.sort_values().plot(kind="barh", ax=ax, color=style.bar_color)
    ax.set_xlabel("Count")
    ax.set_title(title, fontsize=style.title_size)
    return finish(fig), ax


def time_series(data, *, per_slug: bool = True, top: int = 8, logy: bool = False,
                stacked: bool = False, facet: bool = False, title: str = "",
                style: PlotStyle = PlotStyle()):
    """Crimes over time.

    With a ``TrendResult`` carrying ``by_slug``: one coloured line per crime type
    (``top`` busiest) + a bold black **Total** line. Options:
      ``logy``    — log y-axis so small types stay visible;
      ``stacked`` — share-of-total stacked area instead of lines;
      ``facet``   — one small panel per type (shared x), Total on top.
    ``per_slug=False`` or a bare Series -> total only.
    """
    style.apply()
    total = getattr(data, "by_period", data)
    if isinstance(total, pd.DataFrame):
        total = total.iloc[:, 0]
    by_slug = getattr(data, "by_slug", None) if per_slug else None

    if by_slug is not None and by_slug.shape[1] > 1 and facet:
        cols = list(by_slug.columns[:top])
        fig, axes = plt.subplots(len(cols) + 1, 1, sharex=True,
                                 figsize=(style.figsize[0], 0.7 * (len(cols) + 1)))
        axes[0].plot(total.index, total.values, color="black", lw=1.5)
        axes[0].set_ylabel("Total", rotation=0, ha="right", fontsize=style.font_size - 3)
        cmap = plt.get_cmap("tab20" if len(cols) > 10 else "tab10")
        for k, col in enumerate(cols, 1):
            axes[k].plot(by_slug.index, by_slug[col].values, color=cmap((k - 1) % cmap.N), lw=1.0)
            axes[k].set_ylabel(col, rotation=0, ha="right", fontsize=style.font_size - 4)
            if logy:
                axes[k].set_yscale("log")
        axes[0].set_title(title or "Crimes over time, by type", fontsize=style.title_size)
        return finish(fig), axes

    multi = by_slug is not None and by_slug.shape[1] > 1
    w = style.figsize[0] * (1.28 if multi else 1.0)
    fig, ax = plt.subplots(figsize=(w, style.figsize[1] * 0.5))

    def _legend():
        ax.legend(loc="center left", bbox_to_anchor=(1.015, 0.5),
                  fontsize=style.font_size - 3, framealpha=0.9,
                  ncol=2 if len(ax.get_legend_handles_labels()[0]) > 8 else 1)

    if multi and stacked:
        cols = list(by_slug.columns[:top])
        share = by_slug[cols].div(by_slug[cols].sum(axis=1), axis=0)
        cmap = plt.get_cmap("tab20" if len(cols) > 10 else "tab10")
        ax.stackplot(by_slug.index, *[share[c].values for c in cols], labels=cols,
                     colors=[cmap(i % cmap.N) for i in range(len(cols))])
        ax.set_ylim(0, 1)
        ax.set_ylabel("share of total")
        _legend()
    elif multi:
        cols = list(by_slug.columns[:top])
        cmap = plt.get_cmap("tab20" if len(cols) > 10 else "tab10")
        for i, col in enumerate(cols):
            ax.plot(by_slug.index, by_slug[col].values, lw=1.0, color=cmap(i % cmap.N), label=col)
        ax.plot(total.index, total.values, color="black", lw=2.0, label="Total", zorder=5)
        if logy:
            ax.set_yscale("log")
        _legend()
    else:
        ax.plot(total.index, total.values, color=style.line_color, lw=1.2)
        if logy:
            ax.set_yscale("log")

    ax.set_ylabel("share of total" if (multi and stacked) else "Crimes")
    ax.set_title(title or "Crimes over time", fontsize=style.title_size)
    finish(fig)
    if multi:
        fig.subplots_adjust(right=0.78)      # reserve room for the outside legend
    return fig, ax


def correlation_heatmap(result, *, title: str = "", style: PlotStyle = PlotStyle()):
    """Correlation matrix heatmap with annotated coefficients."""
    style.apply()
    matrix = getattr(result, "matrix", result)
    fig, ax = plt.subplots(figsize=style.figsize)
    im = ax.imshow(matrix.values, cmap=style.cmap_diverging, vmin=-1, vmax=1)
    ax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=90)
    ax.set_yticks(range(len(matrix.index)), matrix.index)
    for i in range(len(matrix.index)):
        for j in range(len(matrix.columns)):
            v = matrix.values[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                    fontsize=style.font_size - 3, color="white" if abs(v) > 0.5 else "black")
    fig.colorbar(im, shrink=0.7)
    ax.set_title(title or f"{getattr(result, 'method', '')} correlation".strip(),
                 fontsize=style.title_size)
    return finish(fig), ax


def clustered_heatmap(result, *, title: str = "", style: PlotStyle = PlotStyle()):
    """Correlation matrix with a hierarchical-clustering dendrogram along the top
    — reads as blocks of co-occurring crime types. Needs a ``CorrelationResult``
    from ``crime_crime_correlation(cluster=True)`` (falls back to a plain
    heatmap if there's no linkage)."""
    style.apply()
    matrix = getattr(result, "matrix", result)
    linkage = getattr(result, "linkage", None)
    if linkage is None:
        return correlation_heatmap(result, title=title, style=style)

    from scipy.cluster.hierarchy import dendrogram

    fig, (dax, hax) = plt.subplots(
        2, 1, figsize=style.figsize, height_ratios=[1, 5], gridspec_kw={"hspace": 0.02})
    dendrogram(linkage, ax=dax, labels=list(matrix.columns), no_labels=True,
               color_threshold=0, link_color_func=lambda _: style.line_color)
    dax.set_axis_off()
    im = hax.imshow(matrix.values, cmap=style.cmap_diverging, vmin=-1, vmax=1, aspect="auto")
    hax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=90)
    hax.set_yticks(range(len(matrix.index)), matrix.index)
    for i in range(len(matrix.index)):
        for j in range(len(matrix.columns)):
            v = matrix.values[i, j]
            hax.text(j, i, f"{v:.2f}", ha="center", va="center",
                     fontsize=style.font_size - 4, color="white" if abs(v) > 0.5 else "black")
    fig.colorbar(im, ax=hax, shrink=0.7)
    dax.set_title(title or "Crime-type co-location (clustered)", fontsize=style.title_size)
    return fig, (dax, hax)


def moran_scatter(result, *, title: str = "", style: PlotStyle = PlotStyle()):
    """Standardised value vs spatial lag, with the OLS fit line."""
    style.apply()
    y = result.gdf[result.value_col].values.astype(float)
    z = (y - y.mean()) / y.std()
    lag = lag_spatial(result.weights, z)

    fig, ax = plt.subplots(figsize=style.figsize)
    ax.axhline(0, color="grey", lw=0.8, ls="--")
    ax.axvline(0, color="grey", lw=0.8, ls="--")
    ax.scatter(z, lag, s=10, alpha=0.5, edgecolors="none", color=style.line_color)
    m, b = np.polyfit(z, lag, 1)
    xs = np.linspace(z.min(), z.max(), 100)
    ax.plot(xs, m * xs + b, color="black", lw=1.5)
    # Independent x/y padding around the data (not a single square forced by
    # whichever axis has the longer tail) -- keeps the point cloud filling the
    # panel instead of floating in a mostly-empty square.
    xpad = (z.max() - z.min()) * 0.06
    ypad = (lag.max() - lag.min()) * 0.06
    ax.set_xlim(z.min() - xpad, z.max() + xpad)
    ax.set_ylim(lag.min() - ypad, lag.max() + ypad)
    ax.set_xlabel(f"Standardized {result.value_col}")
    ax.set_ylabel("Spatial lag")
    ax.set_title(title or f"Moran scatter — I = {result.I:.3f} (p = {result.p_sim:.3f})",
                 fontsize=style.title_size)
    return finish(fig), ax



def seasonal_plot(trend_result, *, title: str = "", style: PlotStyle = PlotStyle()):
    """STL decomposition of the total-crime series (observed / trend / seasonal /
    residual). Needs a ``TrendResult`` from ``temporal_trends`` that carries
    ``.stl``."""
    style.apply()
    stl = getattr(trend_result, "stl", None)
    if stl is None:
        raise ValueError("No STL on this TrendResult — temporal_trends needs >= 2 full years.")
    parts = [("observed", stl["observed"]), ("trend", stl["trend"]),
             ("seasonal", stl["seasonal"]), ("residual", stl["resid"])]
    fig, axes = plt.subplots(4, 1, sharex=True, figsize=(style.figsize[0], style.figsize[1]))
    for ax, (name, s) in zip(axes, parts):
        ax.plot(s.index, s.values, color=style.line_color, lw=1.1)
        ax.set_ylabel(name, rotation=0, ha="right", fontsize=style.font_size - 2)
        ax.axhline(0, color="grey", lw=0.5) if name in ("seasonal", "residual") else None
    axes[0].set_title(title or "Seasonal-trend decomposition (STL)", fontsize=style.title_size)
    return finish(fig), axes


# --------------------------------------------------------------------------- #
#  space-time cube / EHSA — 2D information-dense views
# --------------------------------------------------------------------------- #
def _period_str(cols) -> list[str]:
    return [c.strftime("%Y-%m") if hasattr(c, "strftime") else str(c) for c in cols]


def cube_profiles(cube, units, *, ehsa=None, weights: str = "queen", title: str = "",
                  style: PlotStyle = PlotStyle()):
    """One panel per unit: crime count (bars, left axis) + Gi\\*-z trajectory
    (line, right axis, ±1.96 guides) + a robust (Theil–Sen) trend line on z.
    ``ehsa`` (an ``EhsaResult``) supplies the z-matrix + category label; without
    it the Gi\\*-z series is computed on the fly (:mod:`crime.esri.ehsa`)."""
    from scipy.stats import theilslopes

    style.apply()
    wide = getattr(cube, "wide", cube)
    per = _period_str(wide.columns)
    x = np.arange(wide.shape[1])
    if ehsa is not None:
        zdf = ehsa.z_matrix
        labels = ehsa.gdf.set_index("unit_id")["category"] if "unit_id" in ehsa.gdf else None
    else:
        from crime.esri.ehsa import gi_time_series
        from crime.esri.weights import spatial_weights
        w = spatial_weights(getattr(cube, "gdf"), kind=weights)
        z, _, _, _ = gi_time_series(wide, w)
        zdf = pd.DataFrame(z, index=wide.index, columns=wide.columns)
        labels = None

    units = [u for u in units if u in wide.index]
    fig, axes = plt.subplots(len(units), 1, sharex=True,
                             figsize=(style.figsize[0], 1.5 * len(units) + 0.5))
    for ax, u in zip(np.atleast_1d(axes), units):
        c = wide.loc[u].values.astype(float)
        z = zdf.loc[u].values.astype(float) if u in zdf.index else np.zeros_like(c)
        ax.bar(x, c, color=style.bar_color, alpha=0.5, width=0.9)
        ax.set_ylabel("count", color=style.bar_color, fontsize=style.font_size - 2)
        az = ax.twinx()
        az.plot(x, z, color="#d7191c", lw=1.4)
        for h in (-1.96, 1.96):
            az.axhline(h, color="grey", lw=0.6, ls="--")
        sl, ic, *_ = theilslopes(z, x)
        az.plot(x, ic + sl * x, color="black", lw=1.0, ls=":")
        az.set_ylabel("Gi* z", color="#d7191c", fontsize=style.font_size - 2)
        lab = f"  ·  {labels[u]}" if labels is not None and u in labels.index else ""
        ax.set_title(f"{u}{lab}   (trend z/bin {sl:+.3f})", fontsize=style.font_size - 1, loc="left")
    tk = np.unique(np.linspace(0, len(per) - 1, min(8, len(per)), dtype=int))
    np.atleast_1d(axes)[-1].set_xticks(tk, [per[i] for i in tk], rotation=45, ha="right")
    fig.suptitle(title or "Space-time cube — unit profiles", fontsize=style.title_size)
    return finish(fig), axes


def cluster_profiles(result, *, title: str = "", style: PlotStyle = PlotStyle()):
    """Time-series-clustering result: the mean trajectory of each cluster (left)
    and the cluster sizes (right). ``result`` is a ``TSClusterResult``."""
    style.apply()
    prof = result.profiles
    per = _period_str(prof.columns)
    cmap = plt.get_cmap("tab10" if len(prof) <= 10 else "tab20")
    fig, (ax, axb) = plt.subplots(1, 2, figsize=(style.figsize[0], style.figsize[1] * 0.5),
                                  gridspec_kw={"width_ratios": [4, 1]})
    for i, (name, row) in enumerate(prof.iterrows()):
        ax.plot(per, row.values, color=cmap(i % cmap.N), lw=1.6, label=name)
    tk = np.unique(np.linspace(0, len(per) - 1, min(8, len(per)), dtype=int))
    ax.set_xticks(tk, [per[j] for j in tk], rotation=45, ha="right", fontsize=style.font_size - 2)
    ax.set_ylabel("mean crimes / bin")
    ax.legend(fontsize=style.font_size - 3, framealpha=0.9)
    sizes = result.gdf["cluster"].value_counts().sort_index()
    axb.barh([f"cluster {i}" for i in sizes.index], sizes.values,
             color=[cmap(i % cmap.N) for i in sizes.index])
    axb.set_xlabel("units")
    axb.invert_yaxis()
    fig.suptitle(title or f"Time-series clusters ({result.method}, k={result.k})",
                 fontsize=style.title_size)
    return finish(fig), (ax, axb)
