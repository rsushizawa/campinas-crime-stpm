"""Stream checksums without loading a complete source into memory."""
import hashlib
from pathlib import Path


def sha256(path: str | Path) -> str:
    """Return the SHA-256 of a local file."""
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
