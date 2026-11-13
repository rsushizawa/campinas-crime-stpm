"""Read the PostGIS warehouse: the only way the notebooks get data.

    from crime.query import CrimeQuery
    from crime.warehouse import Warehouse
    wh = Warehouse()                                   # fails if the database is not running
    cube = wh.counts(CrimeQuery(crime_group="property", time_unit="quarter"))
    tracts = wh.census_tracts()
    pts = wh.bulletins(CrimeQuery(crime_group="drug"))

:meth:`Warehouse.counts` returns a long table: one row per spatial unit and
time bin, zero-filled, with the unit's attributes and geometry. Units come in
``census_tract_id`` order and bins in time order, so the rows are in the same
order on every call. Every frame is in EPSG:31983 (metres).

Two checks run when a :class:`Warehouse` is created. If the database cannot
be reached, :class:`WarehouseNotRunning` tells you how to start and load it
(rule 26). If the release in the database was built with another schema
version than this package expects, :class:`WarehouseVersionError` stops the
read (rule 27).

SQL runs through SQLAlchemy; geometries are read with
:func:`geopandas.read_postgis`.
"""
from __future__ import annotations

import datetime as dt
import json

import geopandas as gpd
import pandas as pd

from crime.config import CRS_METRIC, SCHEMA_VERSION, DBConfig, engine
from crime.errors import WarehouseError
from crime.query import CrimeQuery

#: Columns of :meth:`Warehouse.census_tracts`, in order (``geometry`` last).
TRACT_COLUMNS = ["census_tract_id", "district", "situation", "area_km2", "population", "households",
                 "income_head_mean", "income_head_median", "literate_15_plus", "illiterate_15_plus",
                 "literacy_rate", "n_commercial", "n_education", "n_health", "n_religious"]

#: Keys of a funnel row, in order.
FUNNEL_KEYS = ("stage", "all", "property", "definition")

_BIN = {"month": "month_start", "quarter": "quarter_start", "year": "year_start"}
_FREQ = {"month": "MS", "quarter": "QS", "year": "YS"}


class WarehouseNotRunning(WarehouseError, RuntimeError):
    """The database is unreachable or holds no loaded release."""


class WarehouseVersionError(WarehouseError, RuntimeError):
    """The loaded release was built with another schema version."""


class Warehouse:
    """Connection to the warehouse and the queries the notebooks use.

    Parameters
    ----------
    db : DBConfig, optional
        Connection settings; defaults to the ``PG*`` environment variables and
        ``.env`` (:class:`crime.config.DBConfig`).

    Raises
    ------
    WarehouseNotRunning
        The database does not answer, or no release has been loaded.
    WarehouseVersionError
        ``build.schema_version`` differs from :data:`crime.config.SCHEMA_VERSION`.
    """

    def __init__(self, db: DBConfig | None = None) -> None:
        from sqlalchemy import text
        from sqlalchemy.exc import OperationalError, ProgrammingError

        self.db = db or DBConfig()
        self.engine = engine(self.db)
        where = f"{self.db.host}:{self.db.port}/{self.db.database}"
        try:
            with self.engine.connect() as conn:
                row = conn.execute(text("SELECT data_version, schema_version, code_commit, built_at FROM build")).one_or_none()
        except OperationalError as exc:
            raise WarehouseNotRunning(
                f"The warehouse at {where} is not reachable. Start it with `a configured PostGIS server`, then build it with "
                "`the guided notebook warehouse setup` (run acquisition, cleaning and unit preparation first; see README.md).") from exc
        except ProgrammingError as exc:
            raise WarehouseNotRunning(
                f"The database at {where} is running but holds no loaded release. Run `the guided notebook warehouse setup`.") from exc
        if row is None:          # schema applied but the load did not finish (the build row is written last)
            raise WarehouseNotRunning(
                f"The database at {where} holds an unfinished load (no build row). Run `the guided notebook warehouse setup`.")
        self.data_version, schema, self.code_commit, self.built_at = row
        if schema != SCHEMA_VERSION:
            raise WarehouseVersionError(
                f"The warehouse holds data-v{self.data_version} built with schema {schema}; this package "
                f"reads schema {SCHEMA_VERSION}. Rebuild it with `the guided notebook warehouse setup`.")

    def __repr__(self) -> str:
        return (f"Warehouse(data-v{self.data_version}, commit {self.code_commit[:7]}, "
                f"built {self.built_at:%Y-%m-%d %H:%M}, {self.db.host}:{self.db.port}/{self.db.database})")

    def close(self) -> None:
        """Release this reader's database connection pool."""
        self.engine.dispose()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    # ------------------------------------------------------------------ helpers
    def _sql(self, sql: str, params: dict | None = None, **kw) -> pd.DataFrame:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            return pd.read_sql(text(sql), conn, params=params or {}, **kw)

    def _geo(self, sql: str, params: dict | None = None) -> gpd.GeoDataFrame:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            return gpd.read_postgis(text(sql), conn, params=params or {}, geom_col="geometry", crs=CRS_METRIC)

    @staticmethod
    def _where(q: CrimeQuery) -> tuple[str, dict]:
        """SQL ``WHERE`` clause and bind parameters for the bulletin filter of ``q``.

        Parameters
        ----------
        q : CrimeQuery

        Returns
        -------
        where : str
            Conditions on the aliases ``b`` (``fact_bulletin``) and ``o`` (``dim_offence``).
            Only fixed column names appear in the text; every user value is a bind parameter.
        params : dict
        """
        clauses = ["b.occurrence_date BETWEEN :start AND :end"]
        params: dict = {"start": q.start, "end": q.end}
        if q.crime_group != "all":
            clauses.append("o.crime_group = :crime_group")
            params["crime_group"] = q.crime_group
        if q.crime_slug:
            clauses.append("b.crime_slug = ANY(:crime_slug)")
            params["crime_slug"] = list(q.crime_slug)
        if q.location_type:
            clauses.append("b.location_type = ANY(:location_type)")
            params["location_type"] = list(q.location_type)
        if q.unit == "census_tract":
            clauses.append("b.census_tract_id IS NOT NULL")
        return " AND ".join(clauses), params

    def _check_location_types(self, q: CrimeQuery) -> None:
        """Raise ``ValueError`` for a location type that no bulletin has (a typo would
        otherwise return all-zero counts)."""
        if not q.location_type:
            return
        known = set(self._sql("SELECT DISTINCT location_type FROM fact_bulletin "
                              "WHERE location_type IS NOT NULL")["location_type"])
        unknown = sorted(set(q.location_type) - known)
        if unknown:
            raise ValueError(f"unknown location_type {unknown}; see SELECT DISTINCT location_type FROM fact_bulletin")

    def _bins(self, q: CrimeQuery) -> pd.DatetimeIndex:
        """Start of every time bin of ``q`` (one bin, ``q.start``, for ``"total"``)."""
        if q.time_unit == "total":
            return pd.DatetimeIndex([pd.Timestamp(q.start)], name="period_start")
        first = pd.Timestamp(q.start).to_period(_FREQ[q.time_unit][0]).to_timestamp()
        return pd.date_range(first, pd.Timestamp(q.end), freq=_FREQ[q.time_unit], name="period_start")

    # ------------------------------------------------------------------ units
    def census_tracts(self) -> gpd.GeoDataFrame:
        """The 2,592 IBGE 2022 census tracts with their 2022 attributes.

        Returns
        -------
        GeoDataFrame
            :data:`TRACT_COLUMNS` and ``geometry``, ordered by
            ``census_tract_id``. Attribute definitions: ``etl/census.py`` and
            the column comments of ``dim_census_tract``.
        """
        cols = ", ".join(TRACT_COLUMNS)
        return self._geo(f"SELECT {cols}, geometry FROM dim_census_tract ORDER BY census_tract_id COLLATE \"C\"")

    # ------------------------------------------------------------------ counts
    def counts(self, q: CrimeQuery | None = None) -> gpd.GeoDataFrame:
        """Bulletin counts per spatial unit and time bin (long format, zero-filled).

        Parameters
        ----------
        q : CrimeQuery, optional
            Default ``CrimeQuery()``: all groups, per tract, 2022-2025 total.

        Returns
        -------
        GeoDataFrame
            ``unit="census_tract"``: one row per tract and bin, columns
            ``census_tract_id``, ``period_start``, ``count``, the tract
            attributes and ``geometry``, ordered by tract then bin. A request
            that matches no bulletin still returns every row, with count 0
            (rule 29).
            ``unit="city"``: one row per bin, columns ``period_start`` and
            ``count``, counting every bulletin in the window whether geocoded
            or not; ``geometry`` is empty.
        """
        q = q or CrimeQuery()
        self._check_location_types(q)
        where, params = self._where(q)
        bin_col = "CAST(:start AS date)" if q.time_unit == "total" else f"d.{_BIN[q.time_unit]}"
        unit_col = "b.census_tract_id" if q.unit == "census_tract" else "'Campinas'"
        sql = (f"SELECT {unit_col} AS unit, {bin_col} AS period_start, COUNT(*) AS count "
               "FROM fact_bulletin b JOIN dim_offence o USING (crime_slug) "
               "JOIN dim_date d ON d.date = b.occurrence_date "
               f"WHERE {where} GROUP BY 1, 2")
        raw = self._sql(sql, params, parse_dates=["period_start"])
        bins = self._bins(q)
        if q.unit == "city":
            s = raw.set_index("period_start")["count"].reindex(bins, fill_value=0).astype(int)
            return gpd.GeoDataFrame({"period_start": bins, "count": s.to_numpy()},
                                    geometry=gpd.GeoSeries([None] * len(bins), crs=CRS_METRIC))
        tracts = self.census_tracts()
        full = pd.MultiIndex.from_product([tracts["census_tract_id"], bins], names=["census_tract_id", "period_start"])
        c = (raw.rename(columns={"unit": "census_tract_id"}).set_index(["census_tract_id", "period_start"])["count"]
             .reindex(full, fill_value=0).astype(int).reset_index())
        out = c.merge(tracts, on="census_tract_id", how="left", sort=False)
        return gpd.GeoDataFrame(out, geometry="geometry", crs=CRS_METRIC)

    # ------------------------------------------------------------------ bulletins
    def bulletins(self, q: CrimeQuery | None = None) -> gpd.GeoDataFrame:
        """The bulletins ``q`` selects, one row each.

        With ``unit="census_tract"`` (default) only the spatial event set is
        returned (bulletins geocoded inside a tract); with ``unit="city"`` every
        bulletin in the window, with an empty geometry where there is no
        usable coordinate. ``time_unit`` is ignored here.

        Returns
        -------
        GeoDataFrame
            ``bulletin_id``, ``occurrence_date``, ``occurrence_time``,
            ``registration_date``, ``period_of_day``, ``location_type``,
            ``crime_slug``, ``crime_group``, ``coord_status``, ``latitude``,
            ``longitude``, ``census_tract_id``, ``geometry``; ordered by
            ``bulletin_id`` (byte order).
        """
        q = q or CrimeQuery()
        self._check_location_types(q)
        where, params = self._where(q)
        sql = ("SELECT b.bulletin_id, b.occurrence_date, b.occurrence_time, b.registration_date, "
               "b.period_of_day, b.location_type, b.crime_slug, o.crime_group, b.coord_status, "
               "b.latitude, b.longitude, b.census_tract_id, b.geometry "
               "FROM fact_bulletin b JOIN dim_offence o USING (crime_slug) "
               f"WHERE {where} ORDER BY b.bulletin_id COLLATE \"C\"")
        g = self._geo(sql, params)
        g["occurrence_date"] = pd.to_datetime(g["occurrence_date"])
        g["registration_date"] = pd.to_datetime(g["registration_date"])
        g["occurrence_time"] = g["occurrence_time"].map(lambda t: t.strftime("%H:%M") if isinstance(t, dt.time) else None)
        return g

    def poi(self) -> gpd.GeoDataFrame:
        """CNEFE 2022 points of interest: ``address_id``, ``poi_type_code``, ``poi_type``,
        ``census_tract_id``, ``geometry``, ordered by address and type."""
        return self._geo("SELECT address_id, poi_type_code, poi_type, census_tract_id, geometry "
                         "FROM poi ORDER BY address_id COLLATE \"C\", poi_type_code")

    # ------------------------------------------------------------------ release
    def build(self) -> dict:
        """The ``build`` row: release version, code commit, raw-input checksums, funnel, stage reports."""
        row = self._sql("SELECT * FROM build").iloc[0].to_dict()
        for k in ("raw_inputs", "funnel", "stage_reports"):
            if isinstance(row[k], str):
                row[k] = json.loads(row[k])
        # JSONB keeps object keys in its own order; give the funnel rows their documented order
        row["funnel"] = [{k: r[k] for k in FUNNEL_KEYS} for r in row["funnel"]]
        return row

    def rejects(self, rule: str | None = None) -> pd.DataFrame:
        """Rows of the ``reject`` table, optionally for one rule number."""
        sql = "SELECT stage, step, rule, record_key, reason, record FROM reject"
        params = {}
        if rule is not None:
            sql += " WHERE rule = :rule"
            params["rule"] = rule
        return self._sql(sql + " ORDER BY reject_id", params)


def funnel(wh_engine) -> list[dict]:
    """Rows at every cleaning stage, recomputed from the warehouse tables.

    Offence records = bulletins + records merged by rule 9; bulletins =
    in-window bulletins + those rule 12 removed; in-window bulletins =
    ``fact_bulletin`` + those rule 13 removed when it runs as ``exclude``.

    Parameters
    ----------
    wh_engine : sqlalchemy.engine.Engine
        Engine of a loaded warehouse.

    Returns
    -------
    list of dict
        One dict per stage with :data:`FUNNEL_KEYS`; counts for all groups and
        for ``property``. Stage names and definitions are the paper's.
    """
    from sqlalchemy import text

    with wh_engine.connect() as conn:
        def one(sql):
            return conn.execute(text(sql)).one()

        fact = one("SELECT COUNT(*), COUNT(*) FILTER (WHERE o.crime_group = 'property') "
                   "FROM fact_bulletin b JOIN dim_offence o USING (crime_slug)")
        usable = one("SELECT COUNT(*), COUNT(*) FILTER (WHERE o.crime_group = 'property') "
                     "FROM fact_bulletin b JOIN dim_offence o USING (crime_slug) "
                     "WHERE b.coord_status IN ('ok', 'fixed_decimal')")
        tract = one("SELECT COUNT(*), COUNT(*) FILTER (WHERE o.crime_group = 'property') "
                    "FROM fact_bulletin b JOIN dim_offence o USING (crime_slug) WHERE b.census_tract_id IS NOT NULL")
        rej = {r[0]: (r[1], r[2]) for r in conn.execute(text(
            "SELECT rule, COUNT(*), COUNT(*) FILTER (WHERE record->>'crime_group' = 'property') "
            "FROM reject WHERE rule IN ('9', '12', '13') GROUP BY rule")).all()}
    r9, r12, r13 = (rej.get(k, (0, 0)) for k in ("9", "12", "13"))
    in_window = (fact[0] + r13[0], fact[1] + r13[1])
    bulletins = (in_window[0] + r12[0], in_window[1] + r12[1])
    records = (bulletins[0] + r9[0], bulletins[1] + r9[1])

    def row(stage, n, definition):
        return {"stage": stage, "all": int(n[0]), "property": int(n[1]), "definition": definition}

    return [
        row("offence records (acquired CSV)", records,
            "outputs/data/crimes_campinas.csv; property = record's own offence is property"),
        row("bulletins (one row per NUM_BO+ANO_BO+NOME_DELEGACIA)", bulletins,
            "kept offence = highest maximum penalty (etl/clean.py)"),
        row("occurrence date in window", in_window, "DATA_OCORRENCIA_BO in [2022-01-01, 2025-12-31]"),
        row("... with a usable coordinate", usable, "COORD_STATUS in {ok, fixed_decimal}"),
        row("... inside a 2022 Campinas tract (cube input)", tract, "point within a tract polygon"),
    ]
