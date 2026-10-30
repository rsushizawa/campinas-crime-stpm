# Per-tract literacy, Censo 2022 (`inputs/data/Painel_IBGE_2022.csv`)

This file is the source of `literacy_rate`: literate / (literate + illiterate)
residents aged 15+.

## Provenance

| Item | Value |
|---|---|
| Who built the file | **Unverified.** The issue calls it "IBGE Painel" and the code calls it "the curated `Painel_IBGE_2022.csv` export". No script in the repo produces it |
| Underlying source (verified 2026-10-22) | Its 8 `alfabetizacao_*` columns are **identical, tract by tract, to IBGE *Agregados por Setores Censitários, Alfabetização*** for all 2,592 Campinas tracts. The file is `https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/Agregados_por_Setor_csv/Agregados_por_setores_alfabetizacao_BR.zip` (server Last-Modified 2024-11-12; SHA-256 of the copy downloaded on 2026-10-22 is `3b2de94e0099d9b6aa32bf967b1e96321a0f6ee7df674bbac984c3b751c8a17b`). A blank cell in the Painel corresponds to IBGE `X` (suppressed) or to a tract absent from the IBGE file |
| The 13 `basico_*` columns | come from a *Básico* table. They are not used and were not cross-checked. Their `AREA_KM2` precision differs from the 2026-05-20 *Básico* release |
| Download date | Unknown. Committed in `6891c8b` (2026-08-16) |
| Licence | Not stated. **To check** |
| Format | `,`-separated, UTF-8, decimal comma inside quoted `basico_AREA_KM2`, 22 columns, 2,592 rows |
| Size | 346,784 bytes |
| SHA-256 | `88d401518f62fae14c334fc750a4ef752719907982a767bd73d0c2d7849f6b6f` |

## What one row is

One row is one Campinas 2022 census tract (`CD_SETOR`, 15 digits, 2,592
unique, all with prefix `3509502`).

## Columns

The definitions are those of the IBGE dictionary
(`dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx`, sheet
*Dicionário não PCT*), matched by value.

| Painel column | IBGE var | Official definition | Blank (= IBGE `X` or absent) | Range | Used |
|---|---|---|---|---|---|
| `alfabetizacao_15 a 29 anos, Morador sabe ler e escrever` | V00852 | 15–29 years, resident can read and write | 94 | 0…497 | no |
| `… 15 a 29 anos, Morador não sabe ler e escrever` | V00853 | 15–29, cannot read and write | 928 | 0…11 | no |
| `… 30 a 59 anos, … sabe …` | V00854 | 30–59, can | 90 | 3…811 | no |
| `… 30 a 59 anos, … não sabe …` | V00855 | 30–59, cannot | 867 | 0…69 | no |
| `… 60 anos ou mais, … sabe …` | V00856 | 60+, can | 108 | 0…283 | no |
| `… 60 anos ou mais, … não sabe …` | V00857 | 60+, cannot | 685 | 0…47 | no |
| `alfabetizacao_15 anos ou mais, Morador sabe ler e escrever` | **V00900** | 15+, can read and write | **90** | 8…1,268 | **yes** |
| `alfabetizacao_15 anos ou mais, Morador não sabe ler e escrever` | **V00901** | 15+, cannot read and write | **589** | 0…114 | **yes** |
| `basico_SITUACAO` … `basico_CD_SUBDIST` (13 cols) | — | tract geography | 0 | — | no |

`etl/sources.py:_PAINEL_RENAME` renames the eight columns to `alfa_15_29_sabe`
… `alfa_15_mais_nao_sabe`.

## Quality notes (computed)

- **V00900 (15+ literate) is blank for 90 tracts.** These are the 69
  zero-population tracts absent from the IBGE file plus 21 suppressed (`X`)
  tracts. They are the same 21 tracts suppressed in the income table.
- **V00901 (15+ illiterate) is blank for 589 tracts:** 69 absent + 520 `X`.
  In **499** of them the literate count is present.
- Among non-blank V00901 values: 316 are 0, none are 1 or 2, and 1,687 are
  ≥ 3. This is consistent with IBGE suppressing small non-zero counts. The
  exact IBGE suppression rule is **not verified here**.
- How blanks are handled:
  - `crime/data/cleaning.py:tract_attributes` sets the illiterate count to 0
    when it is blank and the literate count is present (learner decision,
    2026-10-15; see that module's docstring). Tracts with both counts blank
    stay NaN.
  - `database/enrich.sql` (`vw_sector_features.literacy_rate`) uses
    `COALESCE(…, 0)` on both counts and returns NULL when their sum is 0.
    This is the same result for these data.

## Code that reads it

- `etl/sources.py:extract_literacy` (`PAINEL_CSV`) reads `CD_SETOR` and the 8
  `alfabetizacao_*` columns. It feeds `dim_setor_painel` in `scripts/02_clean/load_database.py`,
  which the views turn into `literacy_rate`.
- `scripts/02_clean/reload_painel.py:main` also reads it, through `extract_literacy`.
- `crime/data/cleaning.py:RawPaths.painel` produces `literacy_rate`, from
  `alfa_15_mais_sabe` and `alfa_15_mais_nao_sabe` only.

**Suggested:** read V00900/V00901 straight from the IBGE
*Alfabetização* zip, as the `extract_literacy` docstring already proposes, and
retire this hand-made CSV. The values are identical, so the switch changes no
number.
