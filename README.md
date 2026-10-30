# campinas-crime-stpm

Classical space-time pattern mining of police-recorded crime in Campinas
(São Paulo, Brazil), 2022–2025. The project rebuilds, in open Python
(PySAL / esda, libpysal, scikit-learn, statsmodels), the workflow of the Esri
ArcGIS Pro *Space Time Pattern Mining* and *Spatial Statistics* toolboxes —
global and local spatial autocorrelation, Getis–Ord hot spots, the space-time
cube, Emerging Hot Spot Analysis and Time Series Clustering — and adds the
checks a publication needs: the same analysis on five spatial supports and
three neighbourhood definitions (MAUP and weights sensitivity), point-pattern
statistics on the raw locations, a Knox space–time interaction test, and
rank / bivariate spatial association with 2022 census and address-register
features. Every number is produced by one scripted, seeded pipeline from the
raw public files; no database is required.

## Study area and period

- **Area.** Municipality of Campinas, SP (IBGE code 3509502), 2,592 census
  tracts of the 2022 IBGE tract mesh, 794.8 km² (EPSG:31983, SIRGAS 2000 /
  UTM 23S).
- **Period.** Occurrence dates 2022-01-01 … 2025-12-31.
- **Events.** SSP-SP occurrence bulletins, collapsed to one row per bulletin:
  139,301 offence records → 138,330 bulletins → 137,323 in the period →
  107,912 with a usable coordinate → 107,859 inside a tract
  (`outputs/data/funnel.json`). Sexual crimes have no published coordinates
  and are analysed in time only.

## Methods

Pipeline order (details, parameters and the differences from the Esri tools:
[`docs/METHODS.md`](docs/METHODS.md)):

| Step | Method | Citation |
|---|---|---|
| when | STL decomposition of the monthly series | Cleveland et al. (1990), *J. Official Statistics* 6(1) |
| where | Global Moran's I | Moran (1950), *Biometrika* 37(1/2) |
| where | Getis–Ord Gi* (analytic z, two-sided p) | Ord & Getis (1995), *Geographical Analysis* 27(4) |
| where | Local Moran's I (LISA, 499 permutations) | Anselin (1995), *Geographical Analysis* 27(2) |
| all local tests | Benjamini–Hochberg FDR | Benjamini & Hochberg (1995), *JRSS B* 57(1) |
| change | Emerging Hot Spot Analysis (space-time Gi* + Mann–Kendall) | Esri, "How Emerging Hot Spot Analysis works"; Mann (1945), *Econometrica* 13 |
| change | Hamed–Rao autocorrelation correction of Mann–Kendall | Hamed & Rao (1998), *Journal of Hydrology* 204 |
| change | Space-time LISA (per-bin local Moran) | Anselin (1995) |
| tsc | Time Series Clustering, k by pseudo-F | Caliński & Harabasz (1974), *Communications in Statistics* 3(1) |
| maup | Support and weights sensitivity (agreement, Jaccard, kappa) | Openshaw (1984), CATMOG 38; Cohen (1960), *Educ. Psychol. Measurement* 20(1) |
| points | Ripley's K as Besag's L, CSR envelope | Ripley (1976), *J. Applied Probability* 13(2); Besag & Diggle (1977), *Applied Statistics* 26(3) |
| points | Average nearest neighbour index | Clark & Evans (1954), *Ecology* 35(4) |
| points | Kernel density (quartic) | Silverman (1986), *Density Estimation for Statistics and Data Analysis* |
| knox | Knox space–time interaction test (Monte Carlo) | Knox (1964), *Applied Statistics* 13(1) |
| assoc | Spearman rank correlation | Spearman (1904), *American Journal of Psychology* 15 |
| assoc | Global / local bivariate Moran's I | Wartenberg (1985), *Geographical Analysis* 17(4) |
| assoc | Areal interpolation of population by area share | Goodchild & Lam (1980), *Geo-Processing* 1 |

Spatial weights use libpysal (Rey & Anselin 2007, *Review of Regional
Studies* 37(1)). Known limitations are listed at the end of
[`docs/METHODS.md`](docs/METHODS.md#known-limitations).

## Repository layout

```
crime/            the library (layers: core <- data <- points / esri / stats <- viz)
  core/           Dataset container, metadata, configuration (paths, CRS)
  data/           supports and point assignment (units.py), raw-file cleaning and
                  tract attributes (cleaning.py), provenance, optional PostGIS access
  esri/           weights, Moran, Gi*/LISA, cube, Mann-Kendall, EHSA, space-time LISA,
                  time series clustering, MAUP
  stats/          descriptive/STL, correlation, bivariate Moran, Knox, agreement metrics
  points/         Ripley's L, nearest-neighbour index, kernel density
  viz/            maps and charts (draw results only)
etl/              acquire / clean rules for the SSP-SP files, taxonomy, IBGE readers
scripts/
  01_acquire/     raw SSP-SP extracts -> outputs/data/crimes_campinas.csv
  02_clean/       one row per bulletin -> outputs/data/bulletins_clean.parquet (+ optional PostGIS load)
  03_test/        pandera validation of the cleaned data
  04_analyse/     run_core.py + core_config.py: the whole analysis -> outputs/core/
database/         optional PostGIS schema (docker compose)
docs/             METHODS.md; data/ = one datasheet per input (Gebru et al. 2021)
inputs/data/      raw inputs, never edited (Git LFS; see inputs/data/README.md)
outputs/          everything the scripts produce (git-ignored)
tests/            pytest suite (synthetic data; DB tests skip without PostGIS)
```

The stage layout follows Alexander (2023), *Telling Stories with Data*, ch. 3.

## Quick start

```bash
uv sync --all-extras          # locked environment in .venv (make env)
make db                       # optional: PostGIS via docker compose (not needed for the analysis)
make acquire                  # raw SSP-SP files -> outputs/data/crimes_campinas.csv
make clean-data               # one row per bulletin + funnel -> outputs/data/
make analyse                  # scripts/04_analyse/run_core.py -> outputs/core/
make test                     # pytest
```

`git lfs pull` fetches the tracked raw inputs. Two IBGE census tables are not
tracked (size) and must be downloaded into `inputs/data/geobr/` from the URLs
in their datasheets: `Agregados_por_setores_basico_BR_20260520.zip` and
`Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip` (SHA-256 in
[`docs/data/`](docs/data/)).

Piecemeal runs:

```bash
.venv/bin/python scripts/04_analyse/run_core.py --quick                 # property, tract only -> outputs/core_quick/
.venv/bin/python scripts/04_analyse/run_core.py --steps where change --groups property --supports tract hex0.5
```

Every parameter is a default in `scripts/04_analyse/core_config.py`; values
marked "project choice" there are this project's decisions. Each run records
provenance (git commit, library versions, configuration, step timings) in
`outputs/core/manifest.json`.

## Data sources and licences

As recorded in the datasheets under [`docs/data/`](docs/data/). No licence is
stated in any of the files; each datasheet marks its licence **"to check"**.

| Data | Producer | Datasheet | Licence |
|---|---|---|---|
| Occurrence bulletins 2022–2025 (`SPDadosCriminais_2025.xlsx`, `crimes_campinas_2022_2024.csv.bak`) | SSP-SP, SPDados | [ssp_raw_inputs.md](docs/data/ssp_raw_inputs.md), [ssp_bulletins_clean.md](docs/data/ssp_bulletins_clean.md) | not stated, to check |
| Legacy assembled bulletin CSV (comparison only) | SSP-SP (assembled by hand) | [ssp_crimes_campinas.md](docs/data/ssp_crimes_campinas.md) | not stated, to check |
| 2022 census tracts | IBGE, via `geobr` (IPEA) | [ibge_census_tracts_2022.md](docs/data/ibge_census_tracts_2022.md) | not stated, to check |
| Agregados por Setores, Básico (population) | IBGE, Censo 2022 | [ibge_agregados_basico_2022.md](docs/data/ibge_agregados_basico_2022.md) | not stated, to check |
| Rendimento do Responsável (income of household heads) | IBGE, Censo 2022 | [ibge_renda_responsavel_2022.md](docs/data/ibge_renda_responsavel_2022.md) | not stated, to check |
| Literacy per tract (`Painel_IBGE_2022.csv`) | values equal IBGE Censo 2022 *Alfabetização*; compiler unverified | [ibge_painel_literacy_2022.md](docs/data/ibge_painel_literacy_2022.md) | not stated, to check |
| CNEFE 2022 address points | IBGE | [ibge_cnefe_2022.md](docs/data/ibge_cnefe_2022.md) | not stated, to check |
| UTB planning units (`map.geojson`) | publisher unverified (Prefeitura de Campinas per the deck) | [campinas_utb.md](docs/data/campinas_utb.md) | not stated, to check |
| Statistical grid 2022 | IBGE | [ibge_statistical_grid.md](docs/data/ibge_statistical_grid.md) | not stated, to check |

The code is released under the MIT licence ([`LICENSE`](LICENSE)); the
licence does not extend to the data.

## How to cite

> *Citation to be added on publication.* (Authors, year, title, venue / DOI.)

## Parked advanced work

Work beyond the classical core is parked, not deleted, in issue
rsushizawa/IC-Crime#22 (tag `archive/pre-reset-2026-10-30` of the IC-Crime
repository): tie-aware permutation inference, a seed-stability study, the
simulation study of Gi* inference on sparse counts (the evidence for the
limitation stated in `docs/METHODS.md`), the prediction / explanation arm, and
a planned partial-Spearman / Clifford–Dutilleul association step.
