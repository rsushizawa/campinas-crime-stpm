# campinas-crime-stpm

Space-time analysis of police-recorded crime in Campinas (São Paulo, Brazil),
2022-2025, following the Esri ArcGIS Pro *Space Time Pattern Mining* and
*Spatial Statistics* toolboxes: a monthly STL decomposition, global and local
spatial autocorrelation, Getis-Ord hot spots, Emerging Hot Spot Analysis and
the association of crime with 2022 census and address-register features, all
on the 2,592 census tracts of the 2022 IBGE mesh.

The data flow is ETL, then a PostGIS warehouse, then the analysis:

```
raw files (inputs/data)
  -> acquire -> clean -> units        ETL stages, one Makefile node each (etl/, scripts/)
  -> load                              PostGIS warehouse: the single source of the analysis data
  -> validate                          pandera checks on the loaded tables
  -> notebooks                         read the warehouse through crime.data.Warehouse
```

The `crime` package is the data access layer. The statistics live in the
Jupyter notebooks ([`notebooks/`](notebooks/README.md)), which call libpysal,
esda, pymannkendall, statsmodels and scipy directly and draw with matplotlib.

## Study area and period

- **Area.** Municipality of Campinas, SP (IBGE code 3509502), 2,592 census
  tracts, 794.8 km² (EPSG:31983, SIRGAS 2000 / UTM zone 23S).
- **Period.** Occurrence dates 2022-01-01 to 2025-12-31.
- **Events.** SSP-SP police bulletins, one row per bulletin: 139,301 offence
  records, 138,330 bulletins, 137,323 in the period, 107,912 with a usable
  coordinate and 107,859 inside a tract (the funnel is stored in the
  warehouse's `build` table). Sexual crimes have no published coordinates and
  appear only in the monthly series.

## Methods

One notebook per step. Parameters, citations and the differences from the
Esri tools are in [`docs/METHODS.md`](docs/METHODS.md).

| Notebook | Method | Library | Citation |
|---|---|---|---|
| `01_data_overview` | funnel, counts by group, year and tract, stacked geocodes | pandas, mapclassify | |
| `02_stl` | STL decomposition of the monthly series; Mann-Kendall and Sen's slope | statsmodels, pymannkendall | Cleveland et al. (1990), *J. Official Statistics* 6(1); Hamed & Rao (1998), *J. Hydrology* 204 |
| `04_global_moran` | Global Moran's I (queen, rook, 5 nearest neighbours) | esda | Moran (1950), *Biometrika* 37(1/2) |
| `05_local_gi_lisa` | Getis-Ord Gi*; local Moran's I; Benjamini-Hochberg FDR | esda, statsmodels | Ord & Getis (1995), *Geographical Analysis* 27(4); Anselin (1995), *Geographical Analysis* 27(2); Benjamini & Hochberg (1995), *JRSS B* 57(1) |
| `06_ehsa` | Emerging Hot Spot Analysis (space-time Gi*, Mann-Kendall, Esri category rules), quarterly and monthly | esda, pymannkendall | Esri, "How Emerging Hot Spot Analysis works"; Mann (1945), *Econometrica* 13 |
| `09_association` | Spearman rank correlation; global and local bivariate Moran's I | scipy, esda | Spearman (1904), *American Journal of Psychology* 15; Wartenberg (1985), *Geographical Analysis* 17(4) |
| `11_paper_figures` | the paper's figures and LaTeX tables, read from the outputs above | matplotlib | |

Spatial weights come from libpysal (Rey & Anselin 2007, *Review of Regional
Studies* 37(1)).

## Data pipeline

Each stage is a pipeline of treatment steps (pipes and filters; Garlan & Shaw
1993). A step has one `run` method that returns the rows that continue, the
rows it rejected and one report line. The 30 rules, with the treatment each
applies (fail, fix, exclude or report), are listed in
[`docs/TREATMENTS.md`](docs/TREATMENTS.md).

| Stage | Make target | Rules | Code | Writes |
|---|---|---|---|---|
| acquire | `make acquire` | 1-8 | `etl/steps/acquire.py` | `outputs/data/crimes_campinas.csv` |
| clean | `make clean` | 9-15 | `etl/steps/clean.py` | `outputs/data/staging/clean/` |
| units | `make units` | 16-22 | `etl/steps/units.py` | `outputs/data/staging/units/` |
| load | `make load` | 23-25 | `etl/load.py` | the PostGIS warehouse, `outputs/reports/profile.md` |
| validate | `make validate` | | `etl/schemas.py` | |

Every stage prints its report as a table and saves it in
`outputs/reports/<stage>.md`. Rejected rows are kept in memory, written to
`outputs/data/staging/<stage>/rejects.parquet`, and loaded into the warehouse's
`reject` table with the rule that removed them. Make reruns a stage only
when its inputs or its code changed.

### The warehouse

A PostGIS star schema ([`database/schema.sql`](database/schema.sql); Kimball &
Ross 2013): `fact_bulletin` (one row per bulletin in the study window),
`dim_date`, `dim_offence`, `dim_census_tract` (polygons and 2022
attributes), `poi`, `reject` and `build`. Every table and column has a
`COMMENT`, so the schema documents itself (`\d+ fact_bulletin` in psql).

The notebooks read it through one class:

```python
from crime.data import CrimeQuery, Warehouse

wh = Warehouse()     # stops with "start it with `make db`, then `make load`" if the database is down
cube = wh.counts(CrimeQuery(crime_group="property", time_unit="quarter"))   # tract x quarter, long, zero-filled
tracts = wh.census_tracts()                                                 # polygons + 2022 attributes
series = wh.counts(CrimeQuery(crime_group="all", unit="city", time_unit="month"))
```

`CrimeQuery` is a pydantic model: crime group, offence slugs, location types,
period, spatial unit (`census_tract` or `city`) and time unit (`total`,
`month`, `quarter`, `year`). An invalid request fails before any database
call.

## Reproducing the results

```bash
uv sync --all-extras          # locked environment in .venv (make env)
cp .env.example .env          # then set POSTGRES_PASSWORD
make db                       # PostgreSQL 17.5 / PostGIS 3.5.2, image pinned by digest, host port 5433
make load                     # acquire, clean, units, load (about 2 minutes)
make validate
make notebooks                # executes every notebook in place; results in outputs/nb/
make test                     # unit tests; database tests skip when PostGIS is down
make parity                   # every number the paper uses against tests/baseline/
```

`git lfs pull` fetches the tracked raw inputs. Two IBGE census tables are not
tracked because of their size: `Agregados_por_setores_basico_BR_20260520.zip`
and `Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip`. Download
them into `inputs/data/geobr/` from the IBGE URLs in their datasheets
([`docs/data/`](docs/data/)). Rule 1 checks every raw file against
[`inputs/data/SHA256SUMS`](inputs/data/SHA256SUMS), so a missing file, or one
that differs from the file the paper used, stops the build.

`tests/baseline/` holds every result the notebooks produced before the
warehouse redesign, with a SHA-256 manifest. `make parity` checks that the
warehouse-backed run reproduces them value for value.

## Releases

Data and code are released separately, with prefixed tags:

| Tag | Contains | New version when |
|---|---|---|
| `data-vX.Y.Z` | database dump, raw-input checksums, reject and report tables | raw inputs or treatment rules change |
| `vX.Y.Z` | package, notebooks with their outputs, result CSVs | code, notebooks or results change |

The warehouse's `build` table records the data version, the schema version,
the commit that built it and the checksum of every raw file. The release notes
of a code version name the data version its results were computed on.

## Repository layout

```
crime/            data access (layers: core <- data)
  core/           config (paths, CRS, study window, versions, DB settings), taxonomy
  data/           query.py = CrimeQuery (pydantic); warehouse.py = Warehouse (SQL reader)
etl/              pipeline.py = Step / Pipeline; steps/ = acquire, clean, units; load.py; schemas.py;
                  profile.py; acquire.py, clean.py, census.py, sources.py = the rule functions and readers
scripts/          one entry point per stage: 01_acquire ... 05_validate
database/         schema.sql (the warehouse), docker-compose.yml
notebooks/        the analysis (see notebooks/README.md); outputs -> outputs/nb/<notebook>/
docs/             METHODS.md, TREATMENTS.md; data/ = one datasheet per input (Gebru et al. 2021)
inputs/data/      raw inputs, never edited (Git LFS), and SHA256SUMS
outputs/          everything the stages and notebooks produce (git-ignored)
tests/            pytest; baseline/ = the paper's results before the redesign
```

The stage layout follows Alexander (2023), *Telling Stories with Data*, ch. 3.
Earlier code (the parquet data API, UTB and grid supports, point patterns,
time-series clustering, Knox, MAUP) is preserved under the tags
`archive/pre-notebooks-2026-10-31` and `archive/pre-warehouse-2026-11-03`.

## Data sources and licences

As recorded in the datasheets under [`docs/data/`](docs/data/). No licence is
stated in any of the files; each datasheet marks its licence "to check".

| Data | Producer | Datasheet |
|---|---|---|
| Occurrence bulletins 2022-2025 (`SPDadosCriminais_2025.xlsx`, `crimes_campinas_2022_2024.csv.bak`) | SSP-SP, SPDados | [ssp_raw_inputs.md](docs/data/ssp_raw_inputs.md), [ssp_bulletins_clean.md](docs/data/ssp_bulletins_clean.md) |
| Legacy assembled bulletin CSV (comparison only) | SSP-SP (assembled by hand) | [ssp_crimes_campinas.md](docs/data/ssp_crimes_campinas.md) |
| 2022 census tracts | IBGE, via `geobr` (IPEA) | [ibge_census_tracts_2022.md](docs/data/ibge_census_tracts_2022.md) |
| Agregados por Setores, Básico (population) | IBGE, Censo 2022 | [ibge_agregados_basico_2022.md](docs/data/ibge_agregados_basico_2022.md) |
| Rendimento do Responsável (income of household heads) | IBGE, Censo 2022 | [ibge_renda_responsavel_2022.md](docs/data/ibge_renda_responsavel_2022.md) |
| Literacy per tract (`Painel_IBGE_2022.csv`) | values equal IBGE Censo 2022 *Alfabetização*; compiler unverified | [ibge_painel_literacy_2022.md](docs/data/ibge_painel_literacy_2022.md) |
| CNEFE 2022 address points | IBGE | [ibge_cnefe_2022.md](docs/data/ibge_cnefe_2022.md) |

The code is released under the MIT licence ([`LICENSE`](LICENSE)); the
licence does not extend to the data.

## How to cite

*Citation to be added on publication.*
