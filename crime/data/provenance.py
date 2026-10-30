"""Run provenance — stamp every result artefact with what produced it.

    from crime.data.provenance import provenance, write_provenance
    write_provenance(out_dir / "backtest_property_ME.provenance.json", extra={"freq": "ME"})

``provenance()`` returns the package version, key library versions, the git
commit (if the working tree is a repo; ``-dirty`` when it has uncommitted
changes) and a UTC timestamp. The PostGIS target (``db``) is recorded only
when the caller says the result was read from the database (``db=True``);
the core pipeline uses no database, so its manifest has no ``db`` field.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_LIBS = (
    "numpy", "pandas", "scipy", "scikit-learn", "geopandas", "shapely", "libpysal",
    "esda", "statsmodels",
)


def _lib_versions() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    out = {}
    for name in _LIBS:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            pass
    return out


def _git_commit() -> str | None:
    try:
        root = Path(__file__).resolve().parents[2]
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return f"{sha}{'-dirty' if dirty else ''}" if sha else None
    except Exception:
        return None


def provenance(extra: dict | None = None, *, db: bool = False) -> dict:
    """Provenance record; ``db=True`` adds the PostGIS target (host:port/database)."""
    from crime.core.config import __version__

    out = {
        "package_version": __version__,
        "git_commit": _git_commit(),
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "libraries": _lib_versions(),
    }
    if db:
        from crime.core.config import DBConfig

        cfg = DBConfig()
        out["db"] = f"{cfg.host}:{cfg.port}/{cfg.database}"
    return {**out, **(extra or {})}


def write_provenance(path: str | Path, *, extra: dict | None = None, db: bool = False) -> Path:
    """Write ``provenance()`` next to a result file (JSON). Returns the path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(provenance(extra, db=db), indent=2, sort_keys=True))
    return p
