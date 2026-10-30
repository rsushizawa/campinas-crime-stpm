"""Project-wide configuration: database connection, data paths, CRS constants.

Two ways to consume it:

* **module constants** (``CRS_METRIC``, ``OUTPUTS_DIR`` ...) — fixed facts about
  the study area and repository layout; safe to import anywhere.
* **``Settings``** — the injectable bundle (paths + DB) that I/O code receives.
  ``Settings.from_env()`` is the default everywhere; pass your own to point a
  run at another database or output tree without touching globals.

The database is read from ``PGHOST``/``PGPORT``/``PGDATABASE``/``PGUSER``/
``PGPASSWORD`` **when a ``DBConfig`` is constructed** (not at import time), so
setting the environment after ``import crime`` still takes effect. Defaults
match ``database/docker-compose.yml``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

__version__ = "0.2.0"          # the package version (single source; re-exported as crime.__version__)

# ---------------------------------------------------------------- paths --------
# Layout follows Alexander (2023), *Telling Stories with Data*, ch. 3:
#   inputs/data/  raw inputs, never edited (Git LFS)
#   outputs/      everything the scripted stages produce (git-ignored, rebuilt by `make`)
REPO_ROOT = Path(__file__).resolve().parents[2]
INPUTS_DIR = REPO_ROOT / "inputs" / "data"
DATA_DIR = INPUTS_DIR                      # backwards-compatible alias: the raw-input tree
OUTPUTS_DIR = REPO_ROOT / "outputs"
OUTPUT_DATA_DIR = OUTPUTS_DIR / "data"     # stage outputs: acquired CSV, cleaned bulletins, funnel
FIGURES_DIR = OUTPUTS_DIR / "figures"
GEOBR_CACHE = INPUTS_DIR / "geobr"
RESULTS_DIR = OUTPUTS_DIR / "artifacts"    # crime.data.artifacts cache (was data/results/)

# Raw SSP-SP inputs (read by scripts/01_acquire only).
SSP_XLSX_2025 = INPUTS_DIR / "SPDadosCriminais_2025.xlsx"
SSP_CSV_2022_2024 = INPUTS_DIR / "crimes_campinas_2022_2024.csv.bak"
# Hand-assembled CSV of commit 6891c8b; kept only as the reference for the acquire diff.
LEGACY_CRIMES_CSV = INPUTS_DIR / "crimes_campinas.csv"

# Stage outputs.
CRIMES_CSV = OUTPUT_DATA_DIR / "crimes_campinas.csv"            # 01_acquire: one row per offence record
BULLETINS_PARQUET = OUTPUT_DATA_DIR / "bulletins_clean.parquet"  # 02_clean: one row per bulletin
FUNNEL_JSON = OUTPUT_DATA_DIR / "funnel.json"                    # 02_clean: N at every stage

# Other raw ETL source files read from disk (CNEFE, UTB map, grid).
# 2022 population: IBGE FTP Agregados/Básico CSV (etl/sources.py:extract_census_2022);
# literacy: inputs/data/Painel_IBGE_2022.csv (extract_literacy).
UTB_GEOJSON = INPUTS_DIR / "map.geojson"
CNEFE_JSON = INPUTS_DIR / "qg_810_endereco_Munic3509502.json"
GRID_2022_ZIP = INPUTS_DIR / "grade_id25_2022.zip"

# --------------------------------------------------------------- geography -----
CRS_WGS84 = "EPSG:4326"
CRS_METRIC = "EPSG:31983"          # SIRGAS 2000 / UTM 23S — metric CRS for Campinas
CODE_MUNI_CAMPINAS = 3509502       # IBGE municipality code (CD_SETOR prefix)
PLACE_CAMPINAS = "Campinas, São Paulo, Brazil"

# Analyses that join crime events to demographic data are restricted to this
# year so the statistical comparison is temporally valid (2022 census).
DEMOGRAPHIC_YEAR = 2022


def _env(name: str, default: str):
    return field(default_factory=lambda: os.getenv(name, default))


@dataclass(frozen=True)
class DBConfig:
    """PostGIS connection parameters (environment-backed defaults)."""

    host: str = _env("PGHOST", "localhost")
    port: int = field(default_factory=lambda: int(os.getenv("PGPORT", "5432")))
    database: str = _env("PGDATABASE", "crime_db")
    user: str = _env("PGUSER", "admin")
    password: str = field(default_factory=lambda: os.getenv("PGPASSWORD", "crime1234"), repr=False)

    @property
    def url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


@dataclass(frozen=True)
class Settings:
    """Injectable run configuration: where data lives, where results go, which DB."""

    db: DBConfig = field(default_factory=DBConfig)
    data_dir: Path = DATA_DIR
    results_dir: Path = RESULTS_DIR
    crs_metric: str = CRS_METRIC

    @classmethod
    def from_env(cls) -> "Settings":
        return cls()


def engine(db: DBConfig | None = None):
    """SQLAlchemy engine for the project database (future=True)."""
    from sqlalchemy import create_engine

    return create_engine((db or DBConfig()).url, future=True)
