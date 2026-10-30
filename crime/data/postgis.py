"""PostGIS data source — the only module that knows table and view names.

``PostGISSource`` implements :class:`crime.core.protocols.DataSource`. Loaders
receive one (``source=``) instead of opening their own connections, so tests
and alternative backends (a parquet snapshot, a fixture) can be injected.

Tables / views read (see ``database/schema.sql`` and ``database/enrich.sql``):

    vw_sector_features, vw_grid_features   one row per unit + model features
    fato_crimes                            one row per geocoded crime
    dim_utb                                planning-unit boundary overlay
    dim_cnefe_enderecos                    CNEFE establishment points
    dim_crime_taxonomy                     slug / group / label
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
from sqlalchemy import text

from crime.core.config import DBConfig, engine
from crime.data.query import CrimeQuery

VIEWS = {"sector": "vw_sector_features", "grid": "vw_grid_features"}
UNIT_COLS = {"sector": "cd_setor", "grid": "grid_id"}


class PostGISSource:
    """Query the project database. One SQLAlchemy engine per source, created
    on first use."""

    def __init__(self, db: DBConfig | None = None, *, engine=None):
        self.db = db
        self._engine = engine

    @classmethod
    def from_settings(cls, settings=None) -> "PostGISSource":
        return cls(settings.db if settings is not None else None)

    @property
    def engine(self):
        if self._engine is None:
            self._engine = engine(self.db)
        return self._engine

    def describe(self, unit: str | None = None) -> str:
        return f"postgis:{VIEWS.get(unit, 'fato_crimes')}"

    # ------------------------------------------------------------ polygon units
    def unit_features(self, unit: str) -> gpd.GeoDataFrame:
        return gpd.read_postgis(f"SELECT * FROM {VIEWS[unit]}", self.engine, geom_col="geometry")

    def unit_counts(self, unit: str, query: CrimeQuery) -> pd.DataFrame:
        col = UNIT_COLS[unit]
        where, params = query.where(f"{col} IS NOT NULL")
        return pd.read_sql(
            text(f"SELECT {col} AS unit_id, COUNT(*) AS crime_count FROM fato_crimes {where} GROUP BY 1"),
            self.engine, params=params,
        )

    def unit_events(self, unit: str, query: CrimeQuery) -> pd.DataFrame:
        col = UNIT_COLS[unit]
        where, params = query.where(f"{col} IS NOT NULL")
        return pd.read_sql(
            text(f"SELECT {col} AS unit_id, data_ocorrencia, hora_ocorrencia, "
                 f"periodo, crime_slug, crime_group FROM fato_crimes {where}"),
            self.engine, params=params, parse_dates=["data_ocorrencia"],
        )

    def overlay(self) -> gpd.GeoDataFrame:
        return gpd.read_postgis("SELECT gid, utb_sigla, geometry FROM dim_utb", self.engine,
                                geom_col="geometry")

    # ------------------------------------------------------------ points
    def crime_points(self, query: CrimeQuery) -> gpd.GeoDataFrame:
        where, params = query.where("lat IS NOT NULL", "long IS NOT NULL")
        return gpd.read_postgis(
            text("SELECT data_ocorrencia, crime_slug, crime_group, cd_setor, grid_id, geometry "
                 f"FROM fato_crimes {where}"),
            self.engine, params=params, geom_col="geometry", parse_dates=["data_ocorrencia"],
        )

    def crime_coordinates(self, query: CrimeQuery) -> pd.DataFrame:
        """Crimes with raw lat/long, for snapping to street segments."""
        where, params = query.where("lat IS NOT NULL AND long IS NOT NULL")
        return pd.read_sql(
            text("SELECT id_crime, data_ocorrencia, hora_ocorrencia, periodo, crime_slug, "
                 f"crime_group, lat, long FROM fato_crimes {where}"),
            self.engine, params=params, parse_dates=["data_ocorrencia"],
        )

    def cnefe_points(self, cod_especie: tuple[int, ...]) -> gpd.GeoDataFrame:
        codes = ", ".join(str(int(c)) for c in cod_especie)
        return gpd.read_postgis(
            f"SELECT cod_especie, geometry FROM dim_cnefe_enderecos WHERE cod_especie IN ({codes})",
            self.engine, geom_col="geometry",
        )

    # ------------------------------------------------------------ tables
    def crime_types(self) -> pd.DataFrame:
        return pd.read_sql(
            "SELECT t.crime_slug, t.crime_group, t.crime_type_label, COUNT(f.id_crime) AS n "
            "FROM dim_crime_taxonomy t LEFT JOIN fato_crimes f USING (crime_slug) "
            "GROUP BY 1, 2, 3 ORDER BY n DESC",
            self.engine,
        )

    def slug_counts_by_unit(self, unit: str, year: int) -> pd.DataFrame:
        """Long ``unit_id, crime_slug, n`` counts for one bulletin year."""
        col = UNIT_COLS[unit]
        return pd.read_sql(
            text(f"SELECT {col} AS unit_id, crime_slug, COUNT(*) AS n "
                 f"FROM fato_crimes WHERE {col} IS NOT NULL AND ano_bo = :year GROUP BY 1, 2"),
            self.engine, params={"year": int(year)},
        )


def describe_source(source, unit: str | None = None) -> str:
    """Provenance string for a DataSource (its ``describe()``, else its type)."""
    describe = getattr(source, "describe", None)
    return describe(unit) if callable(describe) else type(source).__name__


def default_source(db: DBConfig | None = None, source=None):
    """The source a loader should use: an injected one, else PostGIS at ``db``."""
    return source if source is not None else PostGISSource(db)
