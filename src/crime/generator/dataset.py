"""Dataset construction from the study's documented treatment pipelines."""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd

from crime.config import INPUTS_DIR, STAGING_DIR
from crime.models import CrimeDataset, SourceMetadata, StudyConfig, TreatmentReport
from crime.utils.checksums import sha256


def load_dataset(staging_dir: str | Path = STAGING_DIR) -> CrimeDataset:
    """Read an existing staged release without downloading or rebuilding data."""
    staging_dir = Path(staging_dir)
    units = staging_dir / 'units'
    sources, reports, rejects = [], [], []
    for stage in ('acquire', 'clean', 'units'):
        folder = staging_dir / stage
        report = folder / 'report.json'
        if report.exists():
            reports.extend(TreatmentReport(**r) for r in json.loads(report.read_text()))
        rejected = folder / 'rejects.parquet'
        if rejected.exists():
            rejects.append(pd.read_parquet(rejected))
    for name in ('bulletins', 'tracts', 'poi'):
        path = units / f'{name}.parquet'
        sources.append(SourceMetadata(name, str(path.resolve()), sha256(path)))
    return CrimeDataset(gpd.read_parquet(units / 'bulletins.parquet'),
                        gpd.read_parquet(units / 'tracts.parquet'),
                        gpd.read_parquet(units / 'poi.parquet'),
                        sources=tuple(sources), reports=reports,
                        rejects=pd.concat(rejects, ignore_index=True) if rejects else pd.DataFrame())


def generate_dataset(config: StudyConfig | None = None, *, raw_inputs=None, units_input=None) -> CrimeDataset:
    """Apply the pinned Campinas treatment rules and return a reusable dataset.

    This runs treatments in memory. Database writes and file exports are
    separate explicit operations. Override source paths with RawInputs and
    UnitsInput objects; the study rules currently cover Campinas 2022–2025.
    """
    from dataclasses import replace

    from crime.geoprocessor.units import UnitsInput, units_pipeline
    from crime.importer.acquisition import RawInputs, acquire_pipeline
    from crime.importer.cleaning import clean_pipeline

    config = config or StudyConfig()
    defaults = StudyConfig()
    if (config.municipality, config.start, config.end, config.crs) != (
            defaults.municipality, defaults.start, defaults.end, defaults.crs):
        raise ValueError('Pinned treatment rules support Campinas 2022–2025 in EPSG:31983')
    raw_inputs = raw_inputs or RawInputs()
    acquired = acquire_pipeline().run(raw_inputs)
    cleaned = clean_pipeline().run(acquired.kept)
    inp = replace(units_input, bulletins=cleaned.kept) if units_input else UnitsInput(cleaned.kept)
    assigned = units_pipeline().run(inp)
    result = assigned.kept
    reports = acquired.report + cleaned.report + assigned.report
    rejected = pd.concat([r.rejects for r in (acquired, cleaned, assigned)], ignore_index=True)
    paths = {Path(raw_inputs.csv_2022_2024), Path(raw_inputs.xlsx_2025),
             Path(inp.census_basico), Path(inp.census_income), Path(inp.painel), Path(inp.cnefe),
             Path(inp.geobr_cache) / 'census_tract_3509502_2022.parquet'}
    # These files were checked by acquisition rule 1; preserve all their identities.
    paths.update(INPUTS_DIR / name for name in raw_inputs.checksums)
    sources = tuple(SourceMetadata(p.name, str(p.resolve()), sha256(p)) for p in sorted(paths))
    return CrimeDataset(result.bulletins, result.tracts, result.poi, config, sources, reports, rejected)
