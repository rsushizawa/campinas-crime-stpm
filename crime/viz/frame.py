"""Shared map furniture for the static matplotlib maps: figure/axes setup,
article-style graticule + scale bar + north arrow, boundary overlay, and
time-period label formatting. Consumes plain GeoDataFrames (and
``Dataset.overlay`` for boundaries); basemap tiles live in
:mod:`crime.viz.basemap`.

These are plain functions — every map in ``crime.viz.maps`` / ``crime.viz.cubes``
calls them directly:

    fig, ax = map_axes(style, title="Gi* hot spots")
    gdf.plot(ax=ax, ...)
    map_frame(ax, gdf, style)
    boundary_overlay(ax, dataset.overlay, style)
    fig = finish(fig)
"""
import math

import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.ticker import FuncFormatter, MaxNLocator
from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar
from pyproj import Transformer

from crime.viz.style import PlotStyle


def map_axes(style: PlotStyle = PlotStyle(), title: str = "", ax=None):
    """A new ``(fig, ax)``, or ``ax`` and its figure when drawing into a caller's panel."""
    style.apply()
    if ax is None:
        fig, ax = plt.subplots(figsize=style.figsize)
    else:
        fig = ax.figure
    ax.set_axis_off()
    if title:
        ax.set_title(title, fontsize=style.title_size)
    return fig, ax


def finish(fig, own: bool = True):
    """``tight_layout`` a figure the map function created (``own``); a caller's
    multi-panel figure is left to the caller."""
    if own:
        fig.tight_layout()
    return fig


def period_labels(columns) -> list[str]:
    return [c.strftime("%Y-%m") if hasattr(c, "strftime") else str(c) for c in columns]


def boundary_overlay(ax, boundaries, style: PlotStyle = PlotStyle()):
    """Draw boundary polygons (e.g. UTBs) on top of an existing map axis.
    ``boundaries`` is a GeoDataFrame (use ``dataset.overlay``)."""
    if boundaries is None:
        raise ValueError("No boundaries given — build the dataset with overlay=True.")
    target_crs = getattr(ax, "_crime_crs", None) or boundaries.crs
    boundaries.to_crs(target_crs).boundary.plot(
        ax=ax, color=style.boundary_color, linewidth=style.boundary_width
    )
    return ax


def _nice(v: float) -> float:
    """Largest 1/2/2.5/5 x 10^k not above ``v``."""
    exp = math.floor(math.log10(v))
    base = v / 10 ** exp
    return (5 if base >= 5 else 2.5 if base >= 2.5 else 2 if base >= 2 else 1) * 10 ** exp


def alternating_scale_bar(ax, unit_m: float, style: PlotStyle = PlotStyle(), *, segments: int = 4,
                          fraction: float = 0.5, loc: str = "lower left", margin: float = 0.05):
    """Cartographic alternating ("stepped") scale bar: a line that switches
    between an upper and a lower level at every segment, labelled
    ``0  5  10  15  20 km`` above the breaks. ``fraction`` is the target bar
    length as a share of the map width; ``loc`` is ``"lower left"`` or
    ``"lower right"``, ``margin`` the gap to the frame in axes fraction. No
    box (Kim et al. 2025 style)."""
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    seg = _nice((xmax - xmin) * unit_m * fraction / segments)      # metres per segment
    step = seg / unit_m
    if loc == "lower left":
        x = xmin + margin * (xmax - xmin)
    elif loc == "lower right":
        x = xmax - margin * (xmax - xmin) - segments * step - 0.06 * (xmax - xmin)   # room for "km"
    else:
        raise ValueError("loc must be 'lower left' or 'lower right'")
    y = ymin + margin * (ymax - ymin)
    h = 0.018 * (ymax - ymin)
    kw = dict(color=style.boundary_color, lw=0.7, solid_capstyle="butt", zorder=12)
    for k in range(segments + 1):
        ax.plot([x + k * step] * 2, [y, y + h], **kw)                    # break ticks
        if k < segments:
            yy = y + h if k % 2 == 0 else y
            ax.plot([x + k * step, x + (k + 1) * step], [yy, yy], **kw)
    km = seg >= 1000
    small = style.font_size - 3
    for k in range(segments + 1):
        ax.text(x + k * step, y + h * 1.5, f"{k * seg / (1000 if km else 1):g}", ha="center",
                va="bottom", fontsize=small, zorder=12)
    ax.annotate(" km" if km else " m", xy=(x + segments * step, y + h * 1.5), xytext=(4, 0),
                textcoords="offset points", ha="left", va="bottom", fontsize=small, zorder=12)
    return seg


def map_frame(ax, gdf, style: PlotStyle = PlotStyle(), *, scalebar: str = "box",
              scalebar_loc: str = "lower left", scalebar_segments: int = 4):
    """Lat/lon labels on all four sides, a scale bar and a north arrow.
    Degree labels assume the projected-CRS graticule is near-rectangular over
    the map extent (true at city scale). ``scalebar``: ``"box"`` (boxed bar,
    the default) or ``"alternating"`` (stepped cartographic bar, see
    :func:`alternating_scale_bar`, placed at ``scalebar_loc``)."""
    ax._crime_crs = gdf.crs
    ax.set_axis_on()
    for spine in ax.spines.values():
        spine.set_visible(True)
    small = style.font_size - 3
    xmid = sum(ax.get_xlim()) / 2
    ymid = sum(ax.get_ylim()) / 2

    if gdf.crs and not gdf.crs.is_geographic:
        tr = Transformer.from_crs(gdf.crs, 4326, always_xy=True)
        unit_m = 1.0
    else:
        tr = None
        unit_m = 111_320 * math.cos(math.radians(ymid))

    def _deg(v, hemis):
        return f"{abs(v):.2f}\N{DEGREE SIGN}{hemis[int(v < 0)]}"

    ax.xaxis.set_major_formatter(FuncFormatter(
        lambda x, _: _deg(tr.transform(x, ymid)[0] if tr else x, "EW")))
    ax.yaxis.set_major_formatter(FuncFormatter(
        lambda y, _: _deg(tr.transform(xmid, y)[1] if tr else y, "NS")))
    ax.xaxis.set_major_locator(MaxNLocator(4))
    ax.yaxis.set_major_locator(MaxNLocator(4))
    ax.tick_params(top=True, right=True, labeltop=True, labelright=True,
                   labelsize=small, length=3)

    if scalebar == "alternating":
        alternating_scale_bar(ax, unit_m, style, loc=scalebar_loc, segments=scalebar_segments)
    elif scalebar == "box":
        span_m = (ax.get_xlim()[1] - ax.get_xlim()[0]) * unit_m
        exp = math.floor(math.log10(span_m / 4))
        base = span_m / 4 / 10 ** exp
        nice = (5 if base >= 5 else 2 if base >= 2 else 1) * 10 ** exp
        label = f"{nice / 1000:g} km" if nice >= 1000 else f"{nice:g} m"
        ax.add_artist(AnchoredSizeBar(
            ax.transData, nice / unit_m, label, "lower left",
            pad=0.4, sep=4, frameon=True,
            size_vertical=(ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.005,
            fontproperties=FontProperties(size=small)))
    else:
        raise ValueError("scalebar must be 'box' or 'alternating'")

    ax.annotate("", xy=(0.97, 0.965), xytext=(0.97, 0.90), xycoords="axes fraction",
                arrowprops={"arrowstyle": "-|>", "color": style.boundary_color})
    ax.text(0.97, 0.975, "N", transform=ax.transAxes, ha="center", fontsize=style.font_size)
    return ax
