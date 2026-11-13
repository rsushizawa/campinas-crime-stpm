"""Discover and retrieve IBGE 2022 census aggregate archives."""
import re
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

from crime.downloader.utils import download_file
from crime.errors import DownloadError

SETORES_URL = ('https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/'
               'Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/')


def download_setores_csv(keyword: str, cache_dir: Path) -> Path:
    """Find the first published archive matching the established source keyword."""
    request = urllib.request.Request(SETORES_URL, headers={'User-Agent': 'campinas-crime-stpm-etl'})
    with urllib.request.urlopen(request, timeout=60) as response:
        listing = response.read().decode('latin-1', 'ignore')
    match = next((h for h in re.findall(r'href="([^"]+\.zip)"', listing) if keyword in h.lower()), None)
    if match is None:
        raise DownloadError(f'No census archive matching {keyword!r} on the IBGE server')
    destination = Path(cache_dir) / Path(match).name
    if destination.exists():
        return destination  # acquisition rule 1 validates pinned raw inputs separately
    return download_file(urljoin(SETORES_URL, match), destination)
