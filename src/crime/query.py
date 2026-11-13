"""The request a notebook sends to the warehouse.

    from crime.query import CrimeQuery
    q = CrimeQuery(crime_group="property", time_unit="quarter")

A :class:`CrimeQuery` names *which* bulletins to count (crime group, offence
slugs, location types, period) and *how* to aggregate them (spatial unit,
time unit). Validation is done by pydantic: an unknown group, a slug outside
the group, a period outside the study window or an unknown time unit raise
:class:`pydantic.ValidationError` before any database call (rule 28).

References
----------
pydantic documentation, "Models": https://docs.pydantic.dev/latest/concepts/models/
"""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import ConfigDict, field_validator, model_validator
from pydantic.dataclasses import dataclass

from crime.config import DATE_END, DATE_START

CrimeGroup = Literal["all", "property", "bodily_harm", "traffic", "drug", "violent", "sexual"]
SpatialUnit = Literal["census_tract", "city"]
TimeUnit = Literal["total", "month", "quarter", "year"]

#: Groups with published locations: the spatial analyses use these ("all" is their union).
SPATIAL_GROUPS: tuple[str, ...] = ("all", "property", "bodily_harm", "traffic", "drug", "violent")
#: Every group of the monthly series; ``sexual`` has no coordinates.
TEMPORAL_GROUPS: tuple[str, ...] = (*SPATIAL_GROUPS, "sexual")


@dataclass(frozen=True, config=ConfigDict(extra='forbid'))
class CrimeQuery:
    """Which bulletins to count and how to aggregate them.

    Parameters
    ----------
    crime_group : str, default "all"
        One of :data:`TEMPORAL_GROUPS`. ``"all"`` is every group.
    crime_slug : tuple of str, optional
        Restrict to these offence slugs (``dim_offence.crime_slug``). Each must
        belong to ``crime_group`` unless the group is ``"all"``.
    location_type : tuple of str, optional
        Restrict to these location types (``fact_bulletin.location_type``, the
        published ``DESCR_SUBTIPOLOCAL`` text).
    start, end : date
        Occurrence-date period, both ends included; must lie in the study
        window 2022-01-01 to 2025-12-31 (the default).
    unit : {"census_tract", "city"}, default "census_tract"
        ``"census_tract"`` counts the spatial event set (bulletins geocoded
        inside a 2022 tract) per tract. ``"city"`` counts every bulletin in the
        window, geocoded or not, as one series for Campinas.
    time_unit : {"total", "month", "quarter", "year"}, default "total"
        Width of the time bins. ``"total"`` is one bin for the whole period.

    Examples
    --------
    >>> CrimeQuery(crime_group="property", time_unit="quarter")
    >>> CrimeQuery(crime_group="all", unit="city", time_unit="month")
    >>> CrimeQuery(crime_slug=("furto_veiculo", "roubo_veiculo"))
    """

    crime_group: CrimeGroup = "all"
    crime_slug: tuple[str, ...] | None = None
    location_type: tuple[str, ...] | None = None
    start: dt.date = dt.date.fromisoformat(DATE_START)
    end: dt.date = dt.date.fromisoformat(DATE_END)
    unit: SpatialUnit = "census_tract"
    time_unit: TimeUnit = "total"

    @field_validator("crime_slug", "location_type", mode="before")
    @classmethod
    def _one_or_many(cls, v):
        return (v,) if isinstance(v, str) else v

    @field_validator("crime_slug")
    @classmethod
    def _known_slugs(cls, v):
        if v is None:
            return v
        from crime.taxonomy import SLUG_TO_GROUP

        unknown = sorted(set(v) - set(SLUG_TO_GROUP))
        if unknown:
            raise ValueError(f"unknown crime_slug {unknown}; see dim_offence")
        return tuple(sorted(set(v)))

    @model_validator(mode="after")
    def _consistent(self):
        lo, hi = dt.date.fromisoformat(DATE_START), dt.date.fromisoformat(DATE_END)
        if not lo <= self.start <= self.end <= hi:
            raise ValueError(f"need {lo} <= start <= end <= {hi}, got {self.start} .. {self.end}")
        if self.crime_slug and self.crime_group != "all":
            from crime.taxonomy import SLUG_TO_GROUP

            other = [s for s in self.crime_slug if SLUG_TO_GROUP[s] != self.crime_group]
            if other:
                raise ValueError(f"crime_slug {other} not in crime_group {self.crime_group!r}")
        if self.unit == "census_tract" and self.crime_group == "sexual":
            raise ValueError("sexual bulletins have no published coordinates; use unit='city'")
        return self
