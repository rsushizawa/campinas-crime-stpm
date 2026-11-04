"""campinas-crime-stpm — data layer for the space-time analysis of crime in Campinas (SP).

The analysis lives in ``notebooks/``: each notebook calls the statistics
libraries directly (libpysal, esda, pointpats, pymannkendall, statsmodels,
scipy, scikit-learn, tobler) and draws with matplotlib / geopandas. This
package only acquires, cleans, validates and serves the data::

    from crime.data import load_points, load_units, unit_counts

    pts = load_points("property")              # bulletins as points, EPSG:31983
    tracts = load_units("tract")               # 2,592 IBGE 2022 tracts + census attributes
    y = unit_counts("utb", "all", freq="M")    # 93 UTBs x 48 months, zero-filled

Subpackages: ``core`` (config, ``Dataset`` header) · ``data`` (the notebook
API, cleaning, units, the PostGIS warehouse readers). Every name below is
importable from the top level and loads **on first use**, so ``import crime``
stays light.
"""
from __future__ import annotations

import importlib

from crime.core.config import __version__ as __version__

#: public name -> defining module (the facade's single source of truth)
_EXPORTS: dict[str, str] = {}


def _export(module: str, *names: str) -> None:
    for n in names:
        _EXPORTS[n] = module


# ---- core: configuration and the warehouse container
_export("crime.core.config", "CRS_METRIC", "CRS_WGS84", "DEMOGRAPHIC_YEAR",
        "PLACE_CAMPINAS", "NOTEBOOK_OUTPUTS_DIR", "DBConfig", "Settings", "engine")
_export("crime.core.dataset", "Dataset")
_export("crime.core.metadata", "DatasetMeta")
# ---- data: the notebook API (parquet-backed, no database)
_export("crime.data.api", "GROUPS", "load_points", "load_units", "unit_counts",
        "cnefe_poi_points", "unit_poi_counts")
_export("crime.data.units", "assign_points", "assign_nearest", "areal_interpolate")
# ---- data: PostGIS warehouse readers (db extra)
_export("crime.data.loaders", "load_sectors", "load_crime_points", "load_cnefe_points", "crime_types")
_export("crime.data.query", "CrimeQuery")
_export("crime.data.postgis", "PostGISSource")
_export("crime.data.catalog", "DEFAULT_FEATURES")
_export("crime.data.provenance", "provenance", "write_provenance")

__all__ = sorted(_EXPORTS)
_SUBPACKAGES = {"core", "data"}


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
