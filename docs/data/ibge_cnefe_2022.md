# IBGE CNEFE 2022 address points, Campinas (`inputs/data/qg_810_endereco_Munic3509502.json`)

*Cadastro Nacional de Endereços para Fins Estatísticos* (CNEFE) of the 2022
census: every address IBGE listed in Campinas, with its *espécie* (type of
use). The project uses it for land-use counts (commerce, education, health,
religious) per tract or cell.

## Provenance

| Item | Value |
|---|---|
| Producer | IBGE, CNEFE, Censo Demográfico 2022 |
| URL (verified listing 2026-10-22) | `https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/Censo_Demografico_2022/Arquivos_CNEFE/GeoJSON/Municipio_20240910/35_SP/qg_810_endereco_Munic3509502.json.zip`. The server has this zipped name; the local copy is the unzipped JSON, and it was not hash-compared with the server copy |
| Official dictionary | `…/Arquivos_CNEFE/GeoJSON/Dicionario_CNEFE_Censo_2022_GeoJSON.xls` (verified listing; **not in repo**) |
| Download date | Unknown. Committed in `6891c8b` (2026-08-16). The release folder is dated `20240910` |
| Licence | Not stated. **To check** |
| Format | GeoJSON FeatureCollection, `crs` = **EPSG:4674** (SIRGAS 2000), Point geometry |
| Size | 241,047,771 bytes |
| SHA-256 | `f871b5273a1a176f40a85bfd1cec690b67aaf70f6c934143b6a8028b5ec9f2fd` |
| Rows | 574,086 features; bounds lon −47.244…−46.822, lat −23.062…−22.724 |

## What one row is

The official dictionary says: *"Cada registro representa uma espécie existente
no endereço"*. One row is **one espécie (use type) at one address**.

An address with several uses therefore appears several times. There are
4,849 rows with a repeated `COD_UNICO_ENDERECO`, so the file holds 569,237
distinct addresses. There are no fully identical rows.

## Columns

Definitions and categories are from `Dicionario_CNEFE_Censo_2022_GeoJSON.xls`.

| Column | Type | Official definition | Values (Campinas) | Missing | Used |
|---|---|---|---|---|---|
| `COD_UNICO_ENDERECO` | str | Unique address code | 569,237 distinct | 0 | **dedup key** |
| `COD_UF`, `COD_MUNICIPIO` | str | State / municipality code | 35 / 3509502 | 0 | no |
| `COD_SETOR` | str (16) | Tract code | 2,499 distinct; **all end in `P`** (meaning of `P` **unverified**; the code strips it); 613 distinct codes (130,408 rows) are not 2022 tract ids after stripping | 0 | ETL `cd_setor` |
| `NUM_QUADRA`, `NUM_FACE` | int | Block number / block-face number (block = 0 outside urbanised areas) | — | 0 | no |
| `CEP` | str | Postal code | 8,610 distinct | 0 | ETL only |
| `DSC_LOCALIDADE` | str | Locality | 717 | 0 | ETL only |
| `LOGRAD_NUM`, `COMPLEMENTO` | str | Street + number / complement | — | `COMPLEMENTO` blank 288,493 | no |
| `NV_GEO_COORD` | int 1–6 | Geocoding level: 1 original 2022 coordinate, 2 modified (apartments at one number), 3 estimated, 4 block face, 5 locality, 6 tract | 1: 504,412 · 2: 63,685 · 3: 4,551 · 4: 1,425 · 5: 10 · 6: 3 | 0 | ETL only |
| `COD_TIPO_ESPECI` (dictionary: `COD_TIPO_ESPECIE`) | int | Building type of private dwellings: 101 house, 102 house in villa/condominium, 103 apartment, 104 other | 101: 322,394 · 103: 160,724 · 102: 16,465 · 104: 2,368 | null 72,135 (non-dwellings) | ETL only |
| `DSC_ESTABELECIMENTO` | str | Establishment name | filled for 100 % of espécie 4/5/6/8 | null 513,734 | ETL only |
| `COD_ESPECIE` | str | Address type: 1 private dwelling, 2 collective dwelling, 3 agricultural, 4 education, 5 health, **6 "other purposes"**, 7 under construction/renovation, 8 religious | rows: 1: 501,383 · 6: 54,898 · 7: 12,131 · 8: 1,863 · 5: 1,737 · 4: 1,096 · 2: 568 · 3: 276 (after global dedup: 6 → 50,499) | 0 | **yes** |
| geometry | Point, EPSG:4674 | — | — | 0 | **yes** |

Espécie 6 is officially *"Estabelecimento de outras finalidades"*, meaning
establishments for any other purpose. The project uses it as a **commerce
proxy**. It is not a commerce-specific category.

> **Update (2026-10-23):** deduplication is now on (`COD_UNICO_ENDERECO`,
> `COD_ESPECIE`) in both `crime/data/cleaning.py:poi_counts` and
> `etl/sources.py:extract_cnefe` (schema PK changed to the pair). Counts inside
> the 2022 tracts: espécie 6 54,892 (raw 54,898), 4 1,096, 5 1,737, 8 1,863.
> The PostGIS table must be reloaded for the ETL path to reflect this.

## Quality notes (computed)

- **The global deduplication drops some establishments.**
  `etl/sources.py:extract_cnefe` deduplicates on `COD_UNICO_ENDERECO` across
  all espécies before the database load, keeping the first row. Because a row
  is one espécie at an address, this removes establishments that share an
  address with another use:

  | Espécie | Rows in file | Kept after dedup | Dropped |
  |---|---|---|---|
  | 4 (education) | 1,096 | 1,053 | 43 |
  | 5 (health) | 1,737 | 1,582 | 155 |
  | 6 (other purposes) | 54,898 | 50,499 | 4,399, i.e. 8.0 % |
  | 8 (religious) | 1,863 | 1,745 | 118 |

  The database counts are therefore lower than the file counts. This affects
  `dim_cnefe_enderecos`, the `vw_*_features` `log_*_density` columns and
  `load_cnefe_points`.

  `crime/data/cleaning.py:commercial_counts` filters to espécie 6 *first* and
  then deduplicates. Within espécie 6, `COD_UNICO_ENDERECO` is unique, so it
  keeps all 54,898.

- **The `COD_SETOR` code disagrees with the polygon.** Among the 54,898
  espécie-6 points:
  - 15,594 lie in a 2022 tract polygon other than their `COD_SETOR`
    (after stripping `P`).
  - 6 lie outside every tract.
  - 549 distinct espécie-6 `COD_SETOR` codes are not 2022 tract ids.
  
  The `crime/data/cleaning.py:commercial_counts` docstring reports 15,594,
  which matches, and "540" codes. This session counted 549 distinct codes
  (wording or definition may differ; **unresolved**).
  
  `vw_sector_features` still joins on the code. `commercial_counts` uses
  point-in-polygon.

- **CRS.** The file declares EPSG:4674. `extract_cnefe` wraps it as
  EPSG:4326 without reprojecting (treated as equivalent).

## Code that reads it

| Code | Columns used |
|---|---|
| `etl/sources.py:extract_cnefe`, which feeds `dim_cnefe_enderecos` in `scripts/02_clean/load_database.py` | `COD_UNICO_ENDERECO, COD_SETOR, CEP, DSC_LOCALIDADE, NV_GEO_COORD, COD_TIPO_ESPECI, DSC_ESTABELECIMENTO, COD_ESPECIE`, geometry; plus `grid_id` (point-in-polygon) |
| `database/enrich.sql` (`vw_sector_features`, `vw_grid_features`) | `cod_especie` ∈ {4, 5, 6, 8}, `cd_setor` / `grid_id` |
| `crime/data/loaders.py:load_cnefe_points` (through `PostGISSource.cnefe_points`) | `cod_especie`, geometry |
| `crime/data/cleaning.py:commercial_counts` | `COD_UNICO_ENDERECO, COD_ESPECIE`, geometry (the file is read directly, with `where COD_ESPECIE = '6'`) |
| `crime/data/cleaning.py:cnefe_poi_points` → `scripts/04_analyse/run_core.py` (step `assoc`) | `COD_UNICO_ENDERECO, COD_ESPECIE`, geometry (espécies 4, 5, 6, 8; assigned to every support by point-in-polygon) |
