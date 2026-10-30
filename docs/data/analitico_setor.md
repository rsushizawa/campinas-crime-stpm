# `inputs/data/analitico_setor.geojson`: legacy derived tract table (not a raw source)

> **Removed in #13** (owner decision, 2026-10-23; recoverable from git history before this commit). Its only reader, the deck commerce-density map
> (`paper/presentation_puc/src/make_fapesp_figs.py`), now counts CNEFE 2022
> `COD_ESPECIE == 6` addresses per tract by point-in-polygon
> (`crime.data.cleaning.commercial_counts`): 54,892 addresses in 2,228 tracts,
> against 43,408 `total_comercio` in this legacy file.

## What it is

This is **not a raw dataset.** It is a per-tract analytic table produced by an
earlier version of this project. No script in the current repo produces it.
It has 2,592 rows (one per 2022 tract) and 81 columns:

- the `geobr` tract attributes (`code_tract`, `name_*`, `code_*`, `situacao`,
  `area_km2_x`)
- `cd_setor`
- crime counts: `total_crimes`; `periodo_*`; `dia_*` (weekday); `mes_*`;
  `ano_2022`…`ano_2024`; `nat_*` per `NATUREZA_APURADA`
- `populacao_total`
- `total_comercio`, `densidade_comercio_km2`
- `crimes_por_100k`, `densidade_pop_km2`, `lat_centroide`, `long_centroide`,
  `n_setores`, `area_km2_y`

The crime counts cover **2022–2024 only**, which suggests the table was built
from the `.bak` CSV (inferred).

| Item | Value |
|---|---|
| Producer | this project, legacy pipeline (code not in the current tree) |
| Git | added in `6891c8b` (2026-08-16). The ETL rebuild in `1415284` (2026-07-10, "drop analitico_setor") had already removed it as a database source |
| CRS | CRS84 (lon/lat) |
| Size | 6,810,730 bytes |
| SHA-256 | `f50182728f45d6562784b73b84b276be7d930e3c58ddc8c5feac1541d930b8d8` |
| Licence | n/a (derived) |

Column definitions are **unverified**. The code that defined them is gone.

## Use

- **Not read by `etl/` or `crime/`.**
- One reader remains: `paper/presentation_puc/src/make_fapesp_figs.py:_enriched`
  uses `cd_setor` and `total_comercio`. It feeds the deck's commerce-density
  layer (`layer_commerce_density`).
- `grep` over `scripts/`, `notebooks/` and `database/` finds no other
  reference.

Its `total_comercio` duplicates what `crime/data/cleaning.py:commercial_counts`
now computes reproducibly from CNEFE. How `total_comercio` was defined is
unknown, so the two may differ.

**Unused by the library. Removed in #13 (owner decision)**, after
`make_fapesp_figs.py` was switched to `commercial_counts`.
