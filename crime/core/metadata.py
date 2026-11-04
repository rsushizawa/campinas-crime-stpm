"""``DatasetMeta`` — the header carried by a :class:`crime.core.dataset.Dataset`.

*What was loaded*: spatial support, year window, the crime filter, the CRS
used for distances, and the source it came from. Frozen and
JSON-serialisable via ``to_dict()``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from crime.core.config import CRS_METRIC


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

    unit          : spatial support — ``"sector"`` (warehouse) | ``"tract"`` | ``"utb"``.
    years         : inclusive crime-year window, or ``None`` for all years.
    crime_slug    : crime-type filter (one slug or a tuple), ``None`` = all.
    crime_group   : crime-group filter (``"property"``, ``"violent"`` ...).
    location_type : ``subtipo_local`` filter (e.g. "Via Pública"), ``None`` = all.
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
