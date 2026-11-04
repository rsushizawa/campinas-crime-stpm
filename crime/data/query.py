"""The crime filter, as a value.

``CrimeQuery`` is the one description of *which crimes* a dataset holds —
year window, crime type(s), crime group, location type — and the one place
that turns it into a SQL ``WHERE`` clause. Every value is a bound parameter
(no string interpolation of user input).

    q = CrimeQuery(years=(2022, 2025), crime_slug=["furto_outros", "roubo_outros"])
    sql, params = q.where("cd_setor IS NOT NULL")
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CrimeQuery:
    years: tuple[int, int] | None = None
    crime_slug: str | tuple[str, ...] | None = None
    crime_group: str | None = None
    location_type: str | None = None

    def __post_init__(self):
        if isinstance(self.crime_slug, list):
            object.__setattr__(self, "crime_slug", tuple(self.crime_slug))

    @property
    def slugs(self) -> tuple[str, ...]:
        if not self.crime_slug:
            return ()
        return (self.crime_slug,) if isinstance(self.crime_slug, str) else tuple(self.crime_slug)

    def where(self, *required: str) -> tuple[str, dict]:
        """``("WHERE ...", params)``. ``required`` are fixed leading clauses
        (e.g. ``"lat IS NOT NULL"``). The year window filters on both the
        bulletin year (``ano_bo``) and the occurrence date, so a crime
        reported in January for the previous December is excluded."""
        clauses = list(required)
        params: dict = {}
        if self.years:
            lo, hi = int(self.years[0]), int(self.years[1])
            clauses.append("ano_bo BETWEEN :yr_lo AND :yr_hi")
            clauses.append("data_ocorrencia >= :date_lo AND data_ocorrencia < :date_hi")
            params.update(yr_lo=lo, yr_hi=hi, date_lo=f"{lo}-01-01", date_hi=f"{hi + 1}-01-01")
        if self.slugs:
            clauses.append("crime_slug IN (" + ", ".join(f":slug_{i}" for i in range(len(self.slugs))) + ")")
            params.update({f"slug_{i}": s for i, s in enumerate(self.slugs)})
        if self.crime_group:
            clauses.append("crime_group = :crime_group")
            params["crime_group"] = self.crime_group
        if self.location_type:
            clauses.append("subtipo_local = :location_type")
            params["location_type"] = self.location_type
        return "WHERE " + " AND ".join(clauses), params
