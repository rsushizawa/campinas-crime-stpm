"""3D space-time cube plots (matplotlib) and per-slice Gi* maps.

    from crime import space_time_cube_3d, ehsa_slice_maps, interactive_slice_map
    fig, ax = space_time_cube_3d(cube_result)            # one marker column per unit
    fig, axes = ehsa_slice_maps(ehsa_result, ds)         # small-multiple Gi_Bin choropleths
    fig = interactive_slice_map(ehsa_result)             # plotly, one animation frame per slice

Consumes: a cube (``CubeResult``: space_time_cube_3d), ``SpaceTimeLisaResult``
(space_time_lisa_cube), ``EhsaResult`` (interactive_slice_map,
ehsa_slice_maps). Gi_Bin classes come from :mod:`crime.esri.local`.

matplotlib functions return ``(fig, ax)``; plotly functions return a ``Figure``.
"""
import math

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, LogNorm

from crime.core.config import CRS_METRIC
from crime.esri.local import gi_confidence_bin
from crime.viz.frame import finish, period_labels
from crime.viz.style import PlotStyle

_LISA_ORDER = ["HH", "HL", "LH", "LL"]


def _unit_sides(gdf, crs_metric: str = CRS_METRIC) -> np.ndarray:
    """Marker side per unit — sqrt of the polygon area, clipped so outlier
    units cannot dwarf the rest."""
    sides = np.sqrt(gdf.to_crs(crs_metric).geometry.area.values)
    median = np.median(sides)
    return np.clip(sides, 0.5 * median, 2.0 * median)


# --------------------------------------------------------------------------- #
#  interactive per-slice map
# --------------------------------------------------------------------------- #
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
    sides = _unit_sides(result.gdf)
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
    sides = _unit_sides(result.gdf)
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
