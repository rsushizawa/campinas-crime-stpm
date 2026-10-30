"""Slip-map context tiles under the static maps (needs ``contextily``).

Providers are looked up in a small **registry** so a caller can add or
override a named basemap without editing this module:

    from crime.viz.basemap import register_basemap
    import contextily as cx
    register_basemap("toner", lambda: cx.providers.Stadia.StamenTonerLite)

Built-in names: ``"gray"`` (Esri light canvas, default), ``"streets"``,
``"satellite"``, ``"positron"``, ``"osm"``. Providers change their access
policy often — when the requested one fails, the ``FALLBACKS`` chain is tried
in order, and the map is drawn without tiles if none is reachable.
"""
from __future__ import annotations

from typing import Callable


def _cx():
    import contextily as cx

    return cx


#: name -> zero-arg callable returning a contextily provider (lazy: no import at load)
_PROVIDERS: dict[str, Callable[[], object]] = {
    "gray": lambda: _cx().providers.Esri.WorldGrayCanvas,
    "streets": lambda: _cx().providers.Esri.WorldStreetMap,
    "satellite": lambda: _cx().providers.Esri.WorldImagery,
    "positron": lambda: _cx().providers.CartoDB.PositronNoLabels,
    "osm": lambda: _cx().providers.OpenStreetMap.DE,
}

#: tried in order after the requested provider fails
FALLBACKS = ("gray", "positron", "osm")


def register_basemap(name: str, provider) -> None:
    """Register ``name`` -> a contextily provider object (or a zero-arg callable
    returning one)."""
    _PROVIDERS[name] = provider if callable(provider) and not hasattr(provider, "build_url") \
        else (lambda p=provider: p)


def basemap_provider(source):
    """Resolve a registered name to its provider; any other value (e.g. a
    ``contextily.providers`` object) is returned unchanged."""
    return _PROVIDERS[source]() if isinstance(source, str) and source in _PROVIDERS else source


def add_basemap(ax, gdf, *, source: str = "gray", alpha: float = 1.0, zoom="auto"):
    """Slip-map context tiles under an existing map axis.

    ``source`` — a registered name or any ``contextily.providers`` object.
    Call *after* plotting the data and setting the extent; keep the data layer
    semi-transparent so the basemap shows."""
    cx = _cx()
    chain = [basemap_provider(source), *(basemap_provider(n) for n in FALLBACKS)]
    crs = getattr(ax, "_crime_crs", None) or getattr(gdf, "crs", None)
    for i, src in enumerate(chain):
        try:
            cx.add_basemap(ax, crs=crs, source=src, alpha=alpha, zoom=zoom, attribution_size=6)
            return ax
        except Exception as exc:  # noqa: BLE001 — provider blocked / needs a key
            if i == 0:
                print(f"basemap '{source}' unavailable ({str(exc)[:80]}); trying fallbacks")
    print("no basemap provider reachable — drawing without tiles")
    return ax
