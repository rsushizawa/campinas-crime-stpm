# IBGE 2022 census tracts, Campinas (`inputs/data/geobr/census_tract_3509502_2022.parquet`)

This file is the spatial unit of the primary analysis: the 2022 census tracts
(*setores censitários*) of Campinas, IBGE municipality code 3509502.

## Provenance

| Item | Value |
|---|---|
| Producer | IBGE, *Malha de Setores Censitários* 2022, obtained through the `geobr` package (IPEA, `https://github.com/ipeaGIT/geobr`) |
| How obtained | `etl/sources.py:extract_census_tracts` calls `geobr.read_census_tract(code_tract=3509502, year=2022, simplified=False)` the first time it runs and caches the result to this parquet file. `geobr` is **not installed** in the current `.venv`, so the cache is the only copy |
| Download date | Unknown. The file was committed in `6891c8b` (2026-08-16) and is unchanged since |
| Licence | Not stated (IBGE public data; the `geobr` package licence is not checked here). **To check** |
| CRS | EPSG:4674 (SIRGAS 2000, geographic). The extractor reprojects it to EPSG:4326 |
| Size | 1,508,480 bytes |
| SHA-256 | `25c880643811a73a43d6eaafe3961a5b234cd46def499c4c318fd0d5e315557e` |

## What one row is

Each row is one tract polygon. The file has **2,593 rows but 2,592 distinct
`code_tract`**: tract `350950210000134` is stored as two separate polygons
(41,209 m² and 73,630 m²). `extract_census_tracts` dissolves these on
`cd_setor`, which leaves 2,592 tracts, the `n_tracts` reported in
`outputs/board/analysis_results.json`.

All geometries are `MultiPolygon`. None is null, empty or invalid. The total
area is 794.80 km² in EPSG:31983. The IBGE *Agregados* `AREA_KM2` sums to
794.57 km².

## Columns

| Column | Type | Meaning | Values | Missing |
|---|---|---|---|---|
| `code_tract` | float64 (15-digit code) | IBGE tract code. It becomes `cd_setor` as a string, with the `.0` removed | 2,592 distinct | 0 |
| `code_muni`, `name_muni` | float / str | Municipality | 3509502 / Campinas | 0 |
| `code_district`, `name_district` | float / str | District | 7 districts | 0 |
| `code_subdistrict` | float | Subdistrict | 7 | 0 |
| `name_subdistrict`, `code_neighborhood`, `name_neighborhood` | — | — | all null | 2,593 |
| `zone` | str | Urban/rural situation | `Urbana`, `Rural` | 0 |
| `code_state`, `abbrev_state`, `name_state`, `code_region`, `name_region`, `year` | — | constants (35/SP/São Paulo/3/Sudeste/2022) | — | 0 |
| `geometry` | MultiPolygon | tract boundary | — | 0 |

The column names come from `geobr`. The official definitions are in IBGE's
*Malha de Setores Censitários* documentation, which is **not in the repo**.

## Code that reads it

| Code | Columns used |
|---|---|
| `etl/sources.py:extract_census_tracts`, which feeds `dim_setor_censitario` in `scripts/02_clean/load_database.py` | `code_tract→cd_setor`, `name_muni→nm_municipio`, `name_district→nm_distrito`, `zone→situacao`, `geometry` |
| `crime/data/cleaning.py:build_tract_attributes` (through the extractor) | `cd_setor`, `geometry` |
| `paper/presentation_puc/src/data_audit.py` | municipality outline, built as the union of the tracts |
| `paper/presentation_puc/src/make_fapesp_figs.py` | reads the parquet directly, for deck figures |

The crime-to-tract assignment (`etl/postgis.py:assign_unit`) is a
point-in-polygon join with `predicate='within'` that keeps the first match.
