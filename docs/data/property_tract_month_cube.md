# Datasheet: property-crime tract × month cube, 2022–2025 (primary EHSA input)

This is the assembled dataset the primary Emerging Hot Spot Analysis (EHSA)
runs on. The warehouse builds it on request (`Warehouse.counts`, called by
`notebooks/06_ehsa`) from `fact_bulletin`, the deduplicated bulletins (one row
per bulletin; see [ssp_bulletins_clean.md](ssp_bulletins_clean.md)). It is not
stored as a table.

All numbers on this page were recomputed on 2026-10-30 and re-checked on
2026-11-03 against the warehouse release data-v1.0.0 (same values); they agree
with the funnel in the warehouse's `build` table.

## How it is built

```python
from crime.data import CrimeQuery, Warehouse
cube = Warehouse().counts(CrimeQuery(crime_group="property", time_unit="quarter"))   # or "month"
```

1. **Bulletins.** `fact_bulletin`, one row per `NUM_BO + ANO_BO +
   NOME_DELEGACIA`; offence = the one with the highest maximum penalty
   (`etl/clean.py`, rule 9).
2. **Filter**: crime group `property` (`dim_offence`); occurrence date in
   2022-01-01 to 2025-12-31; inside a 2022 tract (`census_tract_id` not null).
3. **Assign** each point to its tract: the units stage's point-in-polygon join
   (`within`, first match; rules 16 and 17).
4. **Bin**: events per tract and calendar quarter (16 bins, `dim_date.quarter_start`)
   or month (48 bins), zero-filled to all 2,592 tracts and every bin. The
   result is long (one row per tract and bin); the notebook pivots it.

## What one cell is

One cell is **the number of SSP-SP bulletins whose kept offence has
`crime_group = "property"`, whose geocoded point lies within 2022 tract *i*,
and whose occurrence date (`DATA_OCORRENCIA_BO`) falls in time bin *t*.**

- Rows: 2,592 tracts, indexed by `unit_id` = `cd_setor`.
- Columns: period-start timestamps (2022-01-01 … 2025-10-01 for quarters;
  2022-01-01 … 2025-12-01 for months).
- Integer counts.

A cell counts *recorded, geocoded* bulletins. It is not a count of incidents,
and it is not adjusted for geocoding completeness.

## `crime_group = "property"`: exact membership

From `etl/taxonomy.py:CRIME_GROUPS["property"]`. All 44 raw
`NATUREZA_APURADA` strings in the CSV map to a slug; 0 are unmapped. A
bulletin's slug is its offence with the highest maximum penalty
(`etl/clean.py`), so a bulletin is counted once, under one slug.

| Slug | Raw `NATUREZA_APURADA` strings in the legacy CSV (rows) | Rows in legacy CSV | Bulletins in cube |
|---|---|---|---|
| `furto_outros` | `Furto - Outros` (53,953), `FURTO - OUTROS` (16,490) | 70,443 | 57,411 |
| `roubo_outros` | `Roubo - Outros` (14,904), `ROUBO - OUTROS` (3,380) | 18,284 | 15,639 |
| `furto_veiculo` | `Furto - Veículo` (10,724), `FURTO DE VEÍCULO` (3,854) | 14,578 | 11,803 |
| `roubo_veiculo` | `Roubo - Veículo` (4,783), `ROUBO DE VEÍCULO` (1,150) | 5,933 | 5,145 |
| `roubo_carga` | `Roubo - Carga` (390), `ROUBO DE CARGA` (29) | 419 | 397 |
| `furto_carga` | `Furto - Carga` (36), `FURTO DE CARGA` (9) | 45 | 40 |
| `roubo_banco` | `Roubo - Banco` (1) | 1 | 1 |
| **total** | | **109,703** | **90,436** |

## N funnel (property crime)

From `outputs/data/funnel.json` (stage 02):

| Stage | Property |
|---|---|
| Offence records (acquired CSV) | 109,708 |
| Bulletins (one row per bulletin, kept offence is property) | 109,632 |
| Occurrence date in 2022-01-01 … 2025-12-31 | 108,914 |
| … with a usable coordinate | 90,463 |
| … inside a 2022 Campinas tract (**cube total**) | **90,436** |

Share of property bulletins in the window that reach the cube: 90,436 /
108,914 = **83.0 %**.

## Cube descriptives (monthly cube)

| Quantity | Value |
|---|---|
| Events per year (occurrence) | 2022: 22,845 · 2023: 24,853 · 2024: 22,616 · 2025: 20,122 |
| Zero cells | 67.8 % of 124,416 (= 2,592 × 48) |
| Tracts with zero events over all 48 months | 224 |
| Median events per tract (48 months) | 15 |
| Max events in one cell | 121 |

## Known limitations that propagate into the cube

- **The redaction code changes in 2025.** In 2025 redacted points are
  `(0,0)`; in 2022–2024 they are `VEDAÇÃO…`. Both are treated as no usable
  coordinate (`COORD_STATUS`, see [ssp_bulletins_clean.md](ssp_bulletins_clean.md)).
- **The unit is the bulletin**, not the incident; a bulletin with two
  property offences counts once.
- **The occurrence date is used for time.** Registration lag over the whole
  CSV is median 1 d, p90 10 d, p99 181 d. Events that occurred in late 2025
  but were registered after the extract are absent (inferred; not quantified).
- **Tract assignment uses SSP-SP coordinates as published.** Stacked
  street-level geocodes are kept (see `docs/METHODS.md`, Known limitations).
- **Covariates are not part of the cube.** The 90 tracts without IBGE income
  or literacy (69 uninhabited + 21 suppressed) are still in the cube.

## Provenance

| Item | Value |
|---|---|
| Producer | `crime.data.Warehouse.counts` (called by `notebooks/06_ehsa`) |
| Inputs | `fact_bulletin`, `dim_date` and the 2022 tract polygons `inputs/data/geobr/census_tract_3509502_2022.parquet` (see [ibge_census_tracts_2022.md](ibge_census_tracts_2022.md)) |
| Snapshot | None (built on request from the warehouse). Notebook results in `outputs/nb/<notebook>/`, git-ignored (`/outputs/*`) |
| History | Before the bulletin deduplication (IC-Crime repository, tag `archive/pre-reset-2026-10-30`) the cube counted bulletin × offence records: 90,486 instead of 90,436 |
