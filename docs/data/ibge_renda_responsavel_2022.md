# IBGE Censo 2022, Rendimento do Responsável por setor (`Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip`)

Per-tract income of household heads. This table is the source of
`income_head_mean` / `income_head_median`.

## Provenance

| Item | Value |
|---|---|
| Producer | IBGE, Censo Demográfico 2022, *Agregados por Setores Censitários, Rendimento do Responsável* (released 2026-05-08, per the file name and the `etl/sources.py` docstring) |
| URL (verified listing 2026-10-22) | `https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios_Rendimento_do_Responsavel/Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip`. The same URL is hard-coded as `etl/sources.py:_IBGE_RENDA_ZIP` |
| Local file | `inputs/data/geobr/Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip` (untracked). File mtime 2026-10-15 15:24, probably the download time |
| SHA-256 | `141c83e7635674e7e2c941e55f98811e538fcbf2e1e1125b0aa7892c260f4a23` |
| Official dictionary | `inputs/data/geobr/dicionario_de_dados_renda_responsavel_20260508.xlsx` (untracked, mtime 2026-10-15). SHA-256 `fea6e2b2439eeb167c6fa9c136ed7cb13ebcb06f4c875d634e3e2578c668a48d`. Also on the FTP in the same folder (verified listing) |
| Licence | Not stated. **To check** |
| Format | zip containing `Agregados_por_setores_renda_responsavel_BR.csv`. `;`-separated, latin-1, **decimal point**. This differs from the decimal comma used in *Básico* |
| Coverage | Brazil: 458,772 tracts × 7 columns. Campinas: **2,523** tracts |

## What one row is

One row is one 2022 census tract (`CD_SETOR`) that has occupied permanent
private households.

## Columns

Definitions are quoted from the *Dicionário Renda Responsável* sheet.

| Column | Unit | Official definition | Campinas (non-suppressed) | Used |
|---|---|---|---|---|
| `CD_SETOR` | — | tract code | 2,523 | key |
| `V06001` | persons | Persons responsible in occupied permanent private households | 5…575 | no |
| `V06002` | persons | Residents in occupied permanent private households | 8…1,630 | no |
| `V06003` | persons² | Variance of the number of residents in occupied permanent private households | 0.3…15.44 | no |
| `V06004` | R$ / month (nominal, 2022) | *Valor do rendimento nominal médio mensal das pessoas responsáveis com rendimentos por domicílios particulares permanentes ocupados*: mean nominal monthly income of household heads **with income** | 1,115.33…27,295.92; median 3,375.08 | **yes**, as `income_head_mean` |
| `V06005` | (R$)² | Variance of the household-head nominal monthly income | 43,022.92…1.36 × 10¹⁰ | no |
| `V06006` | R$ / month | Median nominal monthly income of household heads with income | 900…21,000; median 2,500 | **yes**, as `income_head_median` |

**Missing-value code:** `X`, meaning suppressed by IBGE for confidentiality.
The code converts it to NaN with `pd.to_numeric(errors='coerce')` and does not
impute it.

## Quality notes (computed)

Of the 2,592 Campinas tracts, **90 have no income**:

- **69 tracts are absent from the file.** These are exactly the 69 tracts with
  `V0001 == 0` (zero residents) in *Básico*.
- **21 tracts are present but suppressed (`X`)** in all six variables. Their
  population (*Básico* `V0001`) ranges from 2 to 358 residents, with a median
  of 7, and sums to 941.

The issue text described these as "90 IBGE-suppressed tracts". Strictly, only
21 are suppressed; the other 69 are uninhabited tracts that IBGE does not
list. The same 21 + 69 split holds for the literacy table (see
[ibge_painel_literacy_2022.md](ibge_painel_literacy_2022.md)).

Income is that of the household head only, among heads **with** income, in
nominal R$ of the 2022 reference date. It is not per-capita income.

## Code that reads it

- `etl/sources.py:extract_income_2022` reads `CD_SETOR`, `V06004` and
  `V06006`.
- `etl/census.py:tract_attributes` (units stage) stores them as
  `income_head_mean` and `income_head_median` in `dim_census_tract`.
