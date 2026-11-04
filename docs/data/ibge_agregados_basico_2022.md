# IBGE Censo 2022, Agregados por Setores Censitários, Básico (`Agregados_por_setores_basico_BR*.zip`)

The per-tract population (`V0001`) and occupied private households (`V0007`)
for the 2022 tracts.

## Provenance

| Item | Value |
|---|---|
| Producer | IBGE, Censo Demográfico 2022 |
| URL (verified listing 2026-10-22) | `https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/Agregados_por_setores_basico_BR_20260520.zip` |
| Official dictionary (verified listing) | `https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx`, sheet *Dicionário Básico*. This dictionary is **not in the repo**; a copy downloaded on 2026-10-22 had SHA-256 `0b8aedece57f6125d785b6aa2234cfd587e92dfb6ce5ca6ace8c67f140831344` |
| Licence | Not stated in the files. **To check** |
| Format | zip containing `Agregados_por_setores_basico_BR.csv` (140,970,380 bytes, zip member dated 2026-05-08). `;`-separated, latin-1, decimal comma |
| Coverage | all of Brazil: 468,099 tracts, 38 columns. Campinas: 2,592 tracts (`CD_SETOR` starts with `3509502`) |

There were **two local copies, byte-identical** (same SHA-256
`ec04624286233d699ebe69c7b9625744a1cfdfc8352126f30245bdef5e9bdc63`):

| Path | Tracked | Date | Read by |
|---|---|---|---|
| `inputs/data/geobr/Agregados_por_setores_basico_BR_20260520.zip` | untracked | file mtime 2026-09-29 12:09, probably the download time of `extract_census_2022` | `etl/sources.py:extract_census_2022`, which downloads it if it is absent; `crime/data/cleaning.py:RawPaths.census_basico` |
| `inputs/data/Agregados_por_setores_basico_BR.zip` | **Removed** (owner decision, 2026-10-23, in the IC-Crime repository; recoverable from its history, tag `archive/pre-reset-2026-10-30`) | — | — |

The `etl/sources.py` docstring calls the `inputs/data` copy "preliminary". It
was in fact identical to the 2026-05-20 release, hence its removal as
redundant.

## What one row is

One row is one 2022 census tract, keyed by `CD_SETOR` (15 digits). The 2,592
Campinas codes are unique.

## Columns used by the project

The file has 38 columns: 29 geographic identifiers plus `v0001`–`v0009`.
Column names are lower-case `v…` in the file; `_read_setores_zip` upper-cases
them. Definitions are from the *Dicionário Básico* sheet.

| Column | Type | Unit | Official definition | Campinas values | Missing |
|---|---|---|---|---|---|
| `CD_SETOR` | str (15) | — | Tract code | 2,592 unique | 0 |
| `V0001` | int | persons | *Total de pessoas* (total residents) | 0…1,630; median 436; **sum 1,139,047**; 69 tracts = 0 | none (`X` 0, empty 0) |
| `V0007` | int | households | *Total de Domicílios Particulares Ocupados (DPPO + DPIO)*: occupied permanent + improvised private households | 0…575; sum 429,769; 72 tracts = 0 | none |

Other columns, not used: `v0002`/`v0003`/`v0004` (total, private and collective
households), `v0005` (mean residents per occupied private household), `v0006`
(share of imputed occupied households), `v0008` (occasional-use), `v0009`
(vacant), `AREA_KM2` (Campinas sum 794.57 km²), `SITUACAO` (Urbana 2,534 /
Rural 58), and the region, state, district and other names and codes.

## Quality notes (computed)

- No suppression (`X`) in `V0001` or `V0007` for Campinas.
- **69 tracts have `V0001 == 0`.** These are the same 69 tracts that are
  missing from the income and literacy tables (see
  [ibge_renda_responsavel_2022.md](ibge_renda_responsavel_2022.md)).
- The definitions of households differ across files: the grid's `TOTAL_DOM`
  counts private + collective households, while `V0007` counts private only
  (see [ibge_statistical_grid.md](ibge_statistical_grid.md)).

## Code that reads it

- `etl/sources.py:extract_census_2022` produces `cd_setor`,
  `populacao_total` (`V0001`) and `dom_total` (`V0007`). These are merged into
  `dim_setor_censitario` in `scripts/02_clean/load_database.py`, and `vw_sector_features.pop_total`
  is the population denominator of `crime_rate` / `crime_rate_eb`.
- `crime/data/cleaning.py:tract_attributes` produces `pop_total`.
