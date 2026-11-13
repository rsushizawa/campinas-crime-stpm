"""Retrieve current source files for a non-reproducible live data run."""
from __future__ import annotations

import json
import shutil
import tempfile
import urllib.parse
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from crime.config import INPUTS_DIR
from crime.downloader.utils import download_file
from crime.errors import DownloadError
from crime.utils.checksums import sha256

DEFAULT_LIVE_URLS = {
    "census_basico": (
        "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
        "Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/"
        "Agregados_por_setores_basico_BR_20260520.zip"
    ),
    "census_income": (
        "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/"
        "Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/"
        "Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip"
    ),
    "cnefe": (
        "https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/"
        "Censo_Demografico_2022/Arquivos_CNEFE/GeoJSON/Municipio_20240910/35_SP/"
        "qg_810_endereco_Munic3509502.json.zip"
    ),
}

REQUIRED_LIVE_KEYS = (
    "ssp_2022_2024",
    "ssp_2025",
    "legacy_crimes",
    "painel",
    "census_basico",
    "census_income",
    "cnefe",
)


@dataclass(frozen=True)
class LiveDataResult:
    """Source provenance for a live input acquisition."""

    directory: Path
    downloaded: tuple[Path, ...]
    sources: Mapping[str, str]
    retrieved_at: str


def _target(key: str, destination: Path) -> Path:
    names = {
        "ssp_2022_2024": "crimes_campinas_2022_2024.csv.bak",
        "ssp_2025": "SPDadosCriminais_2025.xlsx",
        "legacy_crimes": "crimes_campinas.csv",
        "painel": "Painel_IBGE_2022.csv",
        "census_basico": "geobr/Agregados_por_setores_basico_BR_20260520.zip",
        "census_income": "geobr/Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip",
        "cnefe": "qg_810_endereco_Munic3509502.json",
    }
    if key not in names:
        raise ValueError(f"Unknown live source key: {key}")
    return destination / names[key]


def _download_replace(url: str, target: Path, *, overwrite: bool) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        return target
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        staged = Path(tmp) / target.name
        download_file(url, staged)
        if overwrite and target.exists():
            backup = target.with_suffix(target.suffix + ".live-old")
            shutil.move(str(target), str(backup))
        staged.replace(target)
    return target


def _download_cnefe(url: str, target: Path, *, overwrite: bool) -> Path:
    if target.exists() and not overwrite:
        return target
    with tempfile.TemporaryDirectory(dir=target.parent if target.parent.exists() else None) as tmp:
        archive = Path(tmp) / "cnefe.zip"
        download_file(url, archive)
        with zipfile.ZipFile(archive) as source:
            members = [name for name in source.namelist() if name.lower().endswith(".json")]
            if len(members) != 1:
                raise DownloadError(f"Expected one CNEFE JSON member in {url}, found {members}")
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = Path(tmp) / Path(members[0]).name
            with source.open(members[0]) as source_file, extracted.open("wb") as target_file:
                shutil.copyfileobj(source_file, target_file)
            if overwrite and target.exists():
                shutil.move(str(target), str(target.with_suffix(target.suffix + ".live-old")))
            extracted.replace(target)
    return target


def _download_tracts(destination: Path, *, overwrite: bool) -> Path:
    """Fetch the current GeoBR tract mesh and retain its normal cache path."""
    from crime.importer.sources import extract_census_tracts

    cache = destination / "geobr/census_tract_3509502_2022.parquet"
    if overwrite and cache.exists():
        shutil.move(str(cache), str(cache.with_suffix(cache.suffix + ".live-old")))
    extract_census_tracts(cache_dir=destination / "geobr")
    return cache


def download_live_inputs(destination: str | Path = INPUTS_DIR, *, source_urls: Mapping[str, str] | None = None,
                         overwrite: bool = False, require_all: bool = True) -> LiveDataResult:
    """Download current inputs and write live provenance.

    Official IBGE URLs are supplied for the aggregate and CNEFE files. SSP
    files, the legacy comparison CSV, and the curated literacy CSV require
    explicit URLs because their current direct endpoints are not stable or
    their source file is not an official direct export.
    """
    destination = Path(destination).expanduser()
    urls = {**DEFAULT_LIVE_URLS, **(source_urls or {})}
    missing = [key for key in REQUIRED_LIVE_KEYS if not urls.get(key)]
    if require_all and missing:
        raise ValueError("Live profile needs source URLs for: " + ", ".join(missing))
    downloaded: list[Path] = []
    sources: dict[str, str] = {}
    for key in REQUIRED_LIVE_KEYS:
        url = urls.get(key)
        if not url:
            continue
        if urllib.parse.urlparse(url).scheme != "https":
            raise ValueError(f"Live source {key!r} must use HTTPS")
        target = _target(key, destination)
        path = _download_cnefe(url, target, overwrite=overwrite) if key == "cnefe" else _download_replace(
            url, target, overwrite=overwrite)
        downloaded.append(path)
        sources[key] = url

    # GeoBR owns the tract acquisition path and writes the expected parquet cache.
    if "census_tract" in urls:
        raise ValueError("census_tract is fetched through GeoBR; do not provide a direct URL")
    tract = _download_tracts(destination, overwrite=overwrite)
    downloaded.append(tract)
    sources["census_tract"] = "geobr.read_census_tract(code_tract=3509502, year=2022)"

    metadata = {
        "profile": "live",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "files": {str(path.relative_to(destination)): sha256(path) for path in downloaded},
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / ".crime-live-data.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return LiveDataResult(destination, tuple(downloaded), sources, metadata["retrieved_at"])
