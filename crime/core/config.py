"""Project configuration: paths, CRS, study window, versions and database settings.

Every constant here is a fixed fact about the study or the repository layout,
safe to import anywhere. Database settings are read when a :class:`DBConfig`
is created, not at import time, so setting ``PGPORT`` after ``import crime``
still takes effect.

The database password is never stored in the code. It is ``PGPASSWORD``, else
``POSTGRES_PASSWORD`` (the variable ``database/docker-compose.yml`` uses), read
from the environment and then from the repository's ``.env`` (copy
``.env.example``). The other defaults match the compose file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: Package version, the single source (re-exported as ``crime.__version__``).
__version__ = "1.0.0"

# ---------------------------------------------------------------- paths --------
# Layout after Alexander (2023), Telling Stories with Data, ch. 3:
#   inputs/data/  raw inputs, never edited (Git LFS)
#   outputs/      everything the stages and notebooks produce (git-ignored, rebuilt by `make`)
REPO_ROOT = Path(__file__).resolve().parents[2]
INPUTS_DIR = REPO_ROOT / "inputs" / "data"
OUTPUTS_DIR = REPO_ROOT / "outputs"
OUTPUT_DATA_DIR = OUTPUTS_DIR / "data"
NOTEBOOK_OUTPUTS_DIR = OUTPUTS_DIR / "nb"     # notebooks/<stem>.ipynb write to outputs/nb/<stem>/
STAGING_DIR = OUTPUT_DATA_DIR / "staging"     # hand-over files between the ETL stages
REPORTS_DIR = OUTPUTS_DIR / "reports"         # one Markdown report per stage, plus the data profile
GEOBR_CACHE = INPUTS_DIR / "geobr"

# Raw inputs.
SSP_XLSX_2025 = INPUTS_DIR / "SPDadosCriminais_2025.xlsx"
SSP_CSV_2022_2024 = INPUTS_DIR / "crimes_campinas_2022_2024.csv.bak"
LEGACY_CRIMES_CSV = INPUTS_DIR / "crimes_campinas.csv"   # hand-assembled CSV (commit 6891c8b), compared by acquire
CNEFE_JSON = INPUTS_DIR / "qg_810_endereco_Munic3509502.json"
PAINEL_CSV = INPUTS_DIR / "Painel_IBGE_2022.csv"
CENSUS_BASICO_ZIP = GEOBR_CACHE / "Agregados_por_setores_basico_BR_20260520.zip"
CENSUS_INCOME_ZIP = GEOBR_CACHE / "Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip"

# Acquire output: one row per offence record.
CRIMES_CSV = OUTPUT_DATA_DIR / "crimes_campinas.csv"

# ------------------------------------------------------------ study design -----
#: Study window by occurrence date, both ends included.
DATE_START = "2022-01-01"
DATE_END = "2025-12-31"

# --------------------------------------------------------------- geography -----
CRS_WGS84 = "EPSG:4326"
#: SIRGAS 2000 / UTM zone 23S, metres: the CRS of every stored geometry and every distance or area.
CRS_METRIC = "EPSG:31983"
#: IBGE municipality code of Campinas (the prefix of its census tract ids).
CODE_MUNI_CAMPINAS = 3509502

# -------------------------------------------------------------- warehouse ------
#: Version of ``database/schema.sql``. The reader refuses a warehouse built with another one.
SCHEMA_VERSION = "1.0.0"
#: Version of the data release this code builds (git tag ``data-v<DATA_VERSION>``).
DATA_VERSION = "1.0.0"


def _env(name: str, default: str):
    """Field default read from the environment; an empty variable counts as unset
    (``make`` exports ``PGPORT`` empty when it is not set)."""
    return field(default_factory=lambda: os.getenv(name) or default)


def _dotenv(path: Path = REPO_ROOT / ".env") -> dict[str, str]:
    """``KEY=VALUE`` lines of the repository's ``.env`` (git-ignored), if it exists."""
    out: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def _password() -> str:
    """``PGPASSWORD`` or ``POSTGRES_PASSWORD``, from the environment, then ``.env``."""
    env = {**_dotenv(), **os.environ}
    return env.get("PGPASSWORD") or env.get("POSTGRES_PASSWORD") or ""


@dataclass(frozen=True)
class DBConfig:
    """Connection settings of the PostGIS warehouse.

    Attributes
    ----------
    host, port, database, user : str or int
        ``PGHOST`` (``localhost``), ``PGPORT`` (``5433``), ``PGDATABASE``
        (``crime_db``) and ``PGUSER`` (``admin``).
    password : str
        See the module docstring; never printed in ``repr``.
    """

    host: str = _env("PGHOST", "localhost")
    port: int = field(default_factory=lambda: int(os.getenv("PGPORT") or "5433"))
    database: str = _env("PGDATABASE", "crime_db")
    user: str = _env("PGUSER", "admin")
    password: str = field(default_factory=_password, repr=False)

    @property
    def url(self) -> str:
        """SQLAlchemy URL (``postgresql+psycopg2://...``)."""
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


def engine(db: DBConfig | None = None):
    """SQLAlchemy engine for the warehouse (:func:`sqlalchemy.create_engine`).

    A short connect timeout makes a stopped database fail fast instead of hanging.
    """
    from sqlalchemy import create_engine

    return create_engine((db or DBConfig()).url, future=True, connect_args={"connect_timeout": 5})
