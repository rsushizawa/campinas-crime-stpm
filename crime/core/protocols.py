"""The library's extension points, as structural ``Protocol`` types.

Each protocol names a seam where a caller may inject its own implementation
instead of the default. Nothing here imports heavy dependencies.

=================  ===========================================  ==========================
Protocol           Default implementation                       Injected into
=================  ===========================================  ==========================
DataSource         :class:`crime.data.postgis.PostGISSource`    loaders, ``DatasetSpec``
WeightsBuilder     :func:`crime.esri.weights.spatial_weights`   every ESRI statistic
TrendTest          :func:`crime.esri.trend.mann_kendall`        ``emerging_hotspots``
=================  ===========================================  ==========================
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np
import pandas as pd


@runtime_checkable
class DataSource(Protocol):
    """Anything that can answer the loaders' queries (PostGIS, a parquet
    snapshot, a test fixture)."""

    def unit_features(self, unit: str): ...                       # GeoDataFrame, one row per unit
    def unit_counts(self, unit: str, query) -> pd.DataFrame: ...   # unit_id, crime_count
    def unit_events(self, unit: str, query) -> pd.DataFrame: ...   # per-crime rows with unit_id
    def overlay(self): ...                                         # boundary polygons


class WeightsBuilder(Protocol):
    """``(gdf) -> libpysal W`` — a spatial neighbourhood definition."""

    def __call__(self, gdf) -> Any: ...


class TrendTest(Protocol):
    """``(series) -> (z, p)`` — a monotonic-trend test on one unit's time series."""

    def __call__(self, values: np.ndarray) -> tuple[float, float]: ...
