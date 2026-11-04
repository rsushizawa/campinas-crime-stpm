"""Readers for each raw data source, one plain function per source.

    from etl import sources
    records = sources.extract_crimes()            # acquired SSP-SP offence records
    tracts  = sources.extract_census_tracts()     # IBGE 2022 tract polygons (geobr)
    census  = sources.extract_census_2022()       # population and households per tract
    income  = sources.extract_income_2022()       # household-head income per tract
    lit     = sources.extract_literacy()          # literacy counts per tract

The IBGE aggregate tables are read from the zips in ``inputs/data/geobr/``.
When a zip is missing it is downloaded from the IBGE FTP server; rule 1
(:class:`etl.steps.acquire.VerifyRawInputs`) then checks its SHA-256, so a
file IBGE has since replaced is caught.
"""
import io
import re
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from crime.core.config import CODE_MUNI_CAMPINAS, CRIMES_CSV, GEOBR_CACHE, PAINEL_CSV

_IBGE_SETORES_CSV = (
    "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
    "Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/"
)
_UA = {"User-Agent": "campinas-crime-stpm-etl"}
_REDACTED = "VEDAÇÃO DA DIVULGAÇÃO DOS DADOS RELATIVOS"


# --------------------------------------------------------------------------- #
#  SSP-SP crime bulletins
# --------------------------------------------------------------------------- #
def extract_crimes(path: str | Path = CRIMES_CSV) -> pd.DataFrame:
    """Offence records (one row per offence on a bulletin), typed.

    Default: the scripted acquire output ``outputs/data/crimes_campinas.csv``
    (``scripts/01_acquire``), whose coordinates are already numeric or empty.
    Redacted coordinate strings (legacy CSV) become NaN.
    """
    df = pd.read_csv(
        path, sep=";",
        low_memory=False,
        dtype={"NUM_BO": "object", "NUMERO_LOGRADOURO": "object", "ANO_BO": "Int16",
               "MES_ESTATISTICA": "Int8", "ANO_ESTATISTICA": "Int16"},
        parse_dates=["DATA_REGISTRO", "DATA_OCORRENCIA_BO"],
    )
    mask = df["LATITUDE"] == _REDACTED
    df.loc[mask, ["LATITUDE", "LONGITUDE"]] = pd.NA
    df["LATITUDE"] = pd.to_numeric(df["LATITUDE"], errors="coerce")
    df["LONGITUDE"] = pd.to_numeric(df["LONGITUDE"], errors="coerce")
    return df


# --------------------------------------------------------------------------- #
#  IBGE geometries (geobr, parquet-cached)
# --------------------------------------------------------------------------- #
def extract_census_tracts(
    *, code_muni: int = CODE_MUNI_CAMPINAS, year: int = 2022, cache_dir: Path = GEOBR_CACHE
) -> gpd.GeoDataFrame:
    """2022 census-tract mesh in EPSG:4326 (cd_setor, nm_municipio, nm_distrito, situacao)."""
    cache = Path(cache_dir) / f"census_tract_{code_muni}_{year}.parquet"
    if cache.exists():
        gdf = gpd.read_parquet(cache)
    else:
        import geobr
        gdf = geobr.read_census_tract(code_tract=code_muni, year=year, simplified=False)
        cache.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_parquet(cache)

    rename = {"code_tract": "cd_setor", "name_muni": "nm_municipio",
              "name_district": "nm_distrito", "zone": "situacao"}
    gdf = gdf.rename(columns={k: v for k, v in rename.items() if k in gdf.columns})
    keep = [c for c in ("cd_setor", "nm_municipio", "nm_distrito", "situacao", "geometry")
            if c in gdf.columns]
    gdf = gdf[keep].copy()
    gdf["cd_setor"] = gdf["cd_setor"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    if gdf["cd_setor"].duplicated().any():
        gdf = gdf.dissolve(by="cd_setor", as_index=False)
    return gdf.to_crs("EPSG:4326")


# --------------------------------------------------------------------------- #
#  Definitive IBGE 2022 census aggregates (per tract, auto-downloaded)
# --------------------------------------------------------------------------- #
def _download_setores_csv(keyword: str, cache_dir: Path) -> Path:
    """Fetch & cache one 'Agregados por Setor' zip from the IBGE FTP by keyword
    (e.g. 'basico', 'alfabetizacao'); returns the local zip path."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    listing = urllib.request.urlopen(
        urllib.request.Request(_IBGE_SETORES_CSV, headers=_UA), timeout=60
    ).read().decode("latin-1", "ignore")
    match = next((h for h in re.findall(r'href="([^"]+\.zip)"', listing)
                 if keyword in h.lower()), None)
    if match is None:
        raise RuntimeError(f"No 'Agregados por Setor' zip matching '{keyword}' on the IBGE FTP.")
    dest = cache_dir / match
    if not dest.exists():
        print(f"downloading {match} …")
        urllib.request.urlretrieve(_IBGE_SETORES_CSV + match, dest)  # noqa: S310
    return dest


def _read_setores_zip(zip_path: Path, usecols, code_muni: int) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            df = pd.read_csv(io.TextIOWrapper(f, encoding="latin-1"), sep=";",
                             dtype=str, usecols=lambda c: c.upper() in usecols)
    df.columns = [c.upper() for c in df.columns]
    return df[df["CD_SETOR"].str.startswith(str(code_muni))]


def extract_census_2022(
    *, path: str | Path | None = None, code_muni: int = CODE_MUNI_CAMPINAS,
    cache_dir: Path = GEOBR_CACHE,
) -> pd.DataFrame:
    """Per-tract population (V0001) and occupied households (V0007) from the
    definitive IBGE 2022 'Agregados por Setores / Básico' table. Downloads the
    file once (cached); pass ``path`` to use a local copy instead."""
    zip_path = Path(path) if path else _download_setores_csv("basico", cache_dir)
    df = _read_setores_zip(zip_path, {"CD_SETOR", "V0001", "V0007"}, code_muni)
    return pd.DataFrame({
        "cd_setor": df["CD_SETOR"].str.strip(),
        "populacao_total": pd.to_numeric(df["V0001"], errors="coerce"),
        "dom_total": pd.to_numeric(df["V0007"], errors="coerce"),
    })


_IBGE_RENDA_ZIP = (
    "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
    "Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/"
    "Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip"
)


def extract_income_2022(
    *, path: str | Path | None = None, code_muni: int = CODE_MUNI_CAMPINAS,
    cache_dir: Path = GEOBR_CACHE,
) -> pd.DataFrame:
    """Per-tract income of household heads from the IBGE 2022 'Agregados por
    Setores Censitários / Rendimento do Responsável' table (released 2026-05-08).

    Columns: ``cd_setor``, ``income_head_mean`` (V06004, mean nominal monthly
    income of household heads with income, R$), ``income_head_median``
    (V06006, median). Tracts IBGE suppresses for privacy (value ``"X"``) come
    back as NaN and are **not** imputed. Downloads the zip once into
    ``cache_dir`` unless ``path`` points to a local copy.
    """
    if path is None:
        path = Path(cache_dir) / _IBGE_RENDA_ZIP.rsplit("/", 1)[1]
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            print(f"downloading {path.name} …")
            urllib.request.urlretrieve(_IBGE_RENDA_ZIP, path)  # noqa: S310
    df = _read_setores_zip(Path(path), {"CD_SETOR", "V06004", "V06006"}, code_muni)
    return pd.DataFrame({
        "cd_setor": df["CD_SETOR"].str.strip(),
        "income_head_mean": pd.to_numeric(df["V06004"], errors="coerce"),
        "income_head_median": pd.to_numeric(df["V06006"], errors="coerce"),
    }).reset_index(drop=True)


_PAINEL_RENAME = {
    "alfabetizacao_15 a 29 anos, Morador sabe ler e escrever": "alfa_15_29_sabe",
    "alfabetizacao_15 a 29 anos, Morador não sabe ler e escrever": "alfa_15_29_nao_sabe",
    "alfabetizacao_30 a 59 anos, Morador sabe ler e escrever": "alfa_30_59_sabe",
    "alfabetizacao_30 a 59 anos, Morador não sabe ler e escrever": "alfa_30_59_nao_sabe",
    "alfabetizacao_60 anos ou mais, Morador sabe ler e escrever": "alfa_60_mais_sabe",
    "alfabetizacao_60 anos ou mais, Morador não sabe ler e escrever": "alfa_60_mais_nao_sabe",
    "alfabetizacao_15 anos ou mais, Morador sabe ler e escrever": "alfa_15_mais_sabe",
    "alfabetizacao_15 anos ou mais, Morador não sabe ler e escrever": "alfa_15_mais_nao_sabe",
}


def extract_literacy(path: str | Path = PAINEL_CSV) -> pd.DataFrame:
    """Per-tract literacy indicators (8 ``alfa_*`` age-band columns) for
    ``literacy_rate`` (:mod:`etl.census`).

    NOTE: still read from the curated ``Painel_IBGE_2022.csv`` export. The
    definitive per-tract source is the IBGE FTP "Agregados por Setores /
    Alfabetização" table, but its literacy rate needs the 15+ population from a
    second aggregate; swap this one function once that mapping is in place.
    Population and households already come from the definitive file
    (``extract_census_2022``).
    """
    df = pd.read_csv(path, sep=None, engine="python", dtype={"CD_SETOR": str})
    df = df.rename(columns=_PAINEL_RENAME).rename(columns={"CD_SETOR": "cd_setor"})
    keep = ["cd_setor"] + list(_PAINEL_RENAME.values())
    return df[[c for c in keep if c in df.columns]]
