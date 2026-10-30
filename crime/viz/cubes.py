"""3D space-time cube plots — matplotlib (static) and plotly (interactive).

    from crime import interactive_cube, interactive_ehsa_cube, ehsa_slice_maps
    fig = interactive_cube(cube_result, ds)              # extruded-prism cube + time slider
    fig = interactive_ehsa_cube(ehsa_result, ds)         # voxels over an EHSA-category ground
    fig, axes = ehsa_slice_maps(ehsa_result, ds)         # small-multiple Gi_Bin choropleths

Consumes: a cube (``CubeResult``: interactive_cube, space_time_cube_3d),
``SpaceTimeLisaResult`` (the LISA cubes), ``EhsaResult`` (interactive_ehsa_cube,
interactive_slice_map, ehsa_slice_maps, ehsa_transition_sankey). Gi_Bin classes
and window transitions come from :mod:`crime.esri`.

matplotlib functions return ``(fig, ax)``; plotly functions return a ``Figure``.
"""
import math

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, LogNorm, to_hex

from crime.core.config import CRS_METRIC
from crime.esri.local import gi_confidence_bin
from crime.viz.frame import finish, period_labels
from crime.viz.style import PlotStyle
from crime.viz.voxel import VoxelMesh, time_slider

_LISA_ORDER = ["HH", "HL", "LH", "LL"]


def _decimate(result, top_n):
    """Return a shallow view of a cube result restricted to the ``top_n`` busiest
    units (by total count) — keeps the 3D cubes renderable at grid / segment
    scale. ``None`` or a result smaller than ``top_n`` is passed through."""
    wide = getattr(result, "wide", None)
    if top_n is None or wide is None or len(wide) <= top_n:
        return result
    keep = wide.sum(axis=1).nlargest(top_n).index
    from types import SimpleNamespace
    gdf = result.gdf
    gid = "unit_id" if "unit_id" in gdf else gdf.index
    gdf_keep = gdf.set_index(gid).loc[keep].reset_index(drop=("unit_id" not in gdf))
    return SimpleNamespace(wide=wide.loc[keep], gdf=gdf_keep,
                           freq=getattr(result, "freq", "ME"))


def _cube_scene_layout(fig, periods, z_scale, title, style, *, trace_bins=None):
    tick_idx = np.unique(np.linspace(0, len(periods) - 1, min(6, len(periods)), dtype=int))
    layout = dict(
        title=title, template="simple_white",
        width=int(style.figsize[0] * 100), height=int(style.figsize[1] * 100),
        scene=dict(
            xaxis=dict(visible=False), yaxis=dict(visible=False),
            zaxis=dict(title="", tickvals=(tick_idx * z_scale).tolist(),
                       ticktext=[periods[i] for i in tick_idx]),
            aspectmode="data",
        ),
    )
    if trace_bins is not None:
        layout["sliders"] = time_slider(trace_bins, periods)
    fig.update_layout(**layout)
    return fig


def _log_facecolors(vals, style):
    strength = np.log10(vals) / max(np.log10(vals.max()), 1e-9)
    cmap = plt.get_cmap(style.cmap)
    return cmap, np.array([to_hex(c) for c in cmap(strength)])


def _log_colorbar(cmap, vals, title):
    import plotly.graph_objects as go

    return go.Scatter3d(
        x=[None], y=[None], z=[None], mode="markers",
        marker=dict(color=[0, 1],
                    colorscale=[[i / 10, to_hex(cmap(i / 10))] for i in range(11)],
                    showscale=True,
                    colorbar=dict(title=title,
                                  tickvals=(np.log10([1, 3, 10, 30, 100])
                                            / max(np.log10(vals.max()), 1e-9)),
                                  ticktext=["1", "3", "10", "30", "100"])),
        hoverinfo="none", showlegend=False)


# --------------------------------------------------------------------------- #
#  interactive plotly cubes
# --------------------------------------------------------------------------- #
def interactive_cube(result, dataset=None, *, min_count: int = 1, gap: float = 0.08,
                     top_n: int | None = 1500, title: str = "", style: PlotStyle = PlotStyle()):
    """Each unit's real footprint extruded per time bin, stacked into layers
    over a flat ground, coloured by log crime count, with a cumulative slider.
    ``top_n`` keeps only the busiest N units — set ``None`` for all (slow /
    unreadable at grid or street-segment scale)."""
    import plotly.graph_objects as go

    result = _decimate(result, top_n)
    wide = result.wide
    caps, walls = VoxelMesh.prism_template(result.gdf)
    counts = wide.values
    unit_idx, t_idx = np.nonzero(counts >= min_count)
    vals = counts[unit_idx, t_idx]
    cmap, facecolor = _log_facecolors(vals, style)

    periods = period_labels(wide.columns)
    units = wide.index.values[unit_idx]
    hover = np.array([f"{u}<br>{periods[t]}<br>{v} crimes"
                      for u, t, v in zip(units, t_idx, vals)])

    bounds = result.gdf.to_crs(CRS_METRIC).total_bounds
    z_scale = (bounds[2] - bounds[0]) / max(wide.shape[1], 1)
    traces, trace_bins = [], []
    for t in range(wide.shape[1]):
        sel = t_idx == t
        if not sel.any():
            continue
        mesh = VoxelMesh.build_prisms(caps, walls, unit_idx[sel], t_idx[sel] * z_scale,
                                      z_scale * (1 - gap), facecolor[sel], hover[sel])
        traces.append(go.Mesh3d(name=periods[t], showlegend=False, **mesh))
        trace_bins.append(t)

    ground = VoxelMesh.ground(caps, z=-0.6 * z_scale)
    fig = go.Figure(traces + [go.Mesh3d(**ground), _log_colorbar(cmap, vals, "Crimes per bin")])
    trace_bins += [None, None]
    return _cube_scene_layout(fig, periods, z_scale, title or "Space-time cube", style,
                              trace_bins=trace_bins)


def interactive_lisa_cube(result, dataset=None, *, quadrants=("HH", "HL", "LH", "LL"),
                          gap: float = 0.08, title: str = "", style: PlotStyle = PlotStyle()):
    """Full-size voxels for the significant bins, coloured by LISA quadrant."""
    import plotly.graph_objects as go

    labels = result.labels
    centroids = result.gdf.to_crs(CRS_METRIC).geometry.centroid
    sides = VoxelMesh.unit_sides(result.gdf)
    x_unit, y_unit = centroids.x.values, centroids.y.values
    periods = period_labels(labels.columns)
    z_scale = (x_unit.max() - x_unit.min()) / max(labels.shape[1], 1)

    traces = []
    for quad in [q for q in _LISA_ORDER if q in quadrants]:
        unit_idx, t_idx = np.nonzero(labels.values == quad)
        if len(unit_idx) == 0:
            continue
        hover = np.array([f"{labels.index[u]}<br>{periods[t]}<br>{quad}"
                          for u, t in zip(unit_idx, t_idx)])
        mesh = VoxelMesh.build(
            x_unit[unit_idx], y_unit[unit_idx], t_idx * z_scale,
            sides[unit_idx] * (1 - gap), sides[unit_idx] * (1 - gap), z_scale * (1 - gap),
            np.array([style.lisa_palette[quad]] * len(unit_idx)), hover)
        traces.append(go.Mesh3d(name=quad, showlegend=True, **mesh))

    fig = go.Figure(traces)
    fig.update_layout(legend=dict(itemsizing="constant"))
    return _cube_scene_layout(fig, periods, z_scale, title or "Space-time LISA", style)


def interactive_ehsa_cube(result, dataset=None, *, value_matrix=None, gap: float = 0.08,
                          cube: bool = False, title: str = "", style: PlotStyle = PlotStyle()):
    """Voxel columns (coloured by value, log scale) above an EHSA-category
    choropleth ground; one ground trace per category (legend-toggleable)."""
    import plotly.graph_objects as go

    from crime.esri.cube import space_time_cube

    gdf = result.gdf
    periods = period_labels(result.z_matrix.columns)
    bounds = gdf.to_crs(CRS_METRIC).total_bounds
    z_scale = (bounds[2] - bounds[0]) / max(len(periods), 1)

    if value_matrix is None:
        if dataset is None:
            raise ValueError("interactive_ehsa_cube needs dataset or value_matrix.")
        c = space_time_cube(dataset, freq=result.freq)
        value_matrix = c.wide.reindex(index=gdf[dataset.id_col],
                                      columns=result.z_matrix.columns, fill_value=0)
    values = value_matrix.values

    proj = gdf.to_crs(CRS_METRIC).geometry.centroid
    x, y = proj.x.values, proj.y.values
    side = VoxelMesh.unit_sides(gdf) * (1 - gap)

    u_idx, t_idx = np.nonzero(values > 0)
    vals = values[u_idx, t_idx]
    cmap, facecolor = _log_facecolors(vals, style)
    unit_labels = value_matrix.index.values[u_idx]
    hover = np.array([f"{u}<br>{periods[t]}<br>{v:g}"
                      for u, t, v in zip(unit_labels, t_idx, vals)])

    traces, trace_bins = [], []
    for t in range(len(periods)):
        sel = t_idx == t
        if not sel.any():
            continue
        mesh = VoxelMesh.build(
            x[u_idx[sel]], y[u_idx[sel]], t_idx[sel] * z_scale + 0.5 * z_scale,
            side[u_idx[sel]], side[u_idx[sel]], z_scale * (1 - gap),
            facecolor[sel], hover[sel])
        traces.append(go.Mesh3d(name=periods[t], showlegend=False, **mesh))
        trace_bins.append(t)

    caps, _ = VoxelMesh.prism_template(gdf, tol_frac=0.0)
    palette = style.ehsa_palette
    cats = gdf["category"].values
    for cat in [c for c in palette if c in cats]:
        sub_caps = [c for c, keep in zip(caps, cats == cat) if keep]
        traces.append(go.Mesh3d(name=cat, showlegend=True,
                                **VoxelMesh.ground(sub_caps, color=palette[cat], z=0)))
        trace_bins.append(None)

    traces.append(_log_colorbar(cmap, vals, "Value per bin"))
    trace_bins.append(None)

    fig = go.Figure(traces)
    fig.update_layout(legend=dict(itemsizing="constant"))
    fig = _cube_scene_layout(fig, periods, z_scale, title or "EHSA space-time cube", style,
                             trace_bins=trace_bins)
    if cube:
        fig.update_layout(scene=dict(aspectmode="cube"))
    return fig


def interactive_slice_map(result, dataset=None, *, simplify: float = 20.0, title: str = "",
                          style: PlotStyle = PlotStyle()):
    """Interactive choropleth with a per-interval animation frame, units
    coloured by their Gi* hot/cold confidence bin in that slice."""
    import plotly.express as px

    z = result.z_matrix
    labels = gi_confidence_bin(z.values)
    periods = period_labels(z.columns)
    palette = style.gi_bin_palette

    g = result.gdf.to_crs(CRS_METRIC).reset_index(drop=True)
    g.geometry = g.geometry.simplify(simplify)
    g = g.to_crs("EPSG:4326")

    long = pd.DataFrame({
        "location": np.tile(g.index.values, z.shape[1]),
        "unit": np.tile(z.index.values, z.shape[1]),
        "period": np.repeat(periods, z.shape[0]),
        "Gi bin": labels.ravel(order="F"),
        "z": z.values.ravel(order="F").round(2),
    })
    fig = px.choropleth(long, geojson=g.geometry, locations="location", color="Gi bin",
                        animation_frame="period", color_discrete_map=palette,
                        category_orders={"Gi bin": list(palette)},
                        hover_data={"unit": True, "z": True, "location": False})
    fig.update_traces(marker_line_width=0.3, marker_line_color=style.edge_color)
    fig.update_geos(fitbounds="locations", visible=False, projection_type="mercator")
    fig.update_layout(title=title or "Gi* hot & cold spots per interval", template="simple_white",
                      width=int(style.figsize[0] * 100), height=int(style.figsize[1] * 100),
                      margin=dict(l=10, r=10, t=40, b=10))
    return fig


# --------------------------------------------------------------------------- #
#  static matplotlib cubes / small multiples
# --------------------------------------------------------------------------- #
def space_time_cube_3d(result, dataset=None, *, min_count: int = 1, elev: float = 25,
                       azim: float = -60, voxel_size: float = 1.0, title: str = "",
                       style: PlotStyle = PlotStyle()):
    """One voxel column per unit, time bins bottom (oldest) to top, coloured by count."""
    style.apply()
    wide = result.wide
    centroids = result.gdf.to_crs(CRS_METRIC).geometry.centroid
    sides = VoxelMesh.unit_sides(result.gdf)
    x_unit, y_unit = centroids.x.values, centroids.y.values

    counts = wide.values
    unit_idx, t_idx = np.nonzero(counts >= min_count)
    vals = counts[unit_idx, t_idx]

    base = plt.get_cmap(style.cmap)
    cmap = LinearSegmentedColormap.from_list("visible", base(np.linspace(0.25, 1.0, 256)))
    norm = LogNorm(vmin=max(1, vals.min()), vmax=vals.max())

    order = np.argsort(vals)
    unit_idx, t_idx, vals = unit_idx[order], t_idx[order], vals[order]
    strength = norm(vals).data
    colors = cmap(strength)
    colors[:, 3] = 0.1 + 0.9 * strength

    fig = plt.figure(figsize=style.figsize)
    ax = fig.add_subplot(projection="3d")
    pts_per_m = style.figsize[0] * 72 * 0.5 / (x_unit.max() - x_unit.min())
    s = (voxel_size * sides[unit_idx] * pts_per_m) ** 2
    sc = ax.scatter(x_unit[unit_idx], y_unit[unit_idx], t_idx, c=colors, marker="s",
                    s=s, linewidths=0)
    sc.set_cmap(cmap)
    sc.set_norm(norm)

    labels = period_labels(wide.columns)
    ticks = np.unique(np.linspace(0, wide.shape[1] - 1, min(6, wide.shape[1]), dtype=int))
    ax.set_zticks(ticks)
    ax.set_zticklabels([labels[t] for t in ticks], fontsize=style.font_size - 2)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_box_aspect((1, (y_unit.max() - y_unit.min()) / (x_unit.max() - x_unit.min()), 0.9))
    ax.view_init(elev=elev, azim=azim)
    ax.set_title(title or "Space-time cube", fontsize=style.title_size)
    fig.colorbar(sc, shrink=0.5, pad=0.1, label="Crimes per bin")
    return finish(fig), ax


def space_time_lisa_cube(result, dataset=None, *, elev: float = 25, azim: float = -60,
                         voxel_size: float = 1.0, quadrants=("HH", "HL", "LH", "LL"),
                         title: str = "", style: PlotStyle = PlotStyle()):
    """3D cube coloured by LISA cluster type — significant bins only."""
    style.apply()
    labels = result.labels
    centroids = result.gdf.to_crs(CRS_METRIC).geometry.centroid
    sides = VoxelMesh.unit_sides(result.gdf)
    x_unit, y_unit = centroids.x.values, centroids.y.values

    fig = plt.figure(figsize=style.figsize)
    ax = fig.add_subplot(projection="3d")
    pts_per_m = style.figsize[0] * 72 * 0.5 / (x_unit.max() - x_unit.min())
    values = labels.values
    for quad in [q for q in _LISA_ORDER if q in quadrants]:
        unit_idx, t_idx = np.nonzero(values == quad)
        if len(unit_idx) == 0:
            continue
        ax.scatter(x_unit[unit_idx], y_unit[unit_idx], t_idx,
                   color=style.lisa_palette[quad], marker="s",
                   s=(voxel_size * sides[unit_idx] * pts_per_m) ** 2, alpha=0.8, linewidths=0)

    names = period_labels(labels.columns)
    ticks = np.unique(np.linspace(0, labels.shape[1] - 1, min(6, labels.shape[1]), dtype=int))
    ax.set_zticks(ticks)
    ax.set_zticklabels([names[t] for t in ticks], fontsize=style.font_size - 2)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_box_aspect((1, (y_unit.max() - y_unit.min()) / (x_unit.max() - x_unit.min()), 0.9))
    ax.view_init(elev=elev, azim=azim)
    ax.set_title(title or "Space-time LISA", fontsize=style.title_size)
    present = [q for q in _LISA_ORDER if q in quadrants and (values == q).any()]
    ax.legend(handles=[mpatches.Patch(color=style.lisa_palette[q], label=q) for q in present],
              loc="upper left", framealpha=0.9)
    return finish(fig), ax


def ehsa_slice_maps(result, dataset=None, *, ncols: int = 4, max_slices: int = 36,
                    title: str = "", style: PlotStyle = PlotStyle()):
    """Small multiples: one choropleth per time slice, coloured by Gi_Bin class.
    With more than ``max_slices`` bins, every k-th slice is shown (evenly spaced)
    rather than erroring."""
    style.apply()
    z = result.z_matrix
    note = ""
    if z.shape[1] > max_slices:
        keep = np.unique(np.linspace(0, z.shape[1] - 1, max_slices, dtype=int))
        z = z.iloc[:, keep]
        note = f"  (every {max(1, result.z_matrix.shape[1] // max_slices)} slices)"
    labels = gi_confidence_bin(z.values)
    names = period_labels(z.columns)
    palette = style.gi_bin_palette

    n = z.shape[1]
    ncols = min(ncols, n)
    nrows = math.ceil(n / ncols)
    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(style.figsize[0], style.figsize[0] * nrows / ncols))
    for k, ax in enumerate(np.atleast_1d(axes).ravel()):
        ax.set_axis_off()
        if k >= n:
            continue
        result.gdf.plot(color=[palette[l] for l in labels[:, k]], ax=ax,
                        edgecolor=style.edge_color, linewidth=style.edge_width * 0.5)
        ax.set_title(names[k], fontsize=style.font_size - 1)

    present = [b for b in palette if b in labels]
    fig.legend(handles=[mpatches.Patch(color=palette[b], label=b) for b in present],
               loc="lower center", ncol=min(len(present), 7), framealpha=0.9,
               fontsize=style.font_size - 2)
    fig.suptitle((title or "Gi* hot & cold spots per interval") + note, fontsize=style.title_size)
    return finish(fig), axes


# --------------------------------------------------------------------------- #
#  EHSA transitions — alluvial / Sankey
# --------------------------------------------------------------------------- #
def ehsa_transition_sankey(result, *, window: int = 3, title: str = "",
                           style: PlotStyle = PlotStyle()):
    """How units move between hot / none / cold over successive rolling windows.
    ``result`` is an ``EhsaResult`` (uses its ``z_matrix``). Returns a Plotly
    ``Figure`` — one node column per window, links = unit counts."""
    import plotly.graph_objects as go

    from crime.esri.transitions import rolling_states, transition_counts

    state = rolling_states(result.z_matrix.values, window=window)   # 0 cold, 1 none, 2 hot
    n_win = state.shape[1]

    from matplotlib.colors import to_rgba

    def _rgba(hexc, a):
        r, g, b, _ = to_rgba(hexc)
        return f"rgba({int(r*255)},{int(g*255)},{int(b*255)},{a})"

    names = ["cold", "none", "hot"]
    colors = {0: style.lisa_palette["LL"], 1: "#d9d9d9", 2: style.lisa_palette["HH"]}
    node_label, node_color, idx = [], [], {}
    for k in range(n_win):
        for s in range(3):
            idx[(k, s)] = len(node_label)
            node_label.append(f"W{k + 1} {names[s]}")
            node_color.append(colors[s])

    src, tgt, val, lcol = [], [], [], []
    for (k, a, b), c in transition_counts(state).items():
        src.append(idx[(k, a)]); tgt.append(idx[(k + 1, b)]); val.append(c)
        lcol.append(_rgba(colors[b], 0.45))
    fig = go.Figure(go.Sankey(
        node=dict(label=node_label, color=node_color, pad=14, thickness=14),
        link=dict(source=src, target=tgt, value=val, color=lcol)))
    fig.update_layout(title=title or f"EHSA transitions ({window}-slice windows)",
                      template="simple_white", font_size=style.font_size,
                      width=int(style.figsize[0] * 110), height=int(style.figsize[1] * 90))
    return fig
