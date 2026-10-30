"""Declarative configuration of the core pipeline (``run_core.py``).

Every value below is a **default the authors may change**. Values marked
"project choice" are decisions of this project, not fixed by a cited method or
by the Esri tool being mirrored; values marked "Esri default" follow the
ArcGIS Pro documentation of the tool named in ``docs/METHODS.md``.
"""
from __future__ import annotations

# ---------------------------------------------------------------- data -------
YEARS = (2022, 2025)            # project choice: study period (occurrence date, inclusive)
SEED = 42                       # project choice: one seed for every random draw

# crime groups analysed in space (etl/taxonomy.py CRIME_GROUPS); "all" = every group.
GROUPS = ("all", "property", "bodily_harm", "traffic", "drug", "violent")   # project choice
# groups with no published locations (0 % geocoded): temporal step only.
TEMPORAL_ONLY_GROUPS = ("sexual",)                                          # project choice

# ---------------------------------------------------------------- supports ---
# name -> crime.data.units.load_units arguments. Areas of the regular cells are project choices.
SUPPORTS = {
    "tract": {"kind": "tract"},                          # IBGE 2022 census tracts
    "utb": {"kind": "utb"},                              # Campinas UTB planning units
    "hex0.5": {"kind": "hexagon", "area_km2": 0.5},      # project choice
    "hex0.1": {"kind": "hexagon", "area_km2": 0.1},      # project choice
    "sq0.5": {"kind": "square", "area_km2": 0.5},        # project choice
}

# ---------------------------------------------------------------- weights ----
WEIGHTS = ("queen", "rook", "knn")   # project choice: the three neighbourhoods compared
KNN_K = 5                            # project choice: = median queen neighbour count of tracts (logged)
PRIMARY_WEIGHTS = "queen"            # project choice: the headline neighbourhood

# ---------------------------------------------------------------- inference --
ALPHA = 0.05                 # project choice (conventional)
FDR = True                   # project choice: Benjamini–Hochberg on every family of local tests
LISA_PERMUTATIONS = 499      # Esri default (Cluster and Outlier Analysis)
MORAN_PERMUTATIONS = 999     # project choice (Esri reports the analytic z; both are written)

# ---------------------------------------------------------------- when -------
STL = {"period": 12, "robust": True}    # project choice: monthly series, annual cycle, robust loess

# ---------------------------------------------------------------- how it changes
TIME_UNITS = {"quarter": "QE", "month": "ME"}   # project choice: pandas offset aliases
PRIMARY_TIME_UNIT = "quarter"                   # project choice
EHSA = {
    "neighbourhood": "spacetime",     # Esri-style space-time neighbourhood
    "time_step": 1,                   # Esri default "Neighborhood Time Step" = 1
    "temporal_direction": "backward",
    "trend_method": "hamed_rao",      # project choice (Esri uses Mann-Kendall; see METHODS.md)
    "hot_share": 0.9,                 # Esri rule: 90 % of time steps
}

# ---------------------------------------------------------------- clustering -
TSC = {
    "methods": ("profile", "value"),  # Esri characteristics "profile (correlation)" and "value"
    "time_unit": "month",             # project choice: cube used for clustering
    "k_range": (2, 10),               # Esri: k by pseudo-F when not given
    "min_total": 1,                   # project choice: units with >= 1 event are clustered
}

# ---------------------------------------------------------------- MAUP -------
MAUP_REFERENCE = "tract"   # project choice: other supports are overlaid onto the tracts

# ---------------------------------------------------------------- points -----
POINTS = {
    "distances_m": tuple(range(100, 3001, 100)),   # project choice
    "n_simulations": 99,                           # project choice (Esri offers 9/99/999)
    "sample": 20_000,                              # project choice: Ripley subsample size
    "kde_kernel": "quartic",                       # Esri Kernel Density kernel
    "kde_cell_m": 100,                             # project choice
}

# ---------------------------------------------------------------- Knox -------
KNOX = {
    "space_bands_m": (100, 200, 400, 800),   # project choice
    "time_bands_days": (7, 14, 30, 60),      # project choice
    "permutations": 999,                     # project choice
    "max_events": 40_000,                    # project choice: larger groups are sampled to this
}

# ---------------------------------------------------------------- association
ASSOCIATION = {
    "weights": "queen",                       # project choice
    "permutations": 999,                      # project choice
    # crime-count periods: the full study period and the census year (crime.core.config.DEMOGRAPHIC_YEAR)
    "crime_years": ((2022, 2025), (2022, 2022)),     # project choice
    "features_all_supports": ("pop_total", "n_commercial", "n_education", "n_health", "n_religious"),
    "features_tract_only": ("income_head_mean", "literacy_rate"),
    # population on non-tract supports: tract pop_total split by area share (Goodchild & Lam 1980)
    "population_interpolation": "area_share",  # project choice
    "local_support": "tract",                  # project choice
    "local_feature": "n_commercial",           # local bivariate Moran: crime_count x lag(n_commercial)
}

# ---------------------------------------------------------------- CLI --------
QUICK = {"groups": ("property",), "supports": ("tract",)}   # --quick: one group, tract only
STEPS = ("when", "where", "change", "tsc", "maup", "points", "knox", "assoc")


def as_dict() -> dict:
    """The configuration as a JSON-serialisable dict (for the run manifest)."""
    out = {}
    for k, v in globals().items():
        if k.isupper():
            out[k] = v
    import json

    return json.loads(json.dumps(out, default=list))
