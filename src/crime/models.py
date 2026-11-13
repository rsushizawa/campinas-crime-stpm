"""Shared dataclasses defining the data exchanged between package modules.

CRS, time bins and source provenance travel with each dataset and result.
Large tables stay as pandas/GeoPandas objects rather than copied row objects.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from crime.config import CRS_METRIC, DATE_END, DATE_START, REPO_ROOT, WarehouseConfig
from crime.errors import ConfigurationError
from crime.query import CrimeQuery

if TYPE_CHECKING:
    import geopandas as gpd
    import numpy as np
    import pandas as pd


@dataclass(frozen=True)
class StudyConfig:
    """Study extent and working directories; no I/O occurs on construction."""

    municipality: str = '3509502'
    start: dt.date = dt.date.fromisoformat(DATE_START)
    end: dt.date = dt.date.fromisoformat(DATE_END)
    crs: str = CRS_METRIC
    project_root: Path = REPO_ROOT

    def __post_init__(self):
        if len(self.municipality) != 7 or not self.municipality.isdigit():
            raise ConfigurationError('Municipality must be a seven-digit IBGE code')
        if self.start > self.end:
            raise ConfigurationError('Study start must precede its end')
        from pyproj import CRS
        CRS.from_user_input(self.crs)


@dataclass(frozen=True)
class SourceMetadata:
    """Identity and coverage of one source used to build a dataset."""

    name: str
    location: str
    sha256: str
    retrieved_at: dt.datetime | None = None
    coverage_start: dt.date | None = None
    coverage_end: dt.date | None = None


@dataclass(frozen=True)
class TreatmentReport:
    """One treatment's action, affected rows and explanatory evidence."""

    step: str
    rule: str
    action: Literal['fail', 'fix', 'exclude', 'report']
    rows_in: int
    rows_out: int
    affected: int
    note: str = ''


@dataclass
class StepResult:
    """Processed data, rejected records, reports and named intermediate tables."""

    kept: Any
    rejects: pd.DataFrame
    report: list[TreatmentReport]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CrimeDataset:
    """Treated bulletin, tract and POI tables in a common projected CRS."""

    bulletins: gpd.GeoDataFrame
    tracts: gpd.GeoDataFrame
    poi: gpd.GeoDataFrame
    config: StudyConfig = field(default_factory=StudyConfig)
    sources: tuple[SourceMetadata, ...] = ()
    reports: list[TreatmentReport] = field(default_factory=list)
    rejects: pd.DataFrame | None = None

    def __post_init__(self):
        from pyproj import CRS
        expected = CRS.from_user_input(self.config.crs)
        for name, table in [('bulletins', self.bulletins), ('tracts', self.tracts), ('poi', self.poi)]:
            if table.crs is None or CRS.from_user_input(table.crs) != expected:
                raise ConfigurationError(f'{name} CRS must equal {expected}')
        ids = self.tracts['census_tract_id']
        if ids.isna().any() or ids.duplicated().any():
            raise ConfigurationError('Tract IDs must be unique and present')
        for name, table in [('bulletins', self.bulletins), ('poi', self.poi)]:
            assigned = table['census_tract_id'].dropna()
            if not assigned.isin(ids).all():
                raise ConfigurationError(f'{name} references a tract absent from the dataset')


@dataclass(frozen=True)
class SpaceTimeCube:
    """Counts indexed by ordered unit IDs (rows) and bin starts (columns)."""

    counts: np.ndarray
    unit_ids: tuple[str, ...]
    periods: pd.DatetimeIndex
    time_unit: Literal['month', 'quarter', 'year']
    crime_group: str = 'all'
    crs: str = CRS_METRIC
    sources: tuple[SourceMetadata, ...] = ()

    def __post_init__(self):
        import numpy as np
        if self.counts.shape != (len(self.unit_ids), len(self.periods)):
            raise ConfigurationError('Cube dimensions must match unit IDs and periods')
        if len(set(self.unit_ids)) != len(self.unit_ids):
            raise ConfigurationError('Cube unit IDs must be unique')
        if self.periods.hasnans or self.periods.has_duplicates or not self.periods.is_monotonic_increasing:
            raise ConfigurationError('Cube periods must be present, unique and ordered')
        if not np.isfinite(self.counts).all() or (self.counts < 0).any() or (self.counts % 1 != 0).any():
            raise ConfigurationError('Cube counts must be finite nonnegative integers')


@dataclass(frozen=True)
class AnalysisConfig:
    """Explicit settings recorded with each statistical result."""

    weights: Literal['queen', 'rook', 'knn5'] = 'queen'
    permutations: int = 499
    seed: int = 20221
    alpha: float = 0.05
    correction: Literal['fdr_bh', 'none'] = 'fdr_bh'

    def __post_init__(self):
        if not 0 < self.alpha < 1 or self.permutations < 0:
            raise ConfigurationError('Require 0 < alpha < 1 and permutations >= 0')


@dataclass
class AnalysisResult:
    """Named result tables with the method and data provenance needed for export."""

    method: str
    tables: dict[str, pd.DataFrame]
    config: AnalysisConfig = field(default_factory=AnalysisConfig)
    sources: tuple[SourceMetadata, ...] = ()
    data_version: str = ''


__all__ = ['StudyConfig', 'WarehouseConfig', 'CrimeQuery', 'SourceMetadata', 'TreatmentReport',
           'StepResult', 'CrimeDataset', 'SpaceTimeCube', 'AnalysisConfig', 'AnalysisResult']
