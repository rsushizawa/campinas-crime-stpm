# campinas-crime-stpm

Space-time analysis of police-recorded crime in Campinas (São Paulo, Brazil),
2022–2025, in the spirit of the Esri ArcGIS Pro *Space Time Pattern Mining*
and *Spatial Statistics* toolboxes: global and local spatial autocorrelation,
Getis–Ord hot spots, Emerging Hot Spot Analysis, Time Series Clustering, point-pattern statistics, a Knox
space–time interaction test, rank / bivariate spatial association with 2022
census and address-register features, and the same analysis on three spatial
supports (points, census tracts, UTB planning units).

The analysis lives in **Jupyter notebooks** ([`notebooks/`](notebooks/README.md))
that call the published libraries directly — libpysal, esda, pointpats,
pymannkendall, statsmodels, scipy, scikit-learn, tobler — and draw
with matplotlib / geopandas / contextily (shared map furniture in
`notebooks/_mapstyle.py`). The `crime` package is only the data layer:
acquisition, cleaning, validation and a small loading API. No database is
required for the analysis.

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
- **Spatial supports.** The 107,859 points; 2,592 IBGE 2022 census tracts;
  93 UTB planning units. Every support counts the same event set.

## Methods

One notebook per step; parameters, citations and the differences from the
Esri tools are in [`docs/METHODS.md`](docs/METHODS.md). Numbers are produced
by running the notebooks and are not restated here.

| Notebook | Method | Library | Citation |
|---|---|---|---|
| `02_stl` | STL decomposition of the monthly series | statsmodels | Cleveland et al. (1990), *J. Official Statistics* 6(1) |
| `03_point_patterns` | Ripley's K / Besag's L, CSR envelope; nearest-neighbour index; KDE | pointpats, scipy | Ripley (1976), *J. Applied Probability* 13(2); Besag & Diggle (1977), *Applied Statistics* 26(3); Clark & Evans (1954), *Ecology* 35(4); Silverman (1986) |
| `04_global_moran` | Global Moran's I | esda | Moran (1950), *Biometrika* 37(1/2) |
| `05_local_gi_lisa` | Getis–Ord Gi*; local Moran's I (LISA); Benjamini–Hochberg FDR | esda, statsmodels | Ord & Getis (1995), *Geographical Analysis* 27(4); Anselin (1995), *Geographical Analysis* 27(2); Benjamini & Hochberg (1995), *JRSS B* 57(1) |
| `06_ehsa` | Emerging Hot Spot Analysis (space-time Gi* + Mann–Kendall, Esri category rules) | esda, pymannkendall | Esri, "How Emerging Hot Spot Analysis works"; Mann (1945), *Econometrica* 13 |
| `07_time_series_clustering` | k-means on unit series, k by pseudo-F | scikit-learn | Caliński & Harabasz (1974), *Communications in Statistics* 3(1) |
| `08_knox` | Knox space–time interaction test (Monte Carlo) | pointpats | Knox (1964), *Applied Statistics* 13(1) |
| `09_association` | Spearman rank correlation; global / local bivariate Moran's I | scipy, esda | Spearman (1904), *American Journal of Psychology* 15; Wartenberg (1985), *Geographical Analysis* 17(4) |
| `10_maup` | Support sensitivity (points / tract / UTB); areal interpolation | tobler | Openshaw (1984), CATMOG 38; Goodchild & Lam (1980), *Geo-Processing* 1 |

Spatial weights use libpysal (Rey & Anselin 2007, *Review of Regional
Studies* 37(1)). Known limitations are listed at the end of
[`docs/METHODS.md`](docs/METHODS.md#known-limitations).

## Repository layout

```
crime/            the data layer (layers: core <- data)
  core/           configuration (paths, CRS, database), the warehouse Dataset container
  data/           api.py = the notebook API (load_points / load_units / unit_counts / CNEFE POIs);
                  units.py = tract / UTB polygons and point assignment; cleaning.py = raw-file
                  cleaning and tract attributes; catalog, provenance; PostGIS readers (optional)
etl/              acquire / clean rules for the SSP-SP files, taxonomy, IBGE readers, PostGIS writers
scripts/
  01_acquire/     raw SSP-SP extracts -> outputs/data/crimes_campinas.csv
  02_clean/       one row per bulletin -> outputs/data/bulletins_clean.parquet (+ optional PostGIS load)
  03_test/        pandera validation of the cleaned data
notebooks/        the analysis (see notebooks/README.md); outputs -> outputs/nb/<notebook>/
database/         optional PostGIS warehouse: schema.sql, enrich.sql (feature views), docker compose
docs/             METHODS.md; data/ = one datasheet per input (Gebru et al. 2021)
inputs/data/      raw inputs, never edited (Git LFS; see inputs/data/README.md)
outputs/          everything the scripts and notebooks produce (git-ignored)
tests/            pytest suite (synthetic data; DB tests skip without PostGIS)
```

The stage layout follows Alexander (2023), *Telling Stories with Data*, ch. 3.
The previous Python statistics package (`crime.esri` / `points` / `stats` /
`viz`, `run_core.py`) is preserved on the `archive/pre-notebooks` branch.

## Quick start

```bash
uv sync --all-extras          # locked environment in .venv (Python 3.14), every extra (make env)
cp .env.example .env          # optional, for PostGIS: set POSTGRES_PASSWORD
make db                       # optional: PostGIS via docker compose (not needed for the analysis)
make acquire                  # raw SSP-SP files -> outputs/data/crimes_campinas.csv
make clean-data               # one row per bulletin + funnel -> outputs/data/
make notebooks                # execute notebooks/*.ipynb in place -> outputs/nb/
make test                     # pytest
```

```python
from crime.data import load_points, load_units, unit_counts
pts = load_points("property")                 # 90,436 points, EPSG:31983
y = unit_counts("tract", "property")          # 2,592 tracts, zero-filled
```

Extras (`pyproject.toml`): the notebooks need none of them. `etl` = acquire /
clean / validate stages; `db` = SQLAlchemy + psycopg2 for the PostGIS
warehouse (`make clean`, `make validate`, `crime.load_sectors` …); `dev` =
pytest + ruff. E.g. `uv sync --extra etl --extra dev` for a database-free
setup.

`git lfs pull` fetches the tracked raw inputs. Two IBGE census tables are not
tracked (size) and must be downloaded into `inputs/data/geobr/` from the URLs
in their datasheets: `Agregados_por_setores_basico_BR_20260520.zip` and
`Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip` (SHA-256 in
[`docs/data/`](docs/data/)). They are needed once, to build the tract
attribute cache `outputs/data/tract_attributes.parquet`.

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
| UTB planning units (`map.geojson`) | publisher unverified | [campinas_utb.md](docs/data/campinas_utb.md) | not stated, to check |
| Statistical grid 2022 (PostGIS warehouse only) | IBGE | [ibge_statistical_grid.md](docs/data/ibge_statistical_grid.md) | not stated, to check |

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
