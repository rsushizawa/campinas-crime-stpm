"""Core: configuration and the warehouse loader's container.

No I/O and no heavy dependencies beyond pandas/geopandas — ``crime.data``
depends on this subpackage, never the reverse.

    config     paths, CRS constants, ``DBConfig``, ``Settings``, ``engine``
    metadata   ``DatasetMeta`` — what was loaded (support, years, crime filter, source)
    dataset    ``Dataset`` — gdf + events + overlay + header (returned by ``load_sectors``)
"""
from crime.core.config import DBConfig, Settings
from crime.core.dataset import Dataset
from crime.core.metadata import DatasetMeta

__all__ = ["DBConfig", "Settings", "Dataset", "DatasetMeta"]
