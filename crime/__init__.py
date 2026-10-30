"""IC-Crime — classical spatio-temporal crime analysis for Campinas.

ArcGIS-Pro "Space Time Pattern Mining" in Python, plus a GeoShapley
explanation of *why* crime concentrates where it does. Typical use::

    import crime

    ds = crime.DatasetSpec().years(2022, 2025).crime(group="property").with_events().load()
    ehsa = crime.emerging_hotspots(ds, freq="ME", weights="queen")
    ehsa.summary()
    fig, ax = crime.ehsa_map(ehsa, ds, overlay=True)

The method, in the order the analysis runs
------------------------------------------
0. **Unit of analysis** — ``crime.data``: load a :class:`Dataset` (sector, grid
   or street segment) whose header records the support and crime filter.
1. **Is crime clustered at all?** — ``crime.esri.moran``: global Moran's I.
2. **Where are the clusters?** — ``crime.esri.local``: Getis-Ord Gi* hot/cold
   spots and Anselin's local Moran (LISA), with Benjamini-Hochberg FDR
   (``crime.esri.inference``).
3. **How do they evolve?** — ``crime.esri.cube`` builds the space-time cube;
   ``crime.esri.ehsa`` runs Gi* per time slice + a Mann-Kendall trend
   (``crime.esri.trend``) → the ESRI Emerging Hot Spot categories;
   ``crime.esri.stlisa`` and ``crime.esri.tsclust`` are the LISA and
   time-series-clustering counterparts.
4. **On the street network** — ``crime.esri.nkde``: network KDE / temporal NKDE.
5. **Robustness** — ``weights_sensitivity``, ``crime.esri.maup``
   (support sensitivity), ``crime.stats.validation`` (agreement metrics).
6. **Why here?** — ``crime.geoshapley``: a cross-sectional model of a target
   (case-control presence, EHSA trend ...) explained with GeoShapley.
7. **Show it** — ``crime.viz``: maps, charts, 3-D cubes. Viz only draws results.

Subpackages: ``core`` (containers, metadata, config, protocols) · ``data``
(I/O) · ``esri`` · ``stats`` · ``geoshapley`` · ``viz``.

Every name below is importable from the top level; submodules load **on first
use**, so ``import crime`` stays light (no matplotlib / sklearn / Earth Engine).
"""
from __future__ import annotations

import importlib

from crime.core.config import __version__ as __version__

#: public name -> defining module (the facade's single source of truth)
_EXPORTS: dict[str, str] = {}


def _export(module: str, *names: str) -> None:
    for n in names:
        _EXPORTS[n] = module


# ---- core: containers, metadata, configuration
_export("crime.core.config", "CRS_METRIC", "CRS_WGS84", "DEMOGRAPHIC_YEAR", "MODELS_DIR",
        "PLACE_CAMPINAS", "RESULTS_DIR", "DBConfig", "Settings", "engine")
_export("crime.core.dataset", "Dataset")
_export("crime.core.metadata", "DatasetMeta", "ResultMeta")
_export("crime.core.cube", "SpaceTimeCube", "CubeResult")
# ---- data: loading, caching, provenance
_export("crime.data.loaders", "load_sectors", "load_grid", "load_crime_points",
        "load_cnefe_points", "crime_types")
_export("crime.data.segments", "load_segments", "snap_events")
_export("crime.data.osm", "street_graph", "street_segments")
_export("crime.data.spec", "DatasetSpec")
_export("crime.data.query", "CrimeQuery")
_export("crime.data.postgis", "PostGISSource")
_export("crime.data.catalog", "DEFAULT_FEATURES")
_export("crime.data.artifacts", "save_result", "load_result", "cached")
_export("crime.data.provenance", "provenance", "write_provenance")
# ---- esri: classical space-time pattern mining
_export("crime.esri.weights", "spatial_weights", "network_weights", "space_time_weights")
_export("crime.esri.inference", "benjamini_hochberg", "fdr")
_export("crime.esri.moran", "global_moran", "MoranResult")
_export("crime.esri.local", "local_moran", "getis_ord_gi", "weights_sensitivity",
        "LisaResult", "GiStarResult")
_export("crime.esri.cube", "space_time_cube")
_export("crime.esri.trend", "mann_kendall")
_export("crime.esri.ehsa", "emerging_hotspots", "gi_time_series", "gi_space_time", "EhsaResult")
_export("crime.esri.stlisa", "space_time_lisa", "SpaceTimeLisaResult")
_export("crime.esri.tsclust", "time_series_clustering", "TSClusterResult")
_export("crime.esri.nkde", "segment_graph", "nkde", "tnkde", "NkdeResult", "TnkdeResult",
        "segment_structure", "corridor_table")
_export("crime.esri.maup", "support_sensitivity")
# ---- stats: descriptive, correlation, validation
_export("crime.stats.eda", "descriptive_stats", "temporal_trends", "DescriptiveResult", "TrendResult")
_export("crime.stats.correlation", "feature_correlation", "crime_crime_correlation",
        "feature_collinearity", "vif_table", "CorrelationResult", "CollinearityResult")
_export("crime.stats.validation", "prediction_agreement")
# ---- geoshapley: cross-sectional model + explanation
_export("crime.geoshapley.pipeline", "run_prediction_pipeline", "PredictionResult", "PredictionPipeline")
_export("crime.geoshapley.casecontrol", "run_geoshapley", "GeoShapleyResult")
_export("crime.geoshapley.trend", "run_trend_analysis")
_export("crime.geoshapley.rtm", "fit_risk_terrain", "RTMResult")
_export("crime.geoshapley.holdout", "run_spatial_holdout", "SpatialHoldoutResult")
# ---- viz
_export("crime.viz.style", "PlotStyle")
_export("crime.viz.classify", "classify", "bin_index")
_export("crime.viz.frame", "map_axes", "map_frame", "boundary_overlay")
_export("crime.viz.basemap", "add_basemap")
_export("crime.viz.maps", "DEFAULT_BASEMAP", "bivariate_choropleth", "choropleth_map", "ehsa_map",
        "grid_heatmap", "history_map", "hotspot_map", "interactive_map", "interactive_segment_map",
        "lisa_map", "persistence_map", "risk_map", "segment_ehsa_map", "trend_map")
_export("crime.viz.charts", "bar_chart", "clustered_heatmap", "cluster_profiles",
        "correlation_heatmap", "cube_profiles", "emergence_curve", "emergence_timeline",
        "moran_scatter", "seasonal_plot", "time_series")
_export("crime.viz.cubes", "ehsa_slice_maps", "ehsa_transition_sankey", "interactive_cube",
        "interactive_ehsa_cube", "interactive_lisa_cube", "interactive_slice_map",
        "space_time_cube_3d", "space_time_lisa_cube")
_export("crime.viz.imagery", "ee_authenticate", "region_history_map")

__all__ = sorted(_EXPORTS)
_SUBPACKAGES = {"core", "data", "esri", "stats", "geoshapley", "viz"}


def __getattr__(name: str):
    if name in _EXPORTS:
        value = getattr(importlib.import_module(_EXPORTS[name]), name)
        globals()[name] = value          # cache: later lookups skip __getattr__
        return value
    if name in _SUBPACKAGES:
        return importlib.import_module(f"crime.{name}")
    raise AttributeError(f"module 'crime' has no attribute {name!r}")


def __dir__():
    return sorted({*globals(), *_EXPORTS, *_SUBPACKAGES})
