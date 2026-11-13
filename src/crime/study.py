"""High-level, self-provisioning study workflow.

This is the notebook-facing API. Lower-level modules remain available for
custom treatments, but ordinary users can acquire data, build a dataset and
open the interactive cube with one object.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Mapping

from crime.config import INPUTS_DIR, REPO_ROOT
from crime.downloader.live import LiveDataResult, download_live_inputs
from crime.downloader.study import StudyDataResult, ensure_study_inputs
from crime.generator import generate_cube, generate_dataset
from crime.importer.acquisition import RawInputs, expected_checksums
from crime.models import CrimeDataset, CrimeQuery, SpaceTimeCube, StudyConfig


@dataclass(frozen=True)
class CrimeStudyConfig:
    """Configuration for the self-provisioning workflow."""

    municipality: str = "3509502"
    start: dt.date = dt.date(2022, 1, 1)
    end: dt.date = dt.date(2025, 12, 31)
    data_profile: Literal["snapshot", "live", "hybrid"] = "snapshot"
    data_mode: Literal["local", "download", "auto"] = "auto"
    data_directory: Path = INPUTS_DIR
    data_release_url: str | None = None
    auto_update_data: bool = False
    live_source_urls: Mapping[str, str] = field(default_factory=dict)
    workspace: Path = REPO_ROOT
    time_unit: Literal["month", "quarter", "year"] = "quarter"
    crime_group: str = "all"

    def __post_init__(self):
        if self.data_profile not in {"snapshot", "live", "hybrid"}:
            raise ValueError("data_profile must be snapshot, live, or hybrid")
        if self.data_mode not in {"local", "download", "auto"}:
            raise ValueError("data_mode must be local, download, or auto")
        if self.start > self.end:
            raise ValueError("start must not be after end")


@dataclass
class CrimeStudyResult:
    """Materialized study data and its first space-time cube."""

    config: CrimeStudyConfig
    dataset: CrimeDataset
    cube: SpaceTimeCube
    data_release: StudyDataResult | LiveDataResult | None = None

    def explore(self, *, bins=None, labels=None, alpha: float = 0.05):
        """Return the interactive map, selected-tract series and history viewer."""
        from crime.visualizer.cube import cube_explorer

        return cube_explorer(self.cube, self.dataset.tracts, bins=bins, labels=labels, alpha=alpha)

    @property
    def bulletins(self):
        """Treated police-record rows."""
        return self.dataset.bulletins

    @property
    def tracts(self):
        """Census-tract geometry and attributes."""
        return self.dataset.tracts


class CrimeStudy:
    """One-call Campinas study workflow, modeled after VoxCity's public API."""

    def __init__(self, **kwargs):
        self.config = CrimeStudyConfig(**kwargs)

    def _acquire_data(self):
        c = self.config
        if c.data_profile == "snapshot":
            return ensure_study_inputs(c.data_directory, mode=c.data_mode,
                                       base_url=c.data_release_url, auto_update=c.auto_update_data)
        if c.data_profile == "hybrid":
            snapshot = ensure_study_inputs(c.data_directory, mode="local",
                                           base_url=c.data_release_url, auto_update=False)
            live = download_live_inputs(c.data_directory, source_urls=c.live_source_urls,
                                        overwrite=c.data_mode == "download" or c.auto_update_data,
                                        require_all=False)
            return (snapshot, live)
        live = download_live_inputs(c.data_directory, source_urls=c.live_source_urls,
                                    overwrite=c.data_mode == "download" or c.auto_update_data,
                                    require_all=True)
        return live

    def build(self) -> CrimeStudyResult:
        """Acquire current/pinned inputs, apply treatments, and build a cube."""
        acquired = self._acquire_data()
        c = self.config
        raw_checksums = expected_checksums() if c.data_profile == "snapshot" else {}
        raw = RawInputs(
            csv_2022_2024=c.data_directory / "crimes_campinas_2022_2024.csv.bak",
            xlsx_2025=c.data_directory / "SPDadosCriminais_2025.xlsx",
            checksums=raw_checksums,
        )
        from crime.geoprocessor.units import UnitsInput

        units = UnitsInput(
            bulletins=None,
            geobr_cache=c.data_directory / "geobr",
            census_basico=c.data_directory / "geobr/Agregados_por_setores_basico_BR_20260520.zip",
            census_income=c.data_directory / "geobr/Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip",
            painel=c.data_directory / "Painel_IBGE_2022.csv",
            cnefe=c.data_directory / "qg_810_endereco_Munic3509502.json",
        )
        dataset = generate_dataset(
            config=StudyConfig(municipality=c.municipality, start=c.start, end=c.end, project_root=c.workspace),
            raw_inputs=raw,
            units_input=units,
        )
        cube = generate_cube(dataset, CrimeQuery(start=c.start, end=c.end,
                                                 time_unit=c.time_unit, crime_group=c.crime_group))
        release = acquired[0] if isinstance(acquired, tuple) else acquired
        return CrimeStudyResult(c, dataset, cube, release)


__all__ = ["CrimeStudy", "CrimeStudyConfig", "CrimeStudyResult"]
