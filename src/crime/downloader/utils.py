"""Stream downloads to a temporary file before publishing a complete source."""
from __future__ import annotations

import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from crime.errors import DownloadError
from crime.utils.checksums import sha256
from crime.utils.logging import get_logger

log = get_logger(__name__)


def download_file(url: str, destination: str | Path, *, expected_sha256: str | None = None,
                  timeout: float = 60, retries: int = 3) -> Path:
    """Download HTTP(S) content atomically, verifying an optional source digest.

    Existing sources are reused only when an expected digest confirms identity.
    An existing file with another checksum is never overwritten implicitly.
    """
    destination = Path(destination)
    if not url.startswith(('https://', 'http://')) or retries < 1 or timeout <= 0:
        raise ValueError('Require an HTTP(S) URL, positive timeout and retries >= 1')
    if destination.exists():
        if expected_sha256 and sha256(destination) == expected_sha256:
            return destination
        raise DownloadError(f'Destination already exists without a matching checksum: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        temporary = None
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'campinas-crime-stpm'})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
            if expected_sha256 and sha256(temporary) != expected_sha256:
                raise DownloadError(f'Checksum differs for {url}')
            # Hard-link publication refuses to clobber a concurrent source download.
            os.link(temporary, destination)
            return destination
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code not in (408, 429):
                raise DownloadError(f'HTTP {exc.code} for {url}') from exc
            failure = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failure = exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        if attempt + 1 < retries:
            log.warning('Download retry %s/%s: %s', attempt + 1, retries, url)
            time.sleep(min(2 ** attempt, 8))
    raise DownloadError(f'Download failed after {retries} attempts: {url}') from failure
