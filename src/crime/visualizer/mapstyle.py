"""Map furniture shared by the notebooks: basemap tiles, boundary overlay, graticule, alternating
scale bar, north arrow, and colour + hatch categorical layers with a grouped legend.

Plain matplotlib / geopandas / contextily; restores the look of the earlier ``crime.viz`` maps
(branch ``archive/pre-notebooks``: ``frame.py``, ``basemap.py``, ``style.py``). Typical use::

    from crime.visualizer import mapstyle as ms
    ms.setup()
    ms.plot_categories(ax, units, labels, STYLES)        # STYLES: label -> (facecolor, hatch)
    ms.decorate(ax, tracts.crs)                          # basemap, graticule, scale, north
"""
import math

import matplotlib as mpl
import numpy as np
from matplotlib.colors import to_rgb
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, MaxNLocator
from pyproj import Transformer

INK = "0.15"           # overlay lines, scale bar, north arrow


def setup():
    """rcParams for the maps: thin, legible hatching at 300 dpi."""
    mpl.rcParams.update({"hatch.linewidth": 0.45, "savefig.dpi": 300, "legend.handleheight": 1.4,
                         "legend.handlelength": 2.0})


def hatch_color(facecolor):
    """Dark hatch on light fills, white hatch on dark fills."""
    r, g, b = to_rgb(facecolor)
    return "white" if 0.299 * r + 0.587 * g + 0.114 * b < 0.45 else "0.1"


def plot_categories(ax, gdf, labels, styles, *, hatch_repeat=1, alpha=0.92, edgecolor="white", linewidth=0.0):
    """One layer per category of ``styles`` (label -> (facecolor, hatch)); every unit is drawn.
    ``hatch_repeat`` doubles / triples the hatch density (small polygons, e.g. census tracts)."""
    labels = np.asarray(labels)
    for lab, (fc, h) in styles.items():
        m = labels == lab
        if m.any():
            gdf[m].plot(ax=ax, facecolor=fc, hatch=h * hatch_repeat if h else None,
                        edgecolor=hatch_color(fc), linewidth=0, alpha=alpha, zorder=2)
    if linewidth:
        gdf.boundary.plot(ax=ax, color=edgecolor, linewidth=linewidth, zorder=3)


def category_legend(ax, groups, *, counts=None, loc="upper center", bbox=(0.5, -0.06), fontsize=7, title=None):
    """Legend on ``ax`` (an Axes or a Figure) with one column per group (``{"Hot spots": [...], ...}``),
    group names in bold. Items are (label, facecolor, hatch); ``counts`` maps label -> text shown in ()."""
    n = max(len(v) for v in groups.values())
    handles, texts, bold = [], [], []
    for name, items in groups.items():
        bold.append(len(texts))
        handles.append(Patch(visible=False)); texts.append(name)
        for lab, fc, h in items:
            handles.append(Patch(facecolor=fc, hatch=h, edgecolor=hatch_color(fc), linewidth=0.3))
            texts.append(f"{lab} ({counts[lab]})" if counts is not None and lab in counts else lab)
        for _ in range(n - len(items)):
            handles.append(Patch(visible=False)); texts.append("")
    leg = ax.legend(handles, texts, loc=loc, bbox_to_anchor=bbox, ncol=len(groups), fontsize=fontsize,
                    frameon=False, title=title, title_fontsize=fontsize + 0.5, columnspacing=1.2)
    for i in bold:
        leg.get_texts()[i].set_fontweight("bold")
    return leg


def add_basemap(ax, crs, zoom="auto", *, strict=False):
    """Esri World Light Gray Canvas tiles under the data; drawn without tiles if offline."""
    try:
        import contextily as cx
        cx.add_basemap(ax, crs=crs, source=cx.providers.Esri.WorldGrayCanvas, zoom=zoom,
                       attribution_size=5, zorder=0)
    except Exception as exc:  # noqa: BLE001 - no network / provider refused
        if strict:
            raise RuntimeError("Requested publication basemap could not be loaded") from exc
        print(f"basemap unavailable ({str(exc)[:80]}); map drawn without tiles")


def add_overlay(ax, gdf, color=INK, linewidth=0.4):
    """Boundary lines of another layer drawn on top of the map."""
    gdf.boundary.plot(ax=ax, color=color, linewidth=linewidth, zorder=6)


def graticule(ax, crs, nticks=4, fontsize=6):
    """Lat / lon labels on the frame of a projected map (near-rectangular graticule at city scale)."""
    tr = Transformer.from_crs(crs, 4326, always_xy=True)
    xmid, ymid = sum(ax.get_xlim()) / 2, sum(ax.get_ylim()) / 2
    deg = lambda v, h: f"{abs(v):.2f}\N{DEGREE SIGN}{h[int(v < 0)]}"
    ax.set_axis_on()
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: deg(tr.transform(x, ymid)[0], "EW")))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: deg(tr.transform(xmid, y)[1], "NS")))
    ax.xaxis.set_major_locator(MaxNLocator(nticks))
    ax.yaxis.set_major_locator(MaxNLocator(nticks))
    ax.tick_params(top=True, right=True, labelsize=fontsize, length=2.5, width=0.5, direction="in")
    ax.tick_params(axis="y", labelrotation=90)
    for sp in ax.spines.values():
        sp.set_visible(True); sp.set_linewidth(0.6)
    ax.grid(False)


def _nice(v):
    e = math.floor(math.log10(v)); b = v / 10 ** e
    return (5 if b >= 5 else 2.5 if b >= 2.5 else 2 if b >= 2 else 1) * 10 ** e


def add_scalebar(ax, segments=4, fraction=0.35, loc="lower right", margin=0.04, fontsize=6):
    """Alternating (stepped) cartographic scale bar labelled 0 2.5 5 ... km; map units in metres."""
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    step = _nice((x1 - x0) * fraction / segments)
    x = x0 + margin * (x1 - x0) if loc == "lower left" else x1 - margin * (x1 - x0) - segments * step - 0.05 * (x1 - x0)
    y, h = y0 + margin * (y1 - y0), 0.014 * (y1 - y0)
    kw = dict(color=INK, lw=0.8, solid_capstyle="butt", zorder=12)
    for k in range(segments + 1):
        ax.plot([x + k * step] * 2, [y, y + h], **kw)
        if k < segments:
            yy = y + h if k % 2 == 0 else y
            ax.plot([x + k * step, x + (k + 1) * step], [yy, yy], **kw)
        ax.text(x + k * step, y + 1.5 * h, f"{k * step / 1000:g}", ha="center", va="bottom", fontsize=fontsize, zorder=12)
    ax.annotate(" km", xy=(x + segments * step, y + 1.5 * h), xytext=(4, 0), textcoords="offset points",
                ha="left", va="bottom", fontsize=fontsize, zorder=12)
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1)


def add_north_arrow(ax, xy=(0.95, 0.95), fontsize=8):
    x, y = xy
    ax.annotate("", xy=(x, y), xytext=(x, y - 0.07), xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=0.9), zorder=12)
    ax.text(x, y + 0.008, "N", transform=ax.transAxes, ha="center", va="bottom", fontsize=fontsize, zorder=12)


def decorate(ax, crs, *, overlay=None, basemap=True, scalebar=True, north=True, grid=True, zoom="auto", basemap_strict=False):
    """All of the above, in order, after the data layer has been drawn."""
    ax.set_aspect("equal")
    if basemap:
        add_basemap(ax, crs, zoom=zoom, strict=basemap_strict)
    if overlay is not None:
        add_overlay(ax, overlay)
    if grid:
        graticule(ax, crs)
    else:
        ax.set_axis_off()
    if scalebar:
        add_scalebar(ax)
    if north:
        add_north_arrow(ax)
