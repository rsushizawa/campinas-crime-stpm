"""Publication plot defaults — colorful, thin black boundaries, 300 dpi.

Category palettes give every class its own hue: LISA quadrants use
red/orange vs. blue/cyan. EHSA follows the ESRI article convention — hot
categories on a red ramp, cold categories on a blue ramp — with hatch
patterns (ehsa_hatches) encoding the temporal pattern so same-family
classes stay distinguishable.

Inputs: any field can be overridden at construction (e.g. PlotStyle(cmap="magma")).
Output: passed to every plot function (``style=``); apply() sets the matplotlib rcParams.
"""
from dataclasses import dataclass, field

import matplotlib as mpl


def _lisa_palette() -> dict:
    return {"HH": "#d7191c", "LL": "#2c7bb6", "HL": "#e08214",
            "LH": "#41b6c4", "ns": "#f0f0f0"}


def _hotspot_palette() -> dict:
    return {"hotspot": "#d7191c", "coldspot": "#2c7bb6", "ns": "#f0f0f0"}


def _ehsa_palette() -> dict:
    return {
        "new hotspot": "#e31a1c", "consecutive hotspot": "#fb6a4a",
        "intensifying hotspot": "#a50f15", "persistent hotspot": "#67000d",
        "diminishing hotspot": "#fcae91", "sporadic hotspot": "#fee0d2",
        "oscillating hotspot": "#de2d26", "historical hotspot": "#fee8c8",
        "new coldspot": "#2171b5", "consecutive coldspot": "#6baed6",
        "intensifying coldspot": "#08519c", "persistent coldspot": "#08306b",
        "diminishing coldspot": "#9ecae1", "sporadic coldspot": "#c6dbef",
        "oscillating coldspot": "#4292c6", "historical coldspot": "#eff3ff",
        "no pattern": "#d9d9d9",
        "no data": "#efefef",
    }


def _ehsa_hatches() -> dict:
    per = {"new": "", "consecutive": "//", "intensifying": "xx",
           "persistent": "", "diminishing": "\\\\", "sporadic": "..",
           "oscillating": "oo", "historical": ""}
    hatches = {f"{p} {family}": h for p, h in per.items()
               for family in ("hotspot", "coldspot")}
    hatches["no pattern"] = ""
    hatches["no data"] = "///"
    return hatches


def _gi_bin_palette() -> dict:
    return {"hot 99%": "#b30000", "hot 95%": "#e34a33", "hot 90%": "#fc8d59",
            "cold 90%": "#74a9cf", "cold 95%": "#2b8cbe", "cold 99%": "#045a8d",
            "ns": "#d9d9d9"}


@dataclass(frozen=True)
class PlotStyle:
    figsize: tuple[float, float] = (8.0, 8.0)
    dpi: int = 150
    save_dpi: int = 300
    cmap: str = "viridis"
    cmap_diverging: str = "RdBu_r"
    bar_color: str = "#4C6DAF"
    line_color: str = "#2c5f9e"
    edge_color: str = "white"
    edge_width: float = 0.2
    boundary_color: str = "black"
    boundary_width: float = 0.8
    font_size: int = 10
    title_size: int = 12
    legend_loc: str = "lower right"
    lisa_palette: dict = field(default_factory=_lisa_palette)
    hotspot_palette: dict = field(default_factory=_hotspot_palette)
    ehsa_palette: dict = field(default_factory=_ehsa_palette)
    ehsa_hatches: dict = field(default_factory=_ehsa_hatches)
    gi_bin_palette: dict = field(default_factory=_gi_bin_palette)

    def apply(self) -> None:
        mpl.rcParams.update({
            "figure.dpi": self.dpi,
            "savefig.dpi": self.save_dpi,
            "font.size": self.font_size,
            "axes.titlesize": self.title_size,
            "font.family": "serif",
            "hatch.linewidth": 0.4,
            "axes.spines.top": False,
            "axes.spines.right": False,
        })
