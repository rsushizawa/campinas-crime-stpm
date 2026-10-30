"""IC-Crime ETL — flat extract functions + a linear rebuild script.

    from etl import sources, taxonomy
    from etl.postgis import write_gdf, write_df

Run the whole pipeline with ``python scripts/02_clean/load_database.py``.
"""
