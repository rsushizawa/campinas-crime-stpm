# SSP-SP bulletins, scripted acquire + one row per bulletin (`outputs/data/`)

Issue #13. This page documents the two scripted tables that replace the
hand-assembled `inputs/data/crimes_campinas.csv` as the source of every crime
count. All numbers come from `outputs/data/acquire_report.json`,
`dedup_report.json` and `funnel.json` written on 2026-10-22 by the stage
scripts (`make acquire clean-data`).

## Stage 01 — acquire (`scripts/01_acquire/acquire_ssp.py`, rules in `etl/acquire.py`)

| Item | Value |
|---|---|
| Inputs | `inputs/data/crimes_campinas_2022_2024.csv.bak` (106,049 rows, SHA-256 `6f98e51c…`) · `inputs/data/SPDadosCriminais_2025.xlsx` (1,161,132 statewide rows, SHA-256 `4ab5b402…`) |
| Output | `outputs/data/crimes_campinas.csv` — 139,301 rows, one row per **offence record**, the 25 legacy columns + `COORD_STATUS` + `SOURCE` |

**Municipality filter — one rule for all years** (confirmed by the owner, 2026-10-23):
`NOME_MUNICIPIO_CIRCUNSCRICAO == "CAMPINAS"` (municipality of the police
station with jurisdiction over the *place of the fact*). Reasons: (1) the
analysis assigns events to Campinas tracts by their location, so a
place-of-fact filter is the consistent one; (2) it is the only filter that can
be applied to 2022–2024, since the `.bak` already contains only those rows
(0 rows of the `.bak` fail it). In the 2025 xlsx the registration filter used
for the legacy CSV (`NOME_MUNICIPIO`, equal in count to `CD_IBGE == 3509502`)
and this filter each select 33,252 rows and share 33,206:

- 46 rows are **added** (fact in Campinas, registered elsewhere — Hortolândia 9,
  Valinhos 9, Paulínia 7, Sumaré 7, Monte Mor 4, São Paulo 4, Vinhedo 2,
  Caconde 1, "OUTRO PAIS" 1, Itatinga 1, Indaiatuba 1);
- 46 rows are **dropped** (registered in Campinas, fact elsewhere — Sumaré 19,
  Valinhos 9, Hortolândia 7, Paulínia 6, Indaiatuba 2, Vinhedo 1, São Paulo 1,
  Jaguariúna 1).

The rows are listed in `outputs/data/acquire_filter_diff_rows.csv`.

**Missing tokens → missing:** `''` 82,603 cells, `'NULL'` 44,893,
`'NUL,L'` 382 (191 rows × 2 coordinates; the artefact is in the raw xlsx).
4,840 cells had leading/trailing whitespace stripped. The redaction text
`VEDAÇÃO DA DIVULGAÇÃO DOS DADOS RELATIVOS` is kept in text columns.

**Coordinates (`COORD_STATUS`):**

| Status | Rows | Rule |
|---|---|---|
| `ok` | 108,520 | numeric, inside the loose Campinas box (lat −23.3…−22.5, lon −47.5…−46.7) |
| `fixed_decimal` | 728 | digits without a decimal point (all 2022), e.g. `-2290311876.0` → `-22.90311876`; the point is placed after the two integer digits and kept only if the result is in the box |
| `zero` | 5,632 | `(0,0)` — the 2025 redaction code — incl. the `'0.0,'` artefact; set to missing |
| `redacted` | 13,144 | `VEDAÇÃO…` (2022–2024); missing |
| `missing` | 11,245 | empty / `NULL` / `NUL,L`; missing |
| `invalid` | 32 | numeric but outside the box (e.g. São Paulo city coordinates); set to missing |

**Times:** `HORA_OCORRENCIA_BO` written as `HH:MM`; 23,930 2025 values were
`HH:MM:SS`. 2,611 of them have non-zero seconds, which are truncated (the
hour and minute are never changed).

**Row-for-row comparison with the legacy CSV** (both files normalised with the
same rules, then all 25 columns matched as a multiset): 139,255 of 139,301
rows are identical; 46 rows are only in the new file and 46 only in the
legacy file — exactly the municipality-filter rows above. No other row
differs.

## Stage 02 — one row per bulletin (`scripts/02_clean/clean_bulletins.py`, rule in `etl/clean.py`)

A bulletin is `NUM_BO + ANO_BO + NOME_DELEGACIA`. In the acquired table, 941
bulletins have more than one record (971 extra rows); in 935 of them the
records differ in `NATUREZA_APURADA`; 1 row is an exact duplicate. (On the
legacy CSV the same code gives the 939 / 969 / 933 / 1 of #11; the 2 extra
bulletins come from the filter change.) The two sources share no bulletin key.

**Kept record = highest maximum penalty** of the base form (caput), in years,
table owner-approved 2026-10-22 and held as data in
`etl/taxonomy.py:MAX_PENALTY`:

| Slug | Max (years) | Legal basis |
|---|---|---|
| `latrocinio` | 30 | CP art. 157 §3 II |
| `homicidio_doloso` | 20 | CP art. 121 |
| `extorsao_sequestro` | 15 | CP art. 159 |
| `estupro_vulneravel` | 15 | CP art. 217-A |
| `trafico_entorpecente` | 15 | Lei 11.343/2006 art. 33 |
| `tentativa_homicidio` | 13.33 | CP art. 121 c/c art. 14 II (20 × 2/3) |
| `lesao_corporal_morte` | 12 | CP art. 129 §3 |
| `roubo_outros`, `roubo_veiculo`, `roubo_carga`, `roubo_banco` | 10 | CP art. 157 |
| `estupro` | 10 | CP art. 213 |
| `porte_arma` | 4 | Lei 10.826/2003 art. 14 |
| `furto_outros`, `furto_veiculo`, `furto_carga` | 4 | CP art. 155 |
| `homicidio_culposo_transito` | 4 | CTB art. 302 |
| `homicidio_culposo_outros` | 3 | CP art. 121 §3 |
| `lesao_culposa_transito` | 2 | CTB art. 303 |
| `lesao_corporal_dolosa` | 1 | CP art. 129 |
| `lesao_culposa_outras` | 1 | CP art. 129 §6 |
| `porte_entorpecente` | 0 | Lei 11.343/2006 art. 28 (no imprisonment) |
| `apreensao_entorpecente` | −1 | seizure record, not an offence (lowest) |

Ties: a specific slug beats `*_outros`/`*_outras`. A slug without an entry
raises; an unmapped `NATUREZA_APURADA` ranks lowest and is reported (0 in this
data). **Residual ties** (same penalty, both specific): 4 bulletins — 2 ×
`furto_veiculo` + `porte_arma`, 1 × `roubo_carga` + `roubo_veiculo`, 1 ×
`estupro` + `roubo_veiculo` — keep the first record in source order. The last
case decides between groups (sexual vs property): the first record in
source order is kept there too. **Rule confirmed by the owner (2026-10-23):**
residual ties keep the first record in source order, including the
`estupro` + `roubo_veiculo` bulletin.

**Group effect.** 138,330 bulletins remain (971 rows removed). Property:
109,708 property records → 109,687 bulletins with at least one property record
→ **109,632 bulletins kept as property**. 55 bulletins that carry a property
record are now counted in a more severe group: property+violent → violent 22,
drug+property → drug 14, property+sexual → sexual 14,
bodily_harm+property+sexual → sexual 3, property+traffic → traffic 2.
Conversely, 240 multi-group bulletins stay property and leave the other group
(bodily_harm+property 183, drug+property 37, property+traffic 20). Full table:
`outputs/data/dedup_group_transitions.csv`.

## N funnel (`outputs/data/funnel.json`)

| Stage | All | Property |
|---|---|---|
| offence records (acquired CSV) | 139,301 | 109,708 |
| bulletins | 138,330 | 109,632 |
| occurrence date in 2022-01-01 … 2025-12-31 | 137,323 | 108,914 |
| … with a usable coordinate (`ok` / `fixed_decimal`) | 107,912 | 90,463 |
| … inside a 2022 Campinas tract (**cube input**) | 107,859 | 90,436 |

All 728 repaired 2022 coordinates fall inside a 2022 tract; none of them is a
property bulletin, so they do not change the property cube.

## Validation (`scripts/03_test/validate_data.py`, `etl/schemas.py`)

pandera checks on the bulletin table and the cube input (parquet and
PostGIS): unique bulletin key, slugs/groups in the taxonomy, no `(0,0)`,
coordinates in the box or missing (and present iff `COORD_STATUS` is
ok/fixed_decimal), occurrence date in the window and every point inside the
union of 2022 tracts (cube input), counts equal to the funnel.
