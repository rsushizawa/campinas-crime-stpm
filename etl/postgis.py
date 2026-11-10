"""Small PostGIS and spatial-join helpers shared by the stages.

    from etl.postgis import assign_unit, wait_for_db, apply_sql

The bulk writes are in :mod:`etl.load`.
"""
import logging
import time

import geopandas as gpd

log = logging.getLogger("etl")


# psycopg2 / SQLAlchemy (the `db` extra) are imported inside the DB functions, so
# assign_unit (used by the database-free clean stage) works without them.


def wait_for_db(eng, retries: int = 10, delay: float = 3.0) -> None:
    from sqlalchemy import text

    for attempt in range(1, retries + 1):
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            log.info("waiting for database… (%d/%d) %s", attempt, retries, exc)
            time.sleep(delay)
    raise RuntimeError("database did not become ready in time")


def apply_sql(eng, sql: str) -> None:
    from sqlalchemy import text

    with eng.begin() as conn:
        conn.execute(text(sql))


def assign_unit(points: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Point-in-polygon including boundaries; lowest polygon index resolves shared edges."""
    joined = gpd.sjoin(points, polygons, how="left", predicate="covered_by")
    joined = joined.sort_values("index_right", kind="stable")
    joined = joined[~joined.index.duplicated(keep="first")].reindex(points.index)
    return joined.drop(columns=["index_right"], errors="ignore")
