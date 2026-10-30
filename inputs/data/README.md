# Data inventory

Each raw input in `inputs/data/` (never edited) has its own data dictionary under
[`docs/data/`](../docs/data/). Each dictionary covers the source, URL,
download date, licence, SHA-256, what one row represents, the columns, the
known quality issues (with numbers) and the code that reads it. The project
follows the datasheet idea of Gebru et al. (2021), *Datasheets for Datasets*.

Hashes were computed on 2026-10-22. "Status" is the current use by
`etl/`, `crime/` and `scripts/`.

| File | Source | Used for | Status | Dictionary |
|---|---|---|---|---|
| `inputs/data/crimes_campinas.csv` | SSP-SP *Dados Criminais*, hand-assembled (commit 6891c8b) | reference for the acquire diff only | **legacy**; superseded by `outputs/data/crimes_campinas.csv` (01_acquire) | [ssp_crimes_campinas.md](../docs/data/ssp_crimes_campinas.md) |
| `inputs/data/SPDadosCriminais_2025.xlsx` | SSP-SP | raw 2025 input (statewide) | read by `scripts/01_acquire` | [ssp_raw_inputs.md](../docs/data/ssp_raw_inputs.md) |
| `inputs/data/crimes_campinas_2022_2024.csv.bak` | SSP-SP (origin unknown) | raw 2022–2024 input | read by `scripts/01_acquire`; tracked in Git LFS (explicit exception to the `*.bak` ignore) | [ssp_raw_inputs.md](../docs/data/ssp_raw_inputs.md) |
| `inputs/data/geobr/census_tract_3509502_2022.parquet` | IBGE 2022 tracts via `geobr` | spatial unit | used | [ibge_census_tracts_2022.md](../docs/data/ibge_census_tracts_2022.md) |
| `inputs/data/grade_id25_2022.zip` | IBGE *Grade Estatística* 2022, quadrant ID_25 | grid unit (raw), PostGIS warehouse only | read by `extract_grid` (`load_database.py`) when the cache is missing; not used by `run_core.py` | [ibge_statistical_grid.md](../docs/data/ibge_statistical_grid.md) |
| `inputs/data/geobr/statistical_grid_2022_campinas.parquet` | clip of the above (made by `extract_grid`) | grid unit, PostGIS warehouse only (`dim_grid_cell`) | read by `load_database.py`; not used by `run_core.py` | [ibge_statistical_grid.md](../docs/data/ibge_statistical_grid.md) |
| `inputs/data/geobr/Agregados_por_setores_basico_BR_20260520.zip` | IBGE Censo 2022, Agregados por Setores, Básico | population `V0001`, households `V0007` | used (untracked) | [ibge_agregados_basico_2022.md](../docs/data/ibge_agregados_basico_2022.md) |
| `inputs/data/geobr/Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip` | IBGE Censo 2022, Rendimento do Responsável | income `V06004`, `V06006` | used (untracked) | [ibge_renda_responsavel_2022.md](../docs/data/ibge_renda_responsavel_2022.md) |
| `inputs/data/geobr/dicionario_de_dados_renda_responsavel_20260508.xlsx` | IBGE official dictionary | documentation | reference (untracked) | [ibge_renda_responsavel_2022.md](../docs/data/ibge_renda_responsavel_2022.md) |
| `inputs/data/Painel_IBGE_2022.csv` | IBGE Censo 2022, Alfabetização (values verified equal); compiler unverified | literacy `V00900`, `V00901` | used | [ibge_painel_literacy_2022.md](../docs/data/ibge_painel_literacy_2022.md) |
| `inputs/data/qg_810_endereco_Munic3509502.json` | IBGE CNEFE 2022 | address points, `COD_ESPECIE` | used | [ibge_cnefe_2022.md](../docs/data/ibge_cnefe_2022.md) |
| `inputs/data/map.geojson` | Campinas UTB (publisher unverified); **2010 Census attributes** | 93 UTB polygons (overlay); `rendatemei` is a count | used | [campinas_utb.md](../docs/data/campinas_utb.md) |
| (in memory, `scripts/04_analyse/run_core.py`) | assembled: property crime, tract × quarter / month | primary EHSA input | generated in memory | [property_tract_month_cube.md](../docs/data/property_tract_month_cube.md) |

## Acquire and clean (scripted)

`scripts/01_acquire/acquire_ssp.py` builds `outputs/data/crimes_campinas.csv`
(one row per offence record) from the two raw SSP-SP files, and
`scripts/02_clean/clean_bulletins.py` collapses it to one row per bulletin
(`outputs/data/bulletins_clean.parquet`). Rules and numbers:
[ssp_bulletins_clean.md](../docs/data/ssp_bulletins_clean.md). The legacy
`crimes_campinas.csv` is kept only so the scripted output can be compared with
it row for row (`outputs/data/acquire_report.json → vs_legacy`).

## Removed

Owner decision (2026-10-23, in the IC-Crime repository): unused or duplicate
files were removed with `git rm`; they stay recoverable from that
repository's history (tag `archive/pre-reset-2026-10-30`). Their datasheets are kept,
marked as removed. Last SHA-256 values:

```
aa310ab0dba79a672ba3485f5fb403b3687ca0ee4214ffbd8c6d82b5b1d11d7b  inputs/data/geobr/statistical_grid_3509502_2010.parquet
3ad3031f5503a4404af825262ee8232cc04d4ea6683d42c5dd0a2f2a27ac9824  inputs/data/grade_id35/grade_id35.cpg
3a9f7e55897350a9c1df7b055b05499a98f798c0448c8a93d9fb23191174cdfc  inputs/data/grade_id35/grade_id35.dbf
b7fe68a2eb827ea974a1a995a73676e095a366b383a10a66c7498300d1c58153  inputs/data/grade_id35/grade_id35.prj
424319a349d60f1cc24abb410cd6d8c0097dbf99f54a078cd40b83e2b1ae3b50  inputs/data/grade_id35/grade_id35.sbn
b03d18303726a03a5531fa6adfff0303c52718d27f109a7599ae0b0d767a98a4  inputs/data/grade_id35/grade_id35.sbx
2a66ca3aabaef9fe6893a2277cfa80343ec04a522deac192b7829d6330777600  inputs/data/grade_id35/grade_id35.shp
db723b8dcd3a6fdc441f7f30a0aab31013588101bf50f5495a2ef3b9ed63cc12  inputs/data/grade_id35/grade_id35.shp.xml
3e17aeabf7745ae4e39ae7945b245553abccfb4415453ca702451158f1c67965  inputs/data/grade_id35/grade_id35.shx
ec04624286233d699ebe69c7b9625744a1cfdfc8352126f30245bdef5e9bdc63  inputs/data/Agregados_por_setores_basico_BR.zip
f50182728f45d6562784b73b84b276be7d930e3c58ddc8c5feac1541d930b8d8  inputs/data/analitico_setor.geojson
```

- `Agregados_por_setores_basico_BR.zip`: byte-identical duplicate of
  `geobr/Agregados_por_setores_basico_BR_20260520.zip`.
- `analitico_setor.geojson`: legacy derived table; commerce per tract is now
  counted from CNEFE `COD_ESPECIE == 6` addresses by point-in-polygon
  (`crime.data.cleaning.commercial_counts`).
- `geobr/statistical_grid_3509502_2010.parquet`, `grade_id35/*`: never read by code.

## SHA-256

```
19d7cf1f3f0e4b987e7feed679a601767ac7699ceeb37ae6854c24572ee64cda  inputs/data/crimes_campinas.csv
4ab5b40229d245a0f50b65e74ea9e9b7750bbdb3bff7b02d961d78b9c4143d8c  inputs/data/SPDadosCriminais_2025.xlsx
6f98e51cb92798d439239e9fd6e56def7a4badbd2b4f9d13ccf19b041ccabc8f  inputs/data/crimes_campinas_2022_2024.csv.bak
25c880643811a73a43d6eaafe3961a5b234cd46def499c4c318fd0d5e315557e  inputs/data/geobr/census_tract_3509502_2022.parquet
fa9f041962622254a17a3a5ef0f883152ce12ac925204c6be1618f545f4f37ab  inputs/data/grade_id25_2022.zip
2f1ba2b6514d36c1c71819cd23402c3a1ae802fe4edf1c8402aca933df128461  inputs/data/geobr/statistical_grid_2022_campinas.parquet
ec04624286233d699ebe69c7b9625744a1cfdfc8352126f30245bdef5e9bdc63  inputs/data/geobr/Agregados_por_setores_basico_BR_20260520.zip
141c83e7635674e7e2c941e55f98811e538fcbf2e1e1125b0aa7892c260f4a23  inputs/data/geobr/Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip
fea6e2b2439eeb167c6fa9c136ed7cb13ebcb06f4c875d634e3e2578c668a48d  inputs/data/geobr/dicionario_de_dados_renda_responsavel_20260508.xlsx
88d401518f62fae14c334fc750a4ef752719907982a767bd73d0c2d7849f6b6f  inputs/data/Painel_IBGE_2022.csv
f871b5273a1a176f40a85bfd1cec690b67aaf70f6c934143b6a8028b5ec9f2fd  inputs/data/qg_810_endereco_Munic3509502.json
5dc6343b73db910e726a8047550983024a3b062d7e903296820a9a9844a2e39e  inputs/data/map.geojson
```
