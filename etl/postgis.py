"""Write DataFrames / GeoDataFrames into pre-existing PostGIS tables.

    from etl.postgis import write_gdf, write_df, assign_unit, wait_for_db, apply_sql
    write_gdf(engine, tracts, "dim_setor_censitario")
    write_df(engine, painel, "dim_setor_painel")

``write_gdf`` uses psycopg2 ``execute_batch`` + ``ST_GeomFromWKB``, bypassing
GeoAlchemy2's ``Find_SRID()`` introspection (which fails on tables created via
raw SQL). ``write_df`` is a plain ``to_sql`` append.
"""
import logging
import time

import geopandas as gpd
import pandas as pd
import psycopg2
from psycopg2.extras import execute_batch
from sqlalchemy import text

log = logging.getLogger("etl")


def wait_for_db(eng, retries: int = 10, delay: float = 3.0) -> None:
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
    with eng.begin() as conn:
        conn.execute(text(sql))


def assign_unit(points: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Point-in-polygon (``within``), first match kept; unmatched points get NaN."""
    joined = gpd.sjoin(points, polygons, how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]
    return joined.drop(columns=["index_right"], errors="ignore")


def _scalar(v):
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def write_gdf(engine, gdf: gpd.GeoDataFrame, table: str, *, srid: int = 4326,
              page_size: int = 1000) -> None:
    non_geom = [c for c in gdf.columns if c != "geometry"]
    sql = (
        f"INSERT INTO {table} ({', '.join(non_geom + ['geometry'])}) "
        f"VALUES ({', '.join(['%s'] * len(non_geom))}, "
        f"ST_SetSRID(ST_GeomFromWKB(%s), {srid}))"
    )
    rows = []
    for _, row in gdf.iterrows():
        geom = row["geometry"]
        wkb = psycopg2.Binary(bytes.fromhex(geom.wkb_hex)) if geom is not None else None
        rows.append([_scalar(row[c]) for c in non_geom] + [wkb])

    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            execute_batch(cur, sql, rows, page_size=page_size)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def write_df(engine, df: pd.DataFrame, table: str) -> None:
    with engine.begin() as conn:
        df.to_sql(table, conn, if_exists="append", index=False)
