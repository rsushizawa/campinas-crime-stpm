"""Data: every read from and write to the outside world.

**The notebook API** (:mod:`crime.data.api`; full contract in its docstring)::

    load_points(group="all")                 -> GeoDataFrame, one row per geocoded-in-tract bulletin
    load_units(support)                      -> GeoDataFrame of "tract" (2,592) | "utb" (93) units
    unit_counts(support, group="all", freq=None)
                                             -> Series unit -> count | DataFrame unit x period ("M"/"Q"/"Y")
    cnefe_poi_points()                       -> GeoDataFrame of CNEFE 2022 POI addresses
    unit_poi_counts(support)                 -> DataFrame unit x POI type
    GROUPS                                   -> ("all", "property", "bodily_harm", "traffic", "drug", "violent")

All frames are in EPSG:31983 (SIRGAS 2000 / UTM 23S). No database is needed.

Other modules

    units      tract / UTB polygons, ``assign_points``, ``assign_nearest``, ``areal_interpolate``
    cleaning   raw-file cleaning: occurrence-date window, tract join, IBGE 2022 income,
               literacy, CNEFE POIs by point-in-polygon
    catalog    ``DEFAULT_FEATURES`` and the crime-slug readiness scopes
    provenance run stamps (versions, git commit; DB target when a DB is used)
    query      ``CrimeQuery`` — the crime filter and its SQL ``WHERE`` clause (warehouse)
    postgis    ``PostGISSource`` — reads the PostGIS warehouse (``db`` extra)
    loaders    ``load_sectors`` / ``load_crime_points`` / ... over the warehouse

The API names are imported on first use, so ``import crime.data`` stays light.
"""
from __future__ import annotations

import importlib

_API = ("load_points", "load_units", "unit_counts", "cnefe_poi_points", "unit_poi_counts",
        "points_from_bulletins", "GROUPS")

__all__ = list(_API)


def __getattr__(name: str):
    if name in _API:
        value = getattr(importlib.import_module("crime.data.api"), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'crime.data' has no attribute {name!r}")


def __dir__():
    return sorted({*globals(), *_API})
