"""Rebuild the IC-Crime PostGIS database, top to bottom.

    python scripts/02_clean/load_database.py              # uses PG* env vars / defaults
    python scripts/02_clean/load_database.py --database crime_db --user admin --password ...

Linear pipeline (no factory, no orchestrator class):
  schema reset -> dimension loads -> spatial joins -> fact load -> enrich.sql

The fact table ``fato_crimes`` is loaded from the cleaned bulletins
(``outputs/data/bulletins_clean.parquet``, one row per bulletin) written by
``scripts/02_clean/clean_bulletins.py``; only rows with a usable coordinate
(``COORD_STATUS`` ok / fixed_decimal) are loaded.
"""
import argparse
import logging

import geopandas as gpd

from crime.core.config import REPO_ROOT, DBConfig, engine
from etl import sources, taxonomy
from etl.postgis import apply_sql, assign_unit, wait_for_db, write_df, write_gdf

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
log = logging.getLogger("etl")

_SQL_DIR = REPO_ROOT / "database"


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild the IC-Crime PostGIS database.")
    d = DBConfig()
    ap.add_argument("--host", default=d.host)
    ap.add_argument("--port", type=int, default=d.port)
    ap.add_argument("--database", default=d.database)
    ap.add_argument("--user", default=d.user)
    ap.add_argument("--password", default=d.password)
    args = ap.parse_args()
    eng = engine(DBConfig(**vars(args)))

    wait_for_db(eng)
    log.info("resetting schema")
    apply_sql(eng, (_SQL_DIR / "schema.sql").read_text())

    # --- dimensions -------------------------------------------------------- #
    tracts = sources.extract_census_tracts()
    censo = sources.extract_census_2022()
    tracts = tracts.merge(censo, on="cd_setor", how="left")
    write_gdf(eng, tracts, "dim_setor_censitario")
    log.info("dim_setor_censitario: %d rows (%d with 2022 population)",
             len(tracts), int(tracts["populacao_total"].notna().sum()))

    grid = sources.extract_grid(boundary=tracts)
    write_gdf(eng, grid, "dim_grid_cell")
    log.info("dim_grid_cell: %d rows", len(grid))

    utb = sources.extract_utb()
    write_gdf(eng, utb, "dim_utb")
    log.info("dim_utb: %d rows", len(utb))

    painel = sources.extract_literacy()
    painel = painel[painel["cd_setor"].isin(set(tracts["cd_setor"]))]
    write_df(eng, painel, "dim_setor_painel")
    log.info("dim_setor_painel: %d rows", len(painel))

    tax = taxonomy.taxonomy_rows()
    write_df(eng, tax, "dim_crime_taxonomy")
    log.info("dim_crime_taxonomy: %d rows", len(tax))

    cnefe = sources.extract_cnefe()
    cnefe = assign_unit(cnefe, grid[["grid_id", "geometry"]])
    write_gdf(eng, cnefe, "dim_cnefe_enderecos", page_size=2000)
    log.info("dim_cnefe_enderecos: %d rows", len(cnefe))

    # --- fact ------------------------------------------------------------- #
    crimes = sources.extract_bulletins()
    # cd_setor from the clean stage is recomputed here with the same rule, alongside grid_id
    geocoded = crimes.dropna(subset=["LATITUDE", "LONGITUDE"]).drop(columns=["cd_setor"]).copy()
    gdf = gpd.GeoDataFrame(
        geocoded,
        geometry=gpd.points_from_xy(geocoded["LONGITUDE"], geocoded["LATITUDE"]),
        crs="EPSG:4326",
    )
    gdf = assign_unit(gdf, tracts[["cd_setor", "geometry"]])
    gdf = assign_unit(gdf, grid[["grid_id", "geometry"]])

    fato = gdf[[
        "NUM_BO", "ANO_BO", "NOME_DELEGACIA", "DATA_OCORRENCIA_BO", "HORA_OCORRENCIA_BO", "DESC_PERIODO",
        "DESCR_SUBTIPOLOCAL", "BAIRRO", "NATUREZA_APURADA", "crime_slug", "crime_group",
        "LATITUDE", "LONGITUDE", "geometry", "cd_setor", "grid_id",
    ]].rename(columns={
        "NUM_BO": "num_bo", "ANO_BO": "ano_bo", "NOME_DELEGACIA": "nome_delegacia", "DATA_OCORRENCIA_BO": "data_ocorrencia",
        "HORA_OCORRENCIA_BO": "hora_ocorrencia", "DESC_PERIODO": "periodo",
        "DESCR_SUBTIPOLOCAL": "subtipo_local", "BAIRRO": "nm_bairro",
        "NATUREZA_APURADA": "natureza_apurada", "LATITUDE": "lat", "LONGITUDE": "long",
    })
    fato = gpd.GeoDataFrame(fato, geometry="geometry", crs="EPSG:4326")
    write_gdf(eng, fato, "fato_crimes", page_size=2000)
    log.info("fato_crimes: %d rows (%d cleaned bulletins)", len(fato), len(crimes))

    # --- enrichment ----------------------------------------------------- #
    log.info("running enrich.sql")
    apply_sql(eng, (_SQL_DIR / "enrich.sql").read_text())
    log.info("ETL complete.")


if __name__ == "__main__":
    main()
