"""Acquire and verify the versioned Campinas study-data release.

The Python wheel contains the pinned checksum manifest, not the raw study
files. A release may expose those files directly and may optionally publish
``release.json`` beside them::

    {"version": "1.0.0", "files": {"file.csv": "<sha256>"}}

The metadata file lets ``auto_update=True`` discover a newer compatible data
release without changing the code package.
"""
from __future__ import annotations

import json
import os
import shutil
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Mapping
from urllib.parse import quote, urlparse

from crime.config import DATA_VERSION, INPUTS_DIR
from crime.downloader.utils import download_file
from crime.errors import DownloadError
from crime.importer.acquisition import expected_checksums
from crime.utils.checksums import sha256

DEFAULT_RELEASE_URL = (
    "https://github.com/rsushizawa/campinas-crime-stpm/"
    "releases/download/data-v1.0.0"
)
RELEASE_METADATA_NAME = "release.json"
LOCAL_RELEASE_METADATA = ".crime-data-release.json"


@dataclass(frozen=True)
class StudyDataRelease:
    """A downloadable, checksum-addressed study-data release."""

    version: str
    base_url: str
    checksums: Mapping[str, str]
    archive: str | None = None


@dataclass(frozen=True)
class StudyDataStatus:
    """Verification result for a study-data directory."""

    directory: Path
    valid: bool
    missing: tuple[str, ...]
    invalid: tuple[str, ...]


@dataclass(frozen=True)
class StudyDataResult:
    """Result of resolving a local or downloaded study-data release."""

    directory: Path
    version: str
    source: str
    downloaded: tuple[Path, ...] = ()


def _manifest() -> dict[str, str]:
    """Return the checksum manifest shipped with the installed package."""
    return expected_checksums(files("crime.downloader").joinpath("campinas-2022-2025.sha256"))


def _safe_relative(name: str) -> Path:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Invalid release path: {name!r}")
    return Path(*path.parts)


def _metadata_url(base_url: str) -> str:
    # GitHub's release CDN occasionally serves a freshly uploaded small asset
    # through its download redirect only when the query parameter is present.
    return base_url.rstrip("/") + "/" + RELEASE_METADATA_NAME + "?download=1"


def _read_release_metadata(base_url: str) -> StudyDataRelease | None:
    """Read optional ``release.json``; return ``None`` when not published."""
    if urlparse(base_url).scheme != "https":
        raise ValueError("Use an HTTPS data-release URL")
    request = urllib.request.Request(_metadata_url(base_url), headers={"User-Agent": "campinas-crime-stpm"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise DownloadError(f"HTTP {exc.code} while reading {_metadata_url(base_url)}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DownloadError(f"Could not read {_metadata_url(base_url)}") from exc

    version = payload.get("version")
    checksums = payload.get("files")
    if not isinstance(version, str) or not version or not isinstance(checksums, dict) or not checksums:
        raise DownloadError(f"Invalid release metadata at {_metadata_url(base_url)}")
    clean: dict[str, str] = {}
    for name, digest in checksums.items():
        relative = _safe_relative(str(name)).as_posix()
        if not isinstance(digest, str) or len(digest) != 64:
            raise DownloadError(f"Invalid SHA-256 for release file {name!r}")
        clean[relative] = digest
    archive = payload.get("archive")
    if archive is not None:
        _safe_relative(str(archive))
    return StudyDataRelease(version, base_url.rstrip("/"), clean, str(archive) if archive else None)


def resolve_release(base_url: str | None = None, *, auto_update: bool = False) -> StudyDataRelease:
    """Resolve a release URL and its manifest.

    Without remote metadata, the package's pinned manifest is used. Remote
    metadata is consulted only when ``auto_update`` is enabled.
    """
    url = base_url or os.getenv("CRIME_DATA_RELEASE_URL") or DEFAULT_RELEASE_URL
    if urlparse(url).scheme != "https":
        raise ValueError("Use an HTTPS data-release URL")
    remote = _read_release_metadata(url) if auto_update else None
    archive = f"campinas-crime-stpm-data-v{DATA_VERSION}.tar.gz"
    return remote or StudyDataRelease(DATA_VERSION, url.rstrip("/"), _manifest(), archive)


def inspect_study_inputs(destination: str | Path = INPUTS_DIR,
                         checksums: Mapping[str, str] | None = None) -> StudyDataStatus:
    """Check a directory without changing it."""
    destination = Path(destination)
    checksums = checksums or _manifest()
    missing: list[str] = []
    invalid: list[str] = []
    for relative, digest in checksums.items():
        path = destination / _safe_relative(relative)
        if not path.is_file():
            missing.append(relative)
        elif sha256(path) != digest:
            invalid.append(relative)
    return StudyDataStatus(destination, not missing and not invalid, tuple(missing), tuple(invalid))


def _stage_release(release: StudyDataRelease, destination: Path) -> tuple[Path, ...]:
    """Download into a temporary release directory and publish atomically."""
    staging = destination / ".download" / release.version
    staging.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[Path, Path]] = []
    try:
        if release.archive:
            archive_name = _safe_relative(release.archive)
            archive = staging / archive_name
            download_file(release.base_url + "/" + quote(archive_name.as_posix()), archive)
            extracted = staging / "extracted"
            extracted.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive) as bundle:
                for member in bundle.getmembers():
                    name = _safe_relative(member.name)
                    if not member.isfile():
                        raise DownloadError(f"Data release archive contains a non-file member: {member.name}")
                    target = extracted / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.extractfile(member) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
            for relative, digest in release.checksums.items():
                name = _safe_relative(relative)
                source = extracted / name
                if not source.is_file() or sha256(source) != digest:
                    raise DownloadError(f"Archive checksum differs for {relative}")
                staged.append((source, destination / name))
        else:
            for relative, digest in release.checksums.items():
                name = _safe_relative(relative)
                source = staging / name
                url = release.base_url + "/" + quote(name.as_posix())
                download_file(url, source, expected_sha256=digest)
                staged.append((source, destination / name))

        archived = destination / ".releases" / release.version
        for source, target in staged:
            target.parent.mkdir(parents=True, exist_ok=True)
            relative = source.relative_to(staging).as_posix()
            if target.exists() and sha256(target) == release.checksums[relative]:
                source.unlink(missing_ok=True)
                continue
            if target.exists():
                backup = archived / source.relative_to(staging)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(backup))
            source.replace(target)
        metadata = destination / LOCAL_RELEASE_METADATA
        metadata.write_text(json.dumps({"version": release.version, "archive": release.archive,
                                        "files": release.checksums}, indent=2) + "\n")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(destination / ".download", ignore_errors=True)
    return tuple(target for _, target in staged if target.is_file())


def ensure_study_inputs(destination: str | Path = INPUTS_DIR, *, mode: str = "auto",
                        base_url: str | None = None, auto_update: bool = False) -> StudyDataResult:
    """Ensure a verified study-data release is available.

    ``local`` only verifies existing files; ``download`` fetches the selected
    release; ``auto`` reuses a valid local release and downloads when files are
    missing or invalid. Updates are staged and previous files are retained.
    """
    if mode not in {"local", "download", "auto"}:
        raise ValueError("mode must be 'local', 'download', or 'auto'")
    destination = Path(destination).expanduser()
    pinned = _manifest()
    local = inspect_study_inputs(destination, pinned)
    if mode == "local":
        if not local.valid:
            raise FileNotFoundError(
                f"Study data are not a verified pinned release; missing={local.missing}, invalid={local.invalid}"
            )
        return StudyDataResult(destination, DATA_VERSION, "local")

    release = resolve_release(base_url, auto_update=auto_update)
    release_local = inspect_study_inputs(destination, release.checksums)
    if mode == "auto" and release_local.valid:
        return StudyDataResult(destination, release.version, "local")

    downloaded = _stage_release(release, destination)
    verified = inspect_study_inputs(destination, release.checksums)
    if not verified.valid:
        raise DownloadError(
            f"Downloaded release failed verification: missing={verified.missing}, invalid={verified.invalid}"
        )
    return StudyDataResult(destination, release.version, "download", downloaded)


def download_study_inputs(base_url: str, destination: str | Path, checksums: Mapping[str, str]) -> list[Path]:
    """Backward-compatible wrapper for downloading a manifest-addressed release."""
    destination = Path(destination)
    current = inspect_study_inputs(destination, checksums)
    if current.valid:
        return [destination / _safe_relative(name) for name in checksums]
    release = StudyDataRelease(DATA_VERSION, base_url.rstrip("/"), dict(checksums))
    return list(_stage_release(release, destination))
