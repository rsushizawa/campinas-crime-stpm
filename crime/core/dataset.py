"""The analysis ``Dataset`` — one container, one header.

A ``Dataset`` is the single input to every analysis function (the mrlib
``Dataset`` idea: data + header travel together):

    gdf      one row per spatial unit (sector | grid | segment), keyed by
             ``id_col`` with the analysed quantity in ``value_col``
    events   optional per-crime rows (``unit_id``, ``data_ocorrencia`` ...)
             — needed by the space-time cube and network KDE
    overlay  optional boundary polygons drawn on maps
    meta     :class:`~crime.core.metadata.DatasetMeta` — support, years,
             crime filter, CRS, source

The container is **frozen**: derive a modified copy with :meth:`replace`
instead of assigning attributes, so the header cannot drift from the fields
it describes. The frames themselves are not copied (that would double memory
on every call) — treat ``gdf`` / ``events`` / ``overlay`` as read-only; every
analysis function in this library works on copies.

Construction is I/O-free; loaders live in :mod:`crime.data`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace as _replace

import geopandas as gpd
import pandas as pd

from crime.core.config import CRS_METRIC
from crime.core.metadata import DatasetMeta


@dataclass(frozen=True, eq=False)
class Dataset:
    """One row per spatial unit in ``gdf`` (id_col='unit_id', value_col='crime_count').

    ``Dataset(gdf, "sector", years=(2022, 2025), events=ev)`` keeps working;
    the header is built from ``unit``/``years``/``crs_metric`` when ``meta`` is
    not given, and must agree with them when it is.
    """

    gdf: gpd.GeoDataFrame
    unit: str                                   # "sector" | "grid" | "segment"
    id_col: str = "unit_id"
    value_col: str = "crime_count"
    crs_metric: str = CRS_METRIC
    years: tuple[int, int] | None = None        # crime year span this dataset covers
    events: pd.DataFrame | None = field(default=None, repr=False)
    overlay: gpd.GeoDataFrame | None = field(default=None, repr=False)
    meta: DatasetMeta | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.meta is None:
            object.__setattr__(self, "meta", DatasetMeta(
                unit=self.unit, years=self.years, crs_metric=self.crs_metric))
        elif (self.meta.unit, self.meta.years, self.meta.crs_metric) != (
                self.unit, tuple(self.years) if self.years else None, self.crs_metric):
            raise ValueError(f"Dataset fields disagree with its header: {self.meta}")

    # ------------------------------------------------------------------ views
    def metric(self) -> gpd.GeoDataFrame:
        """``gdf`` reprojected to the metric CRS (for area / distance / weights)."""
        return self.gdf.to_crs(self.crs_metric)

    def replace(self, **changes) -> "Dataset":
        """A copy with some fields changed (``ds.replace(events=None)``).
        The header follows ``unit``/``years``/``crs_metric`` changes."""
        if {"unit", "years", "crs_metric"} & changes.keys() and "meta" not in changes:
            changes["meta"] = _replace(self.meta, **{k: changes[k] for k in ("unit", "years", "crs_metric")
                                                     if k in changes})
        return _replace(self, **changes)

    def describe(self) -> str:
        n_ev = "no events" if self.events is None else f"{len(self.events)} events"
        return f"Dataset({self.meta.describe()}; {len(self.gdf)} units, {n_ev})"
