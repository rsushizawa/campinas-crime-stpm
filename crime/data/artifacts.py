"""Persist slow results so notebooks load instead of recompute.

Each result is saved as a **directory**: tabular parts as Parquet
(``period x unit`` layers are transposed so the datetime axis is the index)
and ``meta.json``, which carries a ``kind`` tag for dispatch, the module that
defines the kind, the result's :class:`~crime.core.metadata.ResultMeta`, and
a run provenance stamp.

Result types opt in by **registering** a save/load pair (see
``crime.esri.ehsa``), so this module never imports analysis code:

    register_artifact("EhsaResult", save_fn, load_fn)

    import crime
    ehsa = crime.cached("outputs/artifacts/ehsa/property",
                        lambda: crime.emerging_hotspots(ds, freq="ME"),
                        key={"freq": "ME", "years": (2022, 2025)})

``key`` (optional) is hashed into ``meta.json``; a cached result whose key
differs is recomputed instead of silently reused.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
from typing import Callable

import geopandas as gpd
import pandas as pd

from crime.core.config import RESULTS_DIR

__all__ = ["save_result", "load_result", "cached", "register_artifact", "RESULTS_DIR"]

#: kind -> (save(obj, dir) -> extra meta dict, load(dir, meta) -> obj, defining module)
_HANDLERS: dict[str, tuple[Callable, Callable, str]] = {}

#: where each built-in kind is defined — lets load_result import it on demand
#: (also covers caches written before ``module`` was stored in meta.json)
_KNOWN_KINDS = {"EhsaResult": "crime.esri.ehsa"}


def register_artifact(kind: str, save: Callable, load: Callable, *, module: str | None = None) -> None:
    """Register how to persist results of type ``kind``."""
    _HANDLERS[kind] = (save, load, module or getattr(save, "__module__", ""))


def _handler(kind: str):
    if kind not in _HANDLERS and kind in _KNOWN_KINDS:
        importlib.import_module(_KNOWN_KINDS[kind])
    if kind not in _HANDLERS:
        raise TypeError(f"no artifact handler for {kind}; have {sorted(_HANDLERS)}")
    return _HANDLERS[kind]


# --------------------------------------------------------------------------- #
#  frame helpers (for handlers)
# --------------------------------------------------------------------------- #
def write_layer(df: pd.DataFrame, path: Path) -> None:
    """Write a unit x period layer (transpose -> datetime index, string cols)."""
    t = df.T
    t.index = t.index.astype(str) if not isinstance(t.index, pd.DatetimeIndex) else t.index
    t.columns = t.columns.astype(str)
    t.to_parquet(path)


def read_layer(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path).T


def save_gdf(gdf: gpd.GeoDataFrame, path: Path) -> None:
    if isinstance(gdf, gpd.GeoDataFrame) and gdf.geometry.notna().any():
        gdf.to_parquet(path)
    else:
        pd.DataFrame(gdf).to_parquet(path.with_suffix(".plain.parquet"))


def load_gdf(path: Path) -> pd.DataFrame:
    plain = path.with_suffix(".plain.parquet")
    return gpd.read_parquet(path) if path.exists() else pd.read_parquet(plain)


def _key_hash(key) -> str | None:
    if key is None:
        return None
    return hashlib.sha256(json.dumps(key, sort_keys=True, default=repr).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
#  public API
# --------------------------------------------------------------------------- #
def save_result(obj, path: str | Path, *, key=None) -> Path:
    """Persist a registered result type to ``path`` (a directory)."""
    from crime.data.provenance import provenance

    kind = type(obj).__name__
    save, _, module = _handler(kind)
    d = Path(path)
    d.mkdir(parents=True, exist_ok=True)
    extra = save(obj, d)
    meta = getattr(obj, "meta", None)
    record = {"kind": kind, "module": module, **extra,
              "result_meta": meta.to_dict() if hasattr(meta, "to_dict") else None,
              "key_hash": _key_hash(key), "provenance": provenance()}
    (d / "meta.json").write_text(json.dumps(record, indent=2, default=str))
    return d


def load_result(path: str | Path):
    """Load whatever :func:`save_result` wrote at ``path``."""
    d = Path(path)
    meta = json.loads((d / "meta.json").read_text())
    if meta.get("module") and meta["kind"] not in _HANDLERS:
        importlib.import_module(meta["module"])
    return _handler(meta["kind"])[1](d, meta)


def cached(path: str | Path, compute, *, key=None):
    """Return the result saved at ``path`` if present (and saved under the same
    ``key``), else ``compute()`` it and save it there."""
    d = Path(path)
    if (d / "meta.json").exists():
        stored = json.loads((d / "meta.json").read_text()).get("key_hash")
        if key is None or stored == _key_hash(key):
            return load_result(d)
    obj = compute()
    save_result(obj, d, key=key)
    return obj
