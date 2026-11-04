# IBGE statistical grid (*Grade Estatística*): 2022 grid, its Campinas cache, and two unused grids

> **Removed (author decision, 2026-11-03).** The paper analyses census tracts
> only, so the statistical grid are no longer read and the files were removed from
> `inputs/data/` (last SHA-256 in [`inputs/data/README.md`](../../inputs/data/README.md);
> recoverable from the tag `archive/pre-warehouse-2026-11-03`). The text below
> describes the files as they were.

The polygon support of the PostGIS warehouse (`dim_grid_cell`,
`vw_grid_features`). Two grid files are in the repo, both
read by the warehouse ETL (`scripts/02_clean/load_database.py` →
`etl/sources.py:extract_grid`); the analysis notebooks do not use them (their
supports are points, census tracts and UTBs; there is no Python grid loader).
Two other grids were removed.

| File | Status |
|---|---|
| `inputs/data/grade_id25_2022.zip` | **used**: raw 2022 grid, quadrant ID_25 |
| `inputs/data/geobr/statistical_grid_2022_campinas.parquet` | **used**: Campinas clip of the above (cache) |
| `inputs/data/geobr/statistical_grid_3509502_2010.parquet` | **unused**; **Removed** (owner decision, 2026-10-23, in the IC-Crime repository; recoverable from its history, tag `archive/pre-reset-2026-10-30`) |
| `inputs/data/grade_id35/grade_id35.*` (8 shapefile parts) | **unused**; **Removed** (owner decision, 2026-10-23, in the IC-Crime repository; recoverable from its history, tag `archive/pre-reset-2026-10-30`) |

## Official definition (all 2022 grid files)

Source: IBGE, *Censo Demográfico 2022, Grade Estatística, Notas metodológicas
01/2025*. URL (verified 2026-10-22):
`https://geoftp.ibge.gov.br/recortes_para_fins_estatisticos/grade_estatistica/censo_2022/Notas_metodologicas_grade_estatistica_2022.pdf`.

- Cells are **1 km × 1 km in rural areas and 200 m × 200 m in urban areas**.
- `ID_UNICO` encodes the cell size (`1KM…` or `200M…`).

| Field | Type | Definition (Quadro 04) |
|---|---|---|
| `ID_UNICO` | text | Unique cell identifier |
| `nome_1KM` … `nome_500KM` | text | Identifier of the enclosing 1/5/10/50/100/500 km cell |
| `QUADRANTE` | text | Index quadrant of the vector files |
| `TOTAL` | integer | Total population in the cell |
| `TOTAL_DOM` | integer | Total **occupied households, private and collective**, in the cell |

`TOTAL_DOM` counts private + collective households. The tract-level
`dom_total` (IBGE *Básico* `V0007`) counts occupied **private** households
only. The two `dom_total` columns in the database therefore do not measure
the same thing.

## `inputs/data/grade_id25_2022.zip` (raw, used)

| Item | Value |
|---|---|
| Producer | IBGE |
| URL | `https://geoftp.ibge.gov.br/recortes_para_fins_estatisticos/grade_estatistica/censo_2022/grade_estatistica/grade_id25.zip` (verified listing, 2026-10-22). Server size 40,283,809 bytes, which equals the local file. The local file was renamed `…_2022.zip`. The hash was not compared against the server copy |
| Download date | Unknown. The zip members are dated 2025-02-24/25. Committed in `6891c8b` (2026-08-16) |
| Licence | Not stated. **To check** |
| SHA-256 | `fa9f041962622254a17a3a5ef0f883152ce12ac925204c6be1618f545f4f37ab` |
| Content | shapefile `grade_id25` with 929,387 cells, EPSG:4674, bounds lon −51.09…−46.19, lat −26.83…−22.19 |
| Read by | `etl/sources.py:extract_grid`, **only when the parquet cache is absent** (`crime/core/config.py:GRID_2022_ZIP`) |

## `inputs/data/geobr/statistical_grid_2022_campinas.parquet` (cache, used)

Despite the folder name, this file is **not** from `geobr`. `extract_grid`
writes it: it reads the zip with the Campinas bounding box, then keeps the
cells that intersect the municipality.

| Item | Value |
|---|---|
| SHA-256 | `2f1ba2b6514d36c1c71819cd23402c3a1ae802fe4edf1c8402aca933df128461` |
| CRS | EPSG:4674. `extract_grid` reprojects it to EPSG:4326 |
| Rows | 14,971 cells: 14,709 at 200 m and 262 at 1 km. `ID_UNICO` has no duplicates |
| One row | one grid cell |
| `TOTAL` | 0…2,590, sum 1,155,822 |
| `TOTAL_DOM` | 0…1,017 |

The `TOTAL` sum, 1,155,822, is larger than the 2022 tract population of
1,139,047 (*Básico* `V0001`) because cells that cross the municipal boundary
are kept whole.

`extract_grid` renames `ID_UNICO→grid_id`, `TOTAL→pop_total` and
`TOTAL_DOM→dom_total`, and drops the other columns. This feeds:

- `dim_grid_cell`, which becomes `vw_grid_features` (SQL only)
- the CNEFE `grid_id` join (`scripts/02_clean/load_database.py`)
- the fallback area-weighted tract population in `database/enrich.sql`, which
  is applied only where the tract has no *Agregados* value

## `inputs/data/geobr/statistical_grid_3509502_2010.parquet` (removed)

- `geobr` 2010 statistical grid for Campinas: 13,760 cells. Columns:
  `id_unico`, `pop_total` (sum 1,066,499), `pop_fem`, `pop_masc`, `dom_ocu`
  and others.
- SHA-256 `aa310ab0dba79a672ba3485f5fb403b3687ca0ee4214ffbd8c6d82b5b1d11d7b`.
- Commit `1415284` (2026-07-10) introduced it as the grid source, with the
  note "2010 grid — the latest available". Commit `01c1174` (2026-07-15)
  replaced it with the 2022 grid.
- **No current code references it.** `grep` for `statistical_grid_3509502` and
  `year=2010` over the code finds nothing.
- **Unused. Removed (owner decision).**

## `inputs/data/grade_id35/grade_id35.*` (removed)

- IBGE 2022 grid, quadrant **ID_35**: 583,288 cells, EPSG:4674, bounds lat
  −22.27…−17.70. This lies **entirely north of Campinas**, whose cells lie
  between about −23.06 and −22.72 in the CNEFE bounds. Commit `1415284`
  already recorded that "the local grade_id35 shapefile covers quadrant ID_35
  only, which lies north of Campinas".
- SHA-256 of `.shp`: `2a66ca3aabaef9fe6893a2277cfa80343ec04a522deac192b7829d6330777600`.
  The other parts are listed in `inputs/data/README.md`.
- **No code references it.** `grep` for `grade_id35` finds nothing outside git
  history.
- **Unused. Removed (owner decision).**
