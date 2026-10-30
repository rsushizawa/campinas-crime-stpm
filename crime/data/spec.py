"""Fluent builder for the analytical ``Dataset``.

A thin, chainable wrapper over ``load_sectors`` / ``load_grid``
— useful when sweeping many (scope × crime type × window) combinations and you
want to vary one axis at a time.

    from crime import DatasetSpec

    base = DatasetSpec().years(2022, 2025).crime(group="property").with_events()
    tract   = base.scope("sector").load()
    grid    = base.scope("grid").load()
    vehicle = base.crime(slug="furto_veiculo").load()

Every ``.method()`` returns a new spec (immutable), so a partially-built spec can
be reused as a template. ``.load()`` calls the matching loader; pass
``source=`` (a :class:`~crime.core.protocols.DataSource`) or ``db=`` to point
it at another backend. The loaded Dataset's header records the full spec.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from crime.data.loaders import load_grid, load_sectors

_SCOPES = {"sector", "grid"}


@dataclass(frozen=True)
class DatasetSpec:
    scope_: str = "sector"
    years_: tuple[int, int] | None = None
    slug_: str | list[str] | None = None
    group_: str | None = None
    events_: bool = False
    overlay_: bool = False

    # ---- chainable setters (return a new spec) -------------------------
    def scope(self, scope: str) -> "DatasetSpec":
        if scope not in _SCOPES:
            raise ValueError(f"scope must be one of {sorted(_SCOPES)}")
        return replace(self, scope_=scope)

    def years(self, lo: int, hi: int) -> "DatasetSpec":
        return replace(self, years_=(int(lo), int(hi)))

    def crime(self, *, slug: str | list[str] | None = None,
              group: str | None = None) -> "DatasetSpec":
        return replace(self, slug_=slug, group_=group)

    def with_events(self, on: bool = True) -> "DatasetSpec":
        return replace(self, events_=on)

    def with_overlay(self, on: bool = True) -> "DatasetSpec":
        return replace(self, overlay_=on)

    # ---- terminal --------------------------------------------------------
    def load(self, *, source=None, db=None):
        loader = load_grid if self.scope_ == "grid" else load_sectors
        return loader(
            years=self.years_, crime_slug=self.slug_, crime_group=self.group_,
            events=self.events_, overlay=self.overlay_, source=source, db=db,
        )

    def __repr__(self) -> str:
        bits = [f"scope={self.scope_}"]
        if self.years_:
            bits.append(f"years={self.years_[0]}-{self.years_[1]}")
        if self.slug_:
            bits.append(f"slug={self.slug_}")
        if self.group_:
            bits.append(f"group={self.group_}")
        if self.events_:
            bits.append("events")
        return f"DatasetSpec({', '.join(bits)})"
