"""Data access: the request model and the warehouse reader.

    from crime.data import CrimeQuery, Warehouse, SPATIAL_GROUPS, TEMPORAL_GROUPS

    wh = Warehouse()
    wh.counts(CrimeQuery(crime_group="property", time_unit="quarter"))   # tract x quarter, long
    wh.census_tracts()                                                    # tracts + 2022 attributes
    wh.bulletins(CrimeQuery(crime_group="drug"))                          # one row per bulletin

Modules

    query       :class:`CrimeQuery` (pydantic): which bulletins, which spatial and time unit
    warehouse   :class:`Warehouse`: SQL against the PostGIS warehouse, frames in EPSG:31983
"""
from crime.data.query import SPATIAL_GROUPS, TEMPORAL_GROUPS, CrimeQuery
from crime.data.warehouse import Warehouse, WarehouseNotRunning, WarehouseVersionError

__all__ = ["CrimeQuery", "SPATIAL_GROUPS", "TEMPORAL_GROUPS", "Warehouse", "WarehouseNotRunning",
           "WarehouseVersionError"]
