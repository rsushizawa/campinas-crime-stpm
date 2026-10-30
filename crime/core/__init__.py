"""Core: data containers, their metadata headers, configuration and protocols.

No I/O and no heavy dependencies beyond pandas/geopandas — every other
subpackage depends on this one, never the reverse.

    config     paths, CRS constants, ``DBConfig``, ``Settings``, ``engine``
    metadata   ``DatasetMeta`` (what was loaded) · ``ResultMeta`` (how a result was made)
    dataset    ``Dataset`` — gdf + events + overlay + header
    cube       ``SpaceTimeCube`` / ``CubeResult`` — unit x time layers
    results    ``LocalStatResult`` protocol, ``family`` / ``jaccard``
    protocols  the injectable extension points
"""
from crime.core.config import DBConfig, Settings
from crime.core.cube import CubeResult, SpaceTimeCube
from crime.core.dataset import Dataset
from crime.core.metadata import DatasetMeta, ResultMeta

__all__ = ["DBConfig", "Settings", "Dataset", "DatasetMeta", "ResultMeta",
           "SpaceTimeCube", "CubeResult"]
