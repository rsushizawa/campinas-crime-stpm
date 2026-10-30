# Datasheet: property-crime tract × month cube, 2022–2025 (primary EHSA input)

> **Update (2026-10-30).** The cube is built in memory by the core pipeline,
> `scripts/04_analyse/run_core.py` (step `change`; `make analyse`), from the
> scripted, deduplicated bulletins (one row per bulletin; see
> [ssp_bulletins_clean.md](ssp_bulletins_clean.md)):
> `crime.data.units.unit_dataset("tract", crime_group="property")` then
> `crime.esri.cube.space_time_cube(ds, freq="QE" | "ME")`. It is no longer
> snapshotted to disk; the per-tract counts are in
> `outputs/core/static_by_unit/tract.parquet` (`crime_count`) and the totals in
> `outputs/core/descriptive.csv`. The earlier producer
> (`run_board_analysis.py`, writing `outputs/board/`) has been removed from
> this repository; references to `outputs/board/` below describe that removed
> run. Values after #13 (computed by the removed run, 2026-10-22):
>
> | Quantity | Before #13 | Now |
> |---|---|---|
> | Cube total (property, window, in a tract) | 90,486 records | **90,436 bulletins** |
> | By slug | furto_outros 57,435 · roubo_outros 15,650 · furto_veiculo 11,804 · roubo_veiculo 5,158 · roubo_carga 398 · furto_carga 40 · roubo_banco 1 | 57,411 · 15,639 · 11,803 · 5,145 · 397 · 40 · 1 |
> | Events per year | 22,855 · 24,868 · 22,629 · 20,134 | 22,845 · 24,853 · 22,616 · 20,122 |
> | Zero cells / all-zero tracts / median per tract / max cell | 67.7 % / 225 / 15 / 121 | 67.8 % / 224 / 15 / 121 |
>
> Funnel now: 139,301 offence records → 138,330 bulletins (property 109,632) →
> 108,914 property in the window → 90,463 with a usable coordinate → 90,436 in
> a tract (`outputs/data/funnel.json`). Step 1 below now reads
> `outputs/data/bulletins_clean.parquet`; step 5 ("no deduplication") no
> longer applies. The rest of this page describes the pre-#13 cube.

This is the assembled dataset that the primary Emerging Hot Spot Analysis
(EHSA) runs on. Before 2026-10-30 it was produced by the (now removed)
`scripts/04_analyse/run_board_analysis.py`, specification `PRIMARY`, which
snapshotted it to `outputs/board/tract_counts.parquet` with the tract
attributes in `outputs/board/tracts.parquet`. The current producer is
`scripts/04_analyse/run_core.py` (see the update note above).

All numbers on this page were **recomputed on 2026-10-22** from the raw CSV,
independently of the database. The pipeline logic was replicated: the
`etl/sources.py` extractor, the `etl/taxonomy.py` mapping, point-in-polygon
assignment with first match, and the `crime/data/query.py:CrimeQuery` window.
The recomputed cube matches `tract_counts.parquet` **cell for cell (0
mismatching cells)**.

## How it is built

Current (no database):

```python
from crime.data.units import unit_dataset
from crime.esri.cube import space_time_cube
ds   = unit_dataset("tract", crime_group="property", years=(2022, 2025))
cube = space_time_cube(ds, freq="QE")     # primary time unit; "ME" for months
```

`unit_dataset` assigns each geocoded bulletin to a tract with
`crime.data.units.assign_points` (point-in-polygon, `intersects`, first unit in
row order). Before 2026-10-30 (PostGIS):

```python
ds   = crime.load_sectors(years=(2022, 2025), crime_group="property", events=True, overlay=True)
cube = crime.space_time_cube(ds)          # freq="ME"
cube.wide.to_parquet("outputs/board/tract_counts.parquet")   # removed run
```

The pre-#13 pipeline ran in five steps:

1. **`crimes_campinas.csv` → `fato_crimes`** (`scripts/02_clean/load_database.py`). Only rows with
   numeric lat/long are loaded. Each point is assigned to a 2022 tract by
   `within`, keeping the first match. `crime_group` is set by
   `etl/taxonomy.py:to_group`.
2. **Filter** (`crime/data/query.py:CrimeQuery.where`, SQL), with all three
   conditions applied:
   - `cd_setor IS NOT NULL`
   - `crime_group = 'property'`
   - `ano_bo BETWEEN 2022 AND 2025` **and** `data_ocorrencia >= 2022-01-01
     AND < 2026-01-01`
3. **Bin** (`crime/esri/cube.py:space_time_cube`, `freq="ME"`). Events are
   counted per tract and calendar month of occurrence. The cube is
   zero-filled to all 2,592 tracts and all 48 months.
4. **Window equivalence.** The window equals `crime/data/cleaning.py`
   `DATE_START = "2022-01-01"` / `DATE_END = "2025-12-31"`. `filter_events`
   itself is **not called** on this path; the same window is applied in SQL.
   Applied to the property rows, `filter_events` keeps the same 108,984 rows
   (718 before the start date, 0 after the end date, 1 unparseable date). The
   extra `ano_bo` condition removes nothing, because every row has `ANO_BO` in
   2022–2025.
5. **No deduplication.** Bulletins carrying two property offences count
   twice (see [ssp_crimes_campinas.md](ssp_crimes_campinas.md)).

## What one cell is

One cell is **the number of SSP-SP bulletin × offence records with
`crime_group = "property"`, whose geocoded point lies within 2022 tract *i*,
and whose occurrence date (`DATA_OCORRENCIA_BO`) falls in calendar month
*t*.**

- Rows: 2,592 tracts, indexed by `unit_id` = `cd_setor`.
- Columns: 48 month-end timestamps, 2022-01-31 … 2025-12-31.
- Integer counts.

A cell counts *recorded, geocoded* events. It is not a count of incidents,
and it is not adjusted for geocoding completeness.

## `crime_group = "property"`: exact membership

From `etl/taxonomy.py:CRIME_GROUPS["property"]`. All 44 raw
`NATUREZA_APURADA` strings in the CSV map to a slug; 0 are unmapped.

| Slug | Raw `NATUREZA_APURADA` strings in the file (rows) | Rows in CSV | Rows in cube |
|---|---|---|---|
| `furto_outros` | `Furto - Outros` (53,953), `FURTO - OUTROS` (16,490) | 70,443 | 57,435 |
| `roubo_outros` | `Roubo - Outros` (14,904), `ROUBO - OUTROS` (3,380) | 18,284 | 15,650 |
| `furto_veiculo` | `Furto - Veículo` (10,724), `FURTO DE VEÍCULO` (3,854) | 14,578 | 11,804 |
| `roubo_veiculo` | `Roubo - Veículo` (4,783), `ROUBO DE VEÍCULO` (1,150) | 5,933 | 5,158 |
| `roubo_carga` | `Roubo - Carga` (390), `ROUBO DE CARGA` (29) | 419 | 398 |
| `furto_carga` | `Furto - Carga` (36), `FURTO DE CARGA` (9) | 45 | 40 |
| `roubo_banco` | `Roubo - Banco` (1) | 1 | 1 |
| **total** | | **109,703** | **90,486** |

## N funnel (property crime)

| Stage | Rows | Removed | Reason |
|---|---|---|---|
| Raw rows, `crimes_campinas.csv` (all offences) | 139,301 | | |
| `crime_group == "property"` | 109,703 | 29,598 | other offence groups |
| Occurrence date in 2022-01-01 … 2025-12-31 | 108,984 | 719 | 718 occurred before 2022; 1 unparseable date (`1202-02-28`) |
| … with a numeric lat/long | 93,206 | 15,778 | 5,560 redacted (`VEDAÇÃO…`); 10,218 empty / `NULL` |
| … inside a 2022 Campinas tract (**cube total**) | **90,486** | 2,720 | 2,670 at `(0,0)` (the 2025 redaction code); 50 outside every tract |

These match the property column of `outputs/board/data_audit.json → funnel`:
109,703 / 108,984 / 93,206 / 90,486. That file computes the last stage as
"inside the union of tracts". This page computes it as "within some tract",
with the same result. They also match `outputs/board/analysis_results.json →
n_records = 90,486`.

`data_audit.json` also lists "has coordinate" = 93,757 for property rows
*without* the date filter. That figure includes 2,677 `(0,0)` points.

Share of property events in the window that reach the cube: 90,486 / 108,984 =
**83.0 %**.

## Cube descriptives

| Quantity | Value |
|---|---|
| Events per year (occurrence) | 2022: 22,855 · 2023: 24,868 · 2024: 22,629 · 2025: 20,134 |
| Zero cells | 67.7 % of 124,416 (= 2,592 × 48) |
| Tracts with zero events over all 48 months | 225 |
| Median events per tract (48 months) | 15 |
| Max events in one cell | 121 |
| `count_matrix_sha256` (`analysis_results.json`) | `e187e3cab6373151b551d9aebf73361cf6618d73784c591bbc0406ae97ad4a9e`, a hash of `pd.util.hash_pandas_object`. **Not recomputed here**; cell equality was checked instead |

## Known limitations that propagate into the cube

- **The redaction code changes in 2025.** In 2025 redacted points are
  `(0,0)` and drop out at the tract step; in 2022–2024 they are `VEDAÇÃO…` and
  drop out at the coordinate step. `data_audit.json` reports property
  geocoding completeness, as the mean of the monthly shares before the boundary
  filter, of 81.5 % for 2022 and 93.2 % for 2025. These values are quoted, not
  recomputed. Because that measure counts `(0,0)` as geocoded, it overstates
  the 2025 completeness.
- **The unit is bulletin × offence**, not incident. There is no
  deduplication.
- **The occurrence date is used for time.** Registration lag over the whole
  CSV is median 1 d, p90 10 d, p99 181 d. Events that occurred in late 2025
  but were registered after the extract are absent (inferred; not quantified).
- **Tract assignment uses SSP-SP coordinates as published.** Stacked
  street-level geocodes are kept (see #9).
- **Covariates are not part of the cube.** The 90 tracts without IBGE income
  or literacy (69 uninhabited + 21 suppressed) are still in the cube; the
  covariates live in `tracts.parquet`.

## Provenance

| Item | Value |
|---|---|
| Producer | `scripts/04_analyse/run_core.py` (step `change`, in memory). Before 2026-10-30: `scripts/04_analyse/run_board_analysis.py:main` (removed) |
| Inputs | `outputs/data/bulletins_clean.parquet` (stage 02) and the 2022 tract polygons `inputs/data/geobr/census_tract_3509502_2022.parquet` (see [ibge_census_tracts_2022.md](ibge_census_tracts_2022.md)). Before 2026-10-30: PostGIS `fato_crimes` (from `crimes_campinas.csv`, SHA-256 `19d7cf1f3f0e4b987e7feed679a601767ac7699ceeb37ae6854c24572ee64cda`) and `vw_sector_features` |
| Snapshot | None (built in memory). Per-unit results and run provenance in `outputs/core/` (`manifest.json`), git-ignored (`/outputs/*`). The removed run wrote `outputs/board/tract_counts.parquet` |
