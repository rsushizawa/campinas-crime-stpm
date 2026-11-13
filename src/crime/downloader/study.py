"""Retrieve a pinned study input bundle from an explicitly selected release."""
from pathlib import Path

from crime.downloader.utils import download_file


def download_study_inputs(base_url: str, destination: str | Path, checksums: dict[str, str]) -> list[Path]:
    """Download missing files and verify every cached file against the manifest.

    The URL is supplied by the user: the package does not assume unpublished
    study inputs are available from a public repository. It can be a Git LFS
    media URL or an archive server exposing the manifest's relative paths.
    """
    from urllib.parse import quote, urlparse

    from crime.utils.checksums import sha256
    if urlparse(base_url).scheme != 'https':
        raise ValueError('Use an HTTPS release URL')
    destination = Path(destination)
    paths = []
    for relative, digest in checksums.items():
        name = Path(relative)
        if name.is_absolute() or '..' in name.parts:
            raise ValueError('Manifest paths must remain inside the input directory')
        path = destination / name
        if path.exists():
            if sha256(path) != digest:
                raise ValueError(f'Cached input checksum mismatch: {relative}')
        else:
            download_file(base_url.rstrip('/') + '/' + quote(name.as_posix()), path, expected_sha256=digest)
        paths.append(path)
    return paths
