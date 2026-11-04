"""PostGIS warehouse loaders (need the ``db`` extra and ``make db``).

The notebooks do **not** need these: they use the parquet-backed API in
:mod:`crime.data.api` (``load_points`` / ``load_units`` / ``unit_counts``).
These loaders read the warehouse built by ``scripts/02_clean/load_database.py``
(``database/schema.sql`` + ``database/enrich.sql``).

    from crime.data.loaders import load_sectors
    ds = load_sectors(years=(2022, 2025), crime_group="property", events=True)

``load_sectors`` returns a :class:`~crime.core.dataset.Dataset` whose header
(:class:`~crime.core.metadata.DatasetMeta`) records the support and the crime
filter; the support is the 2022 IBGE census tract (``vw_sector_features``).

Derived columns added at load time on polygon supports:
    ``crime_rate``     crimes per 1,000 residents (NaN where population is 0)
    ``crime_rate_eb``  Empirical-Bayes smoothed rate per 1,000 — shrinks
                       small-population tract rates toward the global mean
                       (Clayton & Kaldor 1987; PySAL ``esda.smoothing.Empirical_Bayes``).

Every loader takes ``source=`` (an object with the
:class:`~crime.data.postgis.PostGISSource` methods, e.g. a test fixture) or
``db=`` (a :class:`~crime.core.config.DBConfig`).
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from crime.core.config import DBConfig
from crime.core.dataset import Dataset
from crime.core.metadata import DatasetMeta
from crime.data.postgis import default_source, describe_source
from crime.data.query import CrimeQuery


# --------------------------------------------------------------------------- #
#  Census-sector dataset
# --------------------------------------------------------------------------- #
def load_sectors(
    *,
    years: tuple[int, int] | None = None,
    crime_slug: str | list[str] | None = None,
    crime_group: str | None = None,
    events: bool = False,
    overlay: bool = False,
    db: DBConfig | None = None,
    source=None,
) -> Dataset:
    """Census-tract dataset from ``vw_sector_features`` + ``fato_crimes`` counts."""
    return load_polygons("sector", CrimeQuery(years, crime_slug, crime_group),
                         events=events, overlay=overlay, source=default_source(db, source))


def load_polygons(unit: str, query: CrimeQuery, *, events: bool, overlay: bool, source) -> Dataset:
    """Body of :func:`load_sectors` (``unit`` = a key of ``postgis.VIEWS``)."""
    gdf = source.unit_features(unit)
    gdf = gdf.merge(source.unit_counts(unit, query), on="unit_id", how="left")
    gdf["crime_count"] = gdf["crime_count"].fillna(0).astype(int)

    pop = gdf["pop_total"].where(gdf["pop_total"] > 0)
    gdf["crime_rate"] = 1000.0 * gdf["crime_count"] / pop
    gdf["crime_rate_eb"] = eb_rate(gdf["crime_count"], pop)

    meta = DatasetMeta(unit=unit, years=query.years, crime_slug=query.crime_slug,
                       crime_group=query.crime_group, source=describe_source(source, unit))
    return Dataset(
        gdf=gdf, unit=unit, years=meta.years,
        events=source.unit_events(unit, query) if events else None,
        overlay=source.overlay() if overlay else None,
        meta=meta,
    )


def crime_types(db: DBConfig | None = None, *, source=None) -> pd.DataFrame:
    """slug / group / label / count listing from ``dim_crime_taxonomy``."""
    return default_source(db, source).crime_types()


def load_crime_points(
    *,
    years: tuple[int, int] | None = None,
    crime_slug: str | list[str] | None = None,
    crime_group: str | None = None,
    location_type: str | None = None,
    db: DBConfig | None = None,
    source=None,
) -> gpd.GeoDataFrame:
    """Geocoded crime occurrences as points (EPSG:4326) — for point-pattern
    analyses and maps.

    Columns: ``geometry``, ``data_ocorrencia``, ``crime_slug``, ``crime_group``,
    ``cd_setor``.
    """
    return default_source(db, source).crime_points(
        CrimeQuery(years, crime_slug, crime_group, location_type))


def load_cnefe_points(
    *, cod_especie: tuple[int, ...] = (4, 5, 6, 8), db: DBConfig | None = None, source=None,
) -> gpd.GeoDataFrame:
    """CNEFE establishment points (EPSG:4326) by ``cod_especie`` — the local
    land-use signal for buffer zonal statistics. Defaults to the four
    establishment classes used elsewhere: 4 education, 5 health, 6 commerce,
    8 religious."""
    return default_source(db, source).cnefe_points(cod_especie)


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #
def eb_rate(counts: pd.Series, pop: pd.Series) -> pd.Series:
    """Empirical-Bayes rate per 1,000 (global shrinkage; Clayton & Kaldor 1987)."""
    from esda.smoothing import Empirical_Bayes

    valid = pop.notna()
    out = pd.Series(pd.NA, index=counts.index, dtype="Float64")
    out[valid] = 1000.0 * Empirical_Bayes(
        counts[valid].to_numpy(dtype=float), pop[valid].to_numpy(dtype=float)
    ).r
    return out

