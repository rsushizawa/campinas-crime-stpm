# SSP-SP raw inputs (`SPDadosCriminais_2025.xlsx`, `crimes_campinas_2022_2024.csv.bak`)

> **Update (#13):** both files are now read by `scripts/01_acquire/acquire_ssp.py`,
> which applies one municipality filter (`NOME_MUNICIPIO_CIRCUNSCRICAO`) to all
> years. Rules and the row-for-row comparison with the legacy CSV:
> [ssp_bulletins_clean.md](ssp_bulletins_clean.md).

These are the two raw files that, by inference, were combined into
[`crimes_campinas.csv`](ssp_crimes_campinas.md). **No code in the repo reads
either file.** The combining step is not scripted; that is a known gap, to be
scripted in #13 (Acquire stage).

## `inputs/data/SPDadosCriminais_2025.xlsx`

| Item | Value |
|---|---|
| Publisher | SSP-SP (SPDados) |
| URL | `https://www.ssp.sp.gov.br/estatistica/consultas` (cited in `paper/companion/companion.tex`). **Unverified** that this is the download page for this file |
| Download date | Unknown; committed in `6891c8b` (2026-08-16), unchanged since |
| Licence | Not stated. **To check** |
| Size | 195,899,014 bytes |
| SHA-256 | `4ab5b40229d245a0f50b65e74ea9e9b7750bbdb3bff7b02d961d78b9c4143d8c` |
| Sheets | `CAMPOS_DA_TABELA_SPDADOS` (official field dictionary, 30 fields + a note on `NULL`); `JAN-JUN_2025` (585,427 data rows); `JUL-DEZ_2025` (575,705 data rows) |
| Coverage | **Whole state of São Paulo**, 2025 registrations: 1,161,132 rows |
| One row | one offence classification on one bulletin (same grain as the CSV) |

Columns: the 25 CSV columns (see [ssp_crimes_campinas.md](ssp_crimes_campinas.md)),
plus five more:

- `DESCR_TIPOLOCAL`: group of place types
- `CMD`: Military-Police command area
- `BTL`: battalion area
- `CIA`: company area
- `CD_IBGE`: IBGE municipality code

The circumscription columns are spelled `…_CIRCUNCRIÇÃO` in the data sheets
and `…_CIRCUNSCRICAO` in the dictionary sheet. Coordinates are numeric, and
redacted coordinates appear as `0`.

Campinas subset (computed): 33,252 rows with `NOME_MUNICIPIO == "CAMPINAS"`
and 33,252 with `CD_IBGE == 3509502`. Of those rows, 33,249 have `ANO_BO`
2025 and 3 have 2024. The same count, 33,252, has
`NOME_MUNICIPIO_CIRCUNCRIÇÃO == "CAMPINAS"`, but 46 rows satisfy only one of
the two municipality fields. The 2025 part of `crimes_campinas.csv` matches the
`NOME_MUNICIPIO` (registration-municipality) selection.

## `inputs/data/crimes_campinas_2022_2024.csv.bak`

| Item | Value |
|---|---|
| Publisher | SSP-SP (presumed; same 25-column layout as the CSV) |
| Origin | **Unknown.** Neither the statewide 2022–2024 source files nor a script are in the repo |
| Git status | Added in `6891c8b` (2026-08-16), untracked in `038adab` (2026-09-05), **re-tracked in Git LFS in #13** (owner decision; explicit `.gitignore` / `.gitattributes` exception) |
| Size / rows | 37,749,633 bytes; 106,049 rows (ANO_BO 2022: 34,466 · 2023: 36,743 · 2024: 34,840) |
| SHA-256 | `6f98e51cb92798d439239e9fd6e56def7a4badbd2b4f9d13ccf19b041ccabc8f` |
| Filter (inferred) | `NOME_MUNICIPIO_CIRCUNSCRICAO == "CAMPINAS"` (100 % of rows) |

Every `.bak` row appears unchanged in `crimes_campinas.csv`; an outer join on
all 25 columns found 0 `.bak`-only rows. The CSV's 2022–2024 slice has 3
additional rows (ANO_BO 2024, ANO_ESTATISTICA 2025), and those come from the
2025 xlsx.

**Use:** none in code (`grep` over `etl/`, `crime/`, `scripts/`, `notebooks/`,
`paper/`). It is the only surviving copy of the 2022–2024 raw extract, so it
is needed to rebuild `crimes_campinas.csv` until #13 re-acquires the
statewide 2022–2024 files. Read by `scripts/01_acquire` (#13), which keeps it as a tracked raw input.
