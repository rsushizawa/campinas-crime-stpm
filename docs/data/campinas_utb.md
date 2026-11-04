# Campinas UTB polygons (`inputs/data/map.geojson`)

> **Removed (author decision, 2026-11-03).** The paper analyses census tracts
> only, so the UTB polygons are no longer read and the files were removed from
> `inputs/data/` (last SHA-256 in [`inputs/data/README.md`](../../inputs/data/README.md);
> recoverable from the tag `archive/pre-warehouse-2026-11-03`). The text below
> describes the files as they were.

This file holds 93 *Unidades Territoriais Básicas* (UTB), the planning zones
of Campinas, with census attributes. In the analysis it is used only as a map
overlay (UTB boundaries). Its `rendatemei` field also feeds the mislabelled
database column `income_mean` (see Quality notes).

## Provenance

| Item | Value |
|---|---|
| Producer | **Unverified.** Presumably the Prefeitura Municipal de Campinas (UTB is the municipal planning unit), but no URL, document or metadata in the repo or the file names the publisher |
| URL | **Unknown / unverified** |
| Census vintage of the attributes | **2010 Census (verified).** `tot_pop` sums to **1,080,113**, exactly the 2010 resident population of Campinas in IBGE SIDRA table 202 (`https://apisidra.ibge.gov.br/values/t/202/n6/3509502/v/93/p/2010/c1/0/c2/0`, queried 2026-10-22). The attributes are **not** 2022 data |
| Download date | Unknown. Committed in `6891c8b` (2026-08-16) |
| Licence | Not stated. **To check** |
| Format | GeoJSON, 93 features (92 Polygon, 1 MultiPolygon), 46 attributes |
| Size | 1,322,636 bytes |
| SHA-256 | `5dc6343b73db910e726a8047550983024a3b062d7e903296820a9a9844a2e39e` |

**The CRS is mislabelled.** The file is read as EPSG:4326, but its coordinates
are projected metres: bounds x 269,593…313,860, y 7,448,164…7,485,151.
`extract_utb` overrides the label to EPSG:31983 (SIRGAS 2000 / UTM 23S) and
reprojects. The UTM zone fits Campinas. The **datum is unverified**: SAD69 /
UTM 23S (EPSG:29193) would also produce coordinates in this range. Under
EPSG:31983 the total area is 795.35 km², against 794.80 km² for the 2022
tracts.

## What one row is

One row is one UTB polygon.

- `gid` is **not unique**: 88 distinct values for 93 rows. `extract_utb`
  replaces it with `1..93`.
- `utb_sigla` repeats for the rural zones. For example, `UTR - Campo Grande`
  appears 5 times; 82 distinct values in all.
- 15 UTBs have `tot_pop == 0`.

## Columns

No official dictionary is available. The definitions below are **inferred
from the field names and unverified**, except where noted.

| Column | Type | Meaning (inferred) | Range | Used |
|---|---|---|---|---|
| `gid`, `id` | int | feature ids | gid 1…1,760 | `gid` (replaced) |
| `utb_sigla` | str | UTB code (`EU-35`, `RA-11`, `MM-70`, `UTR - …`) | 82 distinct | **yes** (overlay) |
| `denominaca` | str | UTB name (truncated `denominacao`) | 93 distinct | ETL |
| `tot_pop` | int | total residents, 2010 (verified by the sum above) | 0…85,844 | ETL |
| `tot_dom` | int | total households, 2010 | 0…26,807; sum 348,503 | ETL |
| `tot_pop_fa` | int | **unverified**. Possibly the population in *favelas* / subnormal agglomerates | 0…17,695 | ETL |
| `rendatemei` | int | **count** of persons with income up to ½ minimum wage. This is not an income level. The `etl/sources.py:extract_utb` docstring and IC-Crime#1 c5 give this definition | 0…606 | ETL → `n_low_income_half_mw` → `income_mean` |
| `rendmeioa1`, `rend1a2_sm`, … `rendmaisd2` | int | counts by income band in minimum wages (½–1, 1–2, 2–3, 3–5, 5–10, 10–15, 15–20, > 20). Whether these count persons or heads is **unverified** | — | no |
| `rend_dompc`, `rend_dom_1` … `rend_dom_8` | int | household income-band counts (**unverified**) | — | no |
| `mulheres`, `homens` | int | women, men | — | no |
| `pessoas_al`, `pessoas__1` … `pessoas__3` | int | **unverified**. Possibly literacy-related, per the prefix `al` | — | no |
| `pessoas_0a` … `pessoas_65` | int | 5-year age bands | — | no |
| `densidade_` | float | density (unit unverified) | 0…5,346 | no |
| geometry | Polygon | UTB boundary | — | **yes** |

## Quality notes (computed)

- **The attributes are 2010 Census values.** They should not be joined to
  2022 crime or 2022 tracts as if they were contemporaneous.
- **`rendatemei` is a count, not an income.** `database/enrich.sql` still
  copies it into `dim_setor_censitario.income_mean` and
  `dim_grid_cell.income_mean`, using the UTB that contains each centroid.
  `crime/data/catalog.py:DEFAULT_FEATURES` still lists `income_mean` (the
  default feature set of `feature_collinearity`, DB path only; the core
  pipeline does not use it). For the real 2022 income, see
  [ibge_renda_responsavel_2022.md](ibge_renda_responsavel_2022.md).

## Code that reads it

| Code | Columns used |
|---|---|
| `etl/sources.py:extract_utb`, which feeds `dim_utb` in `scripts/02_clean/load_database.py` | `utb_sigla, denominaca→denominacao, tot_pop, tot_dom, tot_pop_fa, rendatemei→n_low_income_half_mw`, geometry |
| `database/enrich.sql` | `n_low_income_half_mw` → `income_mean` (sector and grid) |
| `crime/data/postgis.py:PostGISSource.overlay` (`load_sectors(overlay=True)`) | `gid, utb_sigla`, geometry |
