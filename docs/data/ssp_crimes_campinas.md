# SSP-SP crime bulletins, Campinas 2022–2025 (`inputs/data/crimes_campinas.csv`)

> **Update (#13):** this hand-assembled file is now **legacy**. The pipeline reads
> the scripted `outputs/data/crimes_campinas.csv` (01_acquire) and the
> one-row-per-bulletin `outputs/data/bulletins_clean.parquet` (02_clean); see
> [ssp_bulletins_clean.md](ssp_bulletins_clean.md). The numbers below describe
> the legacy file and are kept as its datasheet.

The fact table of the project: police occurrence bulletins (boletins de
ocorrência, BO) registered in Campinas, as published by the São Paulo State
Public Security Secretariat (SSP-SP). Every crime count in the analysis comes
from this file.

All numbers below were recomputed on 2026-10-22 from the file with the hash
shown here. Scratch scripts were not committed.

## Provenance

| Item | Value |
|---|---|
| Publisher | Secretaria da Segurança Pública do Estado de São Paulo (SSP-SP), "SPDados" open crime data |
| URL | `https://www.ssp.sp.gov.br/estatistica/consultas`. The repo cites it in `paper/companion/companion.tex` (R12). **Unverified** that this page serves these exact files |
| Download date | **Unknown.** The file first appears in git in commit `6891c8b` (2026-08-16, "feat: data with lfs") and has not changed since. That date is only an upper bound |
| Licence | Not stated in the file or the repo. **To check** |
| Format | `;`-separated, UTF-8, CRLF line endings, 1 header row, 25 columns |
| Size / rows | 48,990,035 bytes. 139,301 data rows |
| SHA-256 | `19d7cf1f3f0e4b987e7feed679a601767ac7699ceeb37ae6854c24572ee64cda` (same as `outputs/board/data_audit.json → source_sha256`) |
| Tracked by | git LFS |

### How this file was built: a known gap (to be scripted in #13, Acquire stage)

No script in the repo produces `crimes_campinas.csv`. The steps below were
inferred by comparing the file with the two raw inputs. See
[ssp_raw_inputs.md](ssp_raw_inputs.md) for those inputs.

- **Rows from ANO_ESTATISTICA 2022–2024 (106,049):** these match
  `crimes_campinas_2022_2024.csv.bak` row for row. Every `.bak` row is in the
  CSV. In that part, `NOME_MUNICIPIO_CIRCUNSCRICAO == "CAMPINAS"` for 100% of
  rows, while `NOME_MUNICIPIO` (the municipality where the BO was registered) is
  not Campinas for 170 rows. The inferred filter is therefore *municipality of
  the fact = Campinas*. Where the `.bak` came from is unknown.
- **Rows from ANO_ESTATISTICA 2025 (33,252):** these come from
  `SPDadosCriminais_2025.xlsx` (statewide, two half-year sheets). That file has
  33,252 rows with `NOME_MUNICIPIO == "CAMPINAS"`, and the same number with
  `CD_IBGE == 3509502`. In the CSV's 2025 part, `NOME_MUNICIPIO` is Campinas for
  100% of rows, while `NOME_MUNICIPIO_CIRCUNSCRICAO` is Campinas for 33,206.
  The inferred filter is therefore *municipality of registration = Campinas*.
  **This is not the filter used for 2022–2024.** In the xlsx, 46 rows match one
  of the two municipality fields but not the other.
- The xlsx columns `DESCR_TIPOLOCAL`, `CMD`, `BTL`, `CIA` and `CD_IBGE` were
  dropped. `…_CIRCUNCRIÇÃO` was renamed to `…_CIRCUNSCRICAO`. Dates were written
  as `YYYY-MM-DD`.
- The conversion left artefacts in the 2025 coordinates: 190 `LATITUDE`/
  `LONGITUDE` values are `"NUL,L"` and 1 is `"0.0,"`.
- Row counts check out: 106,049 + 33,252 = 139,301.

## What one row is

One row is **one offence classification (`NATUREZA_APURADA`/`RUBRICA`) on one
registered bulletin**. It is not one incident and not one bulletin.

- `NUM_BO + ANO_BO + NOME_DELEGACIA` (the bulletin key) repeats: 969 rows
  duplicate an earlier key, spread over 939 distinct keys. In 933 of those 939
  keys the repeated rows have different `NATUREZA_APURADA` values (for example,
  one BO records both *Furto – Outros* and *Lesão corporal – Dolosa*). In 801
  keys the repeated rows have different `RUBRICA` values.
- `NUM_BO + ANO_BO` alone repeats 7,516 times. That key is not unique across
  police stations (`outputs/board/data_audit.json` reports the same 7,516).
- 1 row is an exact duplicate of another row.
- No deduplication is applied anywhere in the pipeline.

## Columns

Official descriptions are quoted from the `CAMPOS_DA_TABELA_SPDADOS` sheet of
`SPDadosCriminais_2025.xlsx` (Portuguese, translated). That sheet also states:
*"Resultado Null indica que o campo se encontrava vazio no banco de dados"*
("a Null result means the field was empty in the database").

**Missing-value codes differ by year.** In the 2022–2024 part a missing value
is an **empty string**. In the 2025 part it is the literal **`NULL`**. The
project reader (`pd.read_csv` default `na_values`) treats both as NaN. The
redaction marker **`VEDAÇÃO DA DIVULGAÇÃO DOS DADOS RELATIVOS`** ("disclosure
of the data is prohibited") is a third code.

| Column | Type | Official definition | Values / range (this file) | Missing / special |
|---|---|---|---|---|
| `NOME_DEPARTAMENTO` | str | Department responsible for the registration | 26 values | 2 empty |
| `NOME_SECCIONAL` | str | Sectional police station responsible for the registration | 95 values | 2 empty |
| `NOME_DELEGACIA` | str | Police station responsible for the registration | 485 values (incl. `DELEGACIA ELETRONICA*`) | 0 |
| `NOME_MUNICIPIO` | str | Municipality of registration | 20 values; `CAMPINAS` 139,131 | 0 (one value has trailing spaces) |
| `NUM_BO` | str | Bulletin number | 130,848 distinct; mostly 6-character alphanumerics (e.g. `CZ3708`) from 2023; numeric in 2022 | 0 |
| `ANO_BO` | int | Year of the bulletin | 2022: 34,466 · 2023: 36,743 · 2024: 34,843 · 2025: 33,249 | 0. Differs from the registration year in 138 rows (BOs registered on 28–31 Dec carry the next year) |
| `DATA_REGISTRO` | date | Date the occurrence was registered | 2021-12-24 … 2025-12-31 | 0 |
| `DATA_OCORRENCIA_BO` | date | Date of the occurrence | 1943-07-19 … 2025-12-31; 1,008 rows before 2022-01-01 | 1 unparseable (`1202-02-28`) |
| `HORA_OCORRENCIA_BO` | `HH:MM` | Time of the occurrence | 95,944 well-formed; 35 (2025) as `HH:MM:SS.0` | 43,322 missing (**31.1 %**: 34,004 empty + 9,318 `NULL`) |
| `DESC_PERIODO` | str | Period of the occurrence | `A noite`, `Pela manhã`, `A tarde`, `De madrugada`, `Em hora incerta` | 23,934 `NULL` (17.2 %), **all in 2025** (72.0 % of 2025 rows) |
| `DESCR_SUBTIPOLOCAL` | str | Sub-group of place types where the fact happened | 327 values; `Via Pública` 98,602 | 600 empty |
| `BAIRRO` | str | Neighbourhood of the occurrence (free text) | 2,525 values | 1,332 empty + 78 `NULL` |
| `LOGRADOURO` | str | Address of the facts | 14,847 values | **18,345 redacted (13.17 %)** |
| `NUMERO_LOGRADOURO` | str | Street number of the facts | 3,448 values | 13,132 redacted, 5,214 empty, 86 `NULL` |
| `LATITUDE` | str→float, decimal degrees | Latitude of the occurrence | see quality notes | 13,144 redacted, 9,454 empty, 1,597 `NULL`, 190 `NUL,L`, 1 `0.0,`, 5,626 rows with lat or long = `0` |
| `LONGITUDE` | str→float, decimal degrees | Longitude of the occurrence | — | as `LATITUDE` |
| `NOME_DELEGACIA_CIRCUNSCRICAO` | str | Police station with jurisdiction over the place of the fact | 27 values; `01º`–`13º D.P. CAMPINAS` + `04º D.P. AEROP/TUR-VIRACOPOS` hold 139,246 rows | 0 |
| `NOME_DEPARTAMENTO_CIRCUNSCRICAO` | str | Department with jurisdiction over the place of the fact | `DEINTER 2 - CAMPINAS` 139,274 | 0 |
| `NOME_SECCIONAL_CIRCUNSCRICAO` | str | Sectional with jurisdiction over the place of the fact | 5 values | 0 |
| `NOME_MUNICIPIO_CIRCUNSCRICAO` | str | Municipality of the station with jurisdiction over the place of the fact | `CAMPINAS` 139,255 | 0 |
| `RUBRICA` | str | Legal nature of the occurrence (penal-code article) | 64 values | 1 empty |
| `DESCR_CONDUTA` | str | Paragraphs, clauses or circumstances related to the rubrica | 56 values | 22,456 empty + 8,281 `NULL` (22.1 %) |
| `NATUREZA_APURADA` | str | Crime classification "verified and validated by the SPDados team, together with the Civil and Military Police, through analysis and audit of the records" | 44 raw strings → 23 slugs; most offences appear in two spellings (2025 is UPPER-CASE, e.g. `FURTO - OUTROS` vs `Furto - Outros`) | 0. All 44 map to a slug (0 unmapped) |
| `MES_ESTATISTICA` | int 1–12 | Month the occurrence entered official statistics (= registration month) | equals the `DATA_REGISTRO` year-month for 99.45 % of rows (766 differ) | 0 |
| `ANO_ESTATISTICA` | int | Year the occurrence entered official statistics (= registration year) | 2022: 34,582 · 2023: 36,627 · 2024: 34,840 · 2025: 33,252 | 0 |

## Known quality issues (computed)

- **Coordinates.** 114,915 rows have numeric lat/long. Of these:
  - 5,625 are exactly `(0, 0)`, **all in 2025**. In 2025, redacted coordinates
    are encoded as `0` rather than with the `VEDAÇÃO…` text (0 `VEDAÇÃO`
    coordinates in 2025; 5,213 of the 5,625 zero rows have a redacted
    `LOGRADOURO`).
  - 728 rows (all ANO_ESTATISTICA 2022) lack the decimal point
    (e.g. `-2290311876.0`).
  - 108,530 fall inside a loose Campinas bounding box (lat −23.3…−22.5,
    lon −47.5…−46.7).
- **Share of rows with a usable coordinate (inside that box), by
  ANO_ESTATISTICA:** 2022 75.1 %, 2023 79.9 %, 2024 79.4 %, 2025 77.1 %.
- **Redacted coordinates** are concentrated in particular offences:
  *Lesão corporal dolosa* (5,846 rows), *Estupro de vulnerável* (all 749 in
  2022–24), *Estupro* (all 269 in 2022–24).
- **Stacking:** the top non-zero coordinate holds 415 rows. 115 coordinates hold
  ≥ 50 rows each, 17,178 rows in total including `(0,0)` (see #9 /
  street-level geocoding).
- **Occurrence date before 2022:** 1,008 rows; the earliest is 1943-07-19.
  These are bulletins filed in 2022+ for older facts, and they are removed by
  the analysis window.
- **Reporting lag** (`DATA_REGISTRO − DATA_OCORRENCIA_BO`, n = 139,300): median
  1 day, p90 10 days, p99 181 days. 6 rows have a negative lag.
- **Missing time:** `HORA_OCORRENCIA_BO` is missing for 31.1 % of all rows and
  35.1 % of property crimes in the analysis window. Hour-of-day analyses use
  only the remainder.
- **Year-dependent encoding:** different missing codes, upper-case
  `NATUREZA_APURADA`, and `DESC_PERIODO` missing in 2025. All are artefacts of
  the two-source assembly described above.

## Code that reads it

| Code | Columns used |
|---|---|
| `etl/sources.py:extract_crimes` | all columns. The redacted `LATITUDE` becomes NaN, then lat/long are made numeric. `NUM_BO`, `ANO_BO`, `MES_/ANO_ESTATISTICA` are typed; `DATA_REGISTRO`, `DATA_OCORRENCIA_BO` are parsed |
| `scripts/02_clean/load_database.py:main` → `fato_crimes` | rows with non-null lat/long only. Uses `NUM_BO, ANO_BO, DATA_OCORRENCIA_BO, HORA_OCORRENCIA_BO, DESC_PERIODO, DESCR_SUBTIPOLOCAL, BAIRRO, NATUREZA_APURADA, LATITUDE, LONGITUDE`, plus `cd_setor`/`grid_id` (point-in-polygon) and `crime_slug`/`crime_group` (`etl/taxonomy.py`) |
| `crime/data/cleaning.py:RawPaths.crimes`, `filter_events` | `data_ocorrencia` (renamed), `crime_slug` |
| `paper/presentation_puc/src/data_audit.py` | N funnel, geocoding completeness, `source_sha256` |

The ETL never loads `DATA_REGISTRO`, `RUBRICA`, `DESCR_CONDUTA`, `LOGRADOURO`,
the `NOME_*` station columns or `*_ESTATISTICA` into the database.
