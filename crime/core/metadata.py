"""Metadata "headers" carried by data containers and results.

Borrowed from the mrlib ``Dataset`` + XML header design: the numbers travel
with a description of what they are. Two headers:

``DatasetMeta``
    *What was loaded*: spatial support, year window, the crime filter, the CRS
    used for distances, and the source it came from. Attached to every
    :class:`crime.core.dataset.Dataset`.

``ResultMeta``
    *How a result was produced*: the method, its reference, the exact
    parameters, and the ``DatasetMeta`` of the input. Attached to every
    ``*Result``; ``params_hash`` lets the artifact cache detect stale results.

Both are frozen and JSON-serialisable via ``to_dict()``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from crime.core.config import CRS_METRIC

SUPPORTS = ("sector", "grid", "segment")


def _jsonable(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, Mapping):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_jsonable(x) for x in v]
    if hasattr(v, "item"):                      # numpy scalar
        return v.item()
    return repr(v) if not isinstance(v, str) else v


@dataclass(frozen=True)
class DatasetMeta:
    """Header of a :class:`~crime.core.dataset.Dataset`.

    unit          : spatial support — ``"sector"`` | ``"grid"`` | ``"segment"``.
    years         : inclusive crime-year window, or ``None`` for all years.
    crime_slug    : crime-type filter (one slug or a tuple), ``None`` = all.
    crime_group   : crime-group filter (``"property"``, ``"violent"`` ...).
    location_type : ``subtipo_local`` filter (segments default to "Via Pública").
    crs_metric    : projected CRS used for areas, distances and weights.
    source        : where the rows came from (e.g. ``"postgis:vw_sector_features"``).
    """

    unit: str
    years: tuple[int, int] | None = None
    crime_slug: str | tuple[str, ...] | None = None
    crime_group: str | None = None
    location_type: str | None = None
    crs_metric: str = CRS_METRIC
    source: str | None = None

    def __post_init__(self):
        if isinstance(self.crime_slug, list):
            object.__setattr__(self, "crime_slug", tuple(self.crime_slug))
        if self.years is not None:
            object.__setattr__(self, "years", (int(self.years[0]), int(self.years[1])))

    def describe(self) -> str:
        bits = [self.unit]
        if self.years:
            bits.append(f"{self.years[0]}–{self.years[1]}")
        if self.crime_slug:
            s = self.crime_slug
            bits.append("slug=" + (s if isinstance(s, str) else "+".join(s)))
        if self.crime_group:
            bits.append(f"group={self.crime_group}")
        if self.location_type:
            bits.append(f"location={self.location_type}")
        return ", ".join(bits)

    def to_dict(self) -> dict:
        return _jsonable(asdict(self))


class FrozenParams(dict):
    """A read-only, picklable dict for :attr:`ResultMeta.params`."""

    def _readonly(self, *args, **kwargs):
        raise TypeError("ResultMeta.params is read-only; build a new ResultMeta instead")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _readonly
    __ior__ = _readonly

    def __reduce__(self):
        return (type(self), (dict(self),))


@dataclass(frozen=True)
class ResultMeta:
    """Header of an analysis result.

    method    : short method name, e.g. ``"Getis-Ord Gi*"``.
    reference : citation(s) the implementation follows.
    params    : every parameter that affects the numbers.
    dataset   : the input's :class:`DatasetMeta` (``None`` for matrix inputs).
    """

    method: str
    reference: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)
    dataset: DatasetMeta | None = None

    def __post_init__(self):
        object.__setattr__(self, "params", FrozenParams(self.params))

    @property
    def params_hash(self) -> str:
        blob = json.dumps({"method": self.method, "params": _jsonable(self.params),
                           "dataset": self.dataset.to_dict() if self.dataset else None},
                          sort_keys=True, default=repr)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "reference": self.reference,
            "params": _jsonable(self.params),
            "dataset": self.dataset.to_dict() if self.dataset else None,
            "params_hash": self.params_hash,
        }

    @classmethod
    def from_dict(cls, d: Mapping) -> "ResultMeta":
        ds = d.get("dataset")
        if ds is not None:
            ds = DatasetMeta(**{**ds, "years": tuple(ds["years"]) if ds.get("years") else None})
        return cls(method=d["method"], reference=d.get("reference", ""),
                   params=d.get("params", {}), dataset=ds)


def dataset_meta_of(obj) -> DatasetMeta | None:
    """The ``DatasetMeta`` of a Dataset-like object, or ``None``."""
    return getattr(obj, "meta", None) if isinstance(getattr(obj, "meta", None), DatasetMeta) else None
