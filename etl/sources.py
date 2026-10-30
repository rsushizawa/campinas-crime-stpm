"""Extract each raw data source into a (Geo)DataFrame ready for PostGIS load.

One plain function per source — no factory, no base class:

    from etl import sources
    crimes  = sources.extract_crimes()
    tracts  = sources.extract_census_tracts()
    grid    = sources.extract_grid(boundary=tracts)
    utb     = sources.extract_utb()
    cnefe   = sources.extract_cnefe()
    pop     = sources.extract_census_2022()      # definitive IBGE 2022, per tract
    income  = sources.extract_income_2022()      # IBGE 2022 household-head income, per tract
    lit     = sources.extract_literacy()

``extract_census_2022`` downloads the **definitive** "Agregados por Setores
Censitários / Básico" CSV from the IBGE FTP (cached under ``inputs/data/geobr``),
replacing the preliminary ``Agregados_..._BR.zip`` that used to live in the
repo. ``extract_census_tracts`` / ``extract_grid`` use ``geobr`` + a parquet
cache as before.
"""
import io
import re
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from crime.core.config import (
    BULLETINS_PARQUET,
    CNEFE_JSON,
    CODE_MUNI_CAMPINAS,
    CRIMES_CSV,
    GEOBR_CACHE,
    GRID_2022_ZIP,
    INPUTS_DIR,
    UTB_GEOJSON,
)

PAINEL_CSV = INPUTS_DIR / "Painel_IBGE_2022.csv"

_IBGE_SETORES_CSV = (
    "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
    "Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/"
)
_UA = {"User-Agent": "ic-crime-etl"}
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


def extract_bulletins(path: str | Path = BULLETINS_PARQUET) -> pd.DataFrame:
    """Cleaned bulletins — one row per ``NUM_BO + ANO_BO + NOME_DELEGACIA``
    (``scripts/02_clean/clean_bulletins.py``; rule in ``etl/clean.py``)."""
    return pd.read_parquet(path)


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


def extract_grid(
    *, boundary: gpd.GeoDataFrame, path: str | Path = GRID_2022_ZIP, cache_dir: Path = GEOBR_CACHE
) -> gpd.GeoDataFrame:
    """2022 statistical grid clipped to ``boundary`` (grid_id, pop_total, dom_total)."""
    cache = Path(cache_dir) / "statistical_grid_2022_campinas.parquet"
    if cache.exists():
        gdf = gpd.read_parquet(cache)
    else:
        b = boundary.to_crs("EPSG:4674")
        gdf = gpd.read_file(path, bbox=tuple(b.total_bounds))
        gdf = gdf[gdf.geometry.intersects(b.union_all())]
        cache.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_parquet(cache)
    gdf = gdf.rename(columns={"ID_UNICO": "grid_id", "TOTAL": "pop_total", "TOTAL_DOM": "dom_total"})
    gdf = gdf[["grid_id", "pop_total", "dom_total", "geometry"]].drop_duplicates(subset="grid_id")
    return gdf.to_crs("EPSG:4326")


# --------------------------------------------------------------------------- #
#  UTB polygons + CNEFE address points
# --------------------------------------------------------------------------- #
def extract_utb(path: str | Path = UTB_GEOJSON) -> gpd.GeoDataFrame:
    """93 UTB polygons. The file declares 4326 but holds 31983 coords.

    ``rendatemei`` is a **count** of residents earning <= 1/2 minimum wage
    (max 606 per zone), not an income level; it was previously renamed to
    ``income_mean`` by mistake (issue #1, comment 5: Spearman -0.585 against
    the real IBGE 2022 tract income). It is now exposed under the honest name
    ``n_low_income_half_mw``. For tract income use :func:`extract_income_2022`.
    """
    gdf = gpd.read_file(path).set_crs("EPSG:31983", allow_override=True).to_crs("EPSG:4326")
    gdf = gdf.rename(columns={"rendatemei": "n_low_income_half_mw", "denominaca": "denominacao"})
    gdf["gid"] = range(1, len(gdf) + 1)
    return gdf[["gid", "utb_sigla", "denominacao", "tot_pop", "tot_dom",
                "tot_pop_fa", "n_low_income_half_mw", "geometry"]]


def extract_cnefe(path: str | Path = CNEFE_JSON) -> gpd.GeoDataFrame:
    """CNEFE address points in EPSG:4326. A row is one use type (espécie) at one
    address, so duplicates are dropped on (cod_unico_endereco, cod_especie)
    (issue #18; deduplicating on the address alone lost 8% of espécie 6)."""
    rename = {
        "COD_UNICO_ENDERECO": "cod_unico_endereco", "COD_SETOR": "cd_setor", "CEP": "cep",
        "DSC_LOCALIDADE": "dsc_localidade", "NV_GEO_COORD": "nv_geo_coord",
        "COD_TIPO_ESPECI": "cod_tipo_especi", "DSC_ESTABELECIMENTO": "dsc_estabelecimento",
        "COD_ESPECIE": "cod_especie",
    }
    gdf = gpd.read_file(path)
    gdf["COD_SETOR"] = gdf["COD_SETOR"].astype(str).str.rstrip("P")
    gdf = gdf.rename(columns=rename)[list(rename.values()) + ["geometry"]]
    gdf = gdf.drop_duplicates(subset=["cod_unico_endereco", "cod_especie"])
    return gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:4326")


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
    ``dim_setor_painel`` — used by ``enrich.sql`` for ``literacy_rate``.

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
