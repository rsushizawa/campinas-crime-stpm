# Notebooks

All analysis lives here. Each notebook gets its data from the PostGIS
warehouse through `crime.data.Warehouse`, then calls the statistics libraries
directly (libpysal, esda, pymannkendall, statsmodels, scipy) and draws with
matplotlib and geopandas (mapclassify for class breaks). If a notebook needs a
method, it calls the library function and cites it in a markdown cell.

The warehouse must be running and loaded (`make db load`). Without it the
first data cell stops with the command to run.

## Maps

`notebooks/_mapstyle.py` (about 150 lines of matplotlib, geopandas and
contextily, imported as `ms`) holds the map furniture every map shares: Esri
World Light Gray Canvas basemap tiles (`contextily`; the map is drawn without
tiles when offline), a lat / lon graticule, an alternating scale bar and a
north arrow (`ms.decorate`), and categorical layers that encode a class by
colour and hatch pattern with a grouped legend (`ms.plot_categories`,
`ms.category_legend`). Conventions: Gi* hot / cold = reds / blues, confidence
99 / 95 / 90 % = solid / `//` / `..`; LISA HH / LL solid, outliers HL / LH
hatched; EHSA hot / cold = reds / blues, pattern type by hatch, *no pattern*
light grey and drawn for every tract.

## Data access

```python
from crime.data import SPATIAL_GROUPS, TEMPORAL_GROUPS, CrimeQuery, Warehouse

wh = Warehouse()
wh.counts(CrimeQuery(crime_group="property"))                         # one row per tract, 2022-2025
wh.counts(CrimeQuery(crime_group="property", time_unit="quarter"))    # one row per tract and quarter
wh.counts(CrimeQuery(crime_group="sexual", unit="city", time_unit="month"))   # city series, any bulletin
wh.census_tracts()                                                    # polygons + 2022 attributes
wh.bulletins(CrimeQuery(crime_group="drug"))                          # one row per bulletin (points)
wh.build()                                                            # release, commit, funnel, reports
```

| Call | Returns |
|---|---|
| `counts(q)`, `unit="census_tract"` | long GeoDataFrame: `census_tract_id`, `period_start`, `count`, the tract attributes, `geometry`; every tract and bin, zero-filled, ordered by tract id then bin |
| `counts(q)`, `unit="city"` | one row per bin: `period_start`, `count`, counting every bulletin in the window, geocoded or not |
| `census_tracts()` | 2,592 tracts: `census_tract_id`, `area_km2`, `population`, `households`, `income_head_mean`, `income_head_median`, `literacy_rate`, POI counts (`n_commercial`, `n_education`, `n_health`, `n_religious`), `geometry` |
| `bulletins(q)` | `bulletin_id`, dates, `crime_slug`, `crime_group`, `coord_status`, `latitude`, `longitude`, `census_tract_id`, `geometry` |

The spatial event set is the bulletins geocoded inside a 2022 census tract
with an occurrence date in 2022-01-01 to 2025-12-31 (107,859). The groups are
disjoint, so `"all"` is their union. `sexual` has no coordinates and only
appears with `unit="city"`.

Most notebooks need a tract x bin matrix; they pivot the long table:

```python
Y = wh.counts(CrimeQuery(crime_group=g, time_unit="quarter")).pivot(
    index="census_tract_id", columns="period_start", values="count")
```

The rows of `counts` and of `census_tracts()` are in the same tract-id order,
so `libpysal.weights.Queen.from_dataframe(tracts, ids=...)` lines up with the
counts. Inside the notebooks the tract id column is renamed `unit_id`, the name
the result tables have always used.

## Outputs

A notebook writes its tables and figures to `outputs/nb/<notebook-stem>/`
(git-ignored, like all of `outputs/`):

```python
from crime.core.config import NOTEBOOK_OUTPUTS_DIR
OUT = NOTEBOOK_OUTPUTS_DIR / "04_global_moran"
OUT.mkdir(parents=True, exist_ok=True)
```

Numbers quoted in `README.md` and `docs/METHODS.md` must be the ones the
notebooks print; rerun the notebooks before quoting them. `make parity`
compares every result table with `tests/baseline/`.

## Run order

| Notebook | Content |
|---|---|
| `01_data_overview` | funnel, counts per group, year and tract, tract areas, stacked geocodes |
| `02_stl` | monthly series per group, STL decomposition (statsmodels), Mann-Kendall (pymannkendall) |
| `04_global_moran` | global Moran's I on tracts (libpysal, esda) |
| `05_local_gi_lisa` | Getis-Ord Gi* and local Moran (esda), BH FDR (statsmodels) |
| `06_ehsa` | Emerging Hot Spot Analysis from esda Gi* per bin, pymannkendall and Esri's category rules |
| `09_association` | Spearman (scipy) and bivariate Moran (esda) with census and CNEFE features |
| `11_paper_figures` | the paper's figures and LaTeX tables, from the outputs of the notebooks above |

The numbers 03, 07, 08 and 10 belonged to notebooks outside the paper's
methods (point patterns, time-series clustering, Knox, MAUP); they are kept
under the tag `archive/pre-warehouse-2026-11-03`.

## Running headless

```bash
make notebooks
# = uv run jupyter nbconvert --to notebook --execute --inplace \
#       --ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=python3 notebooks/*.ipynb
```

The glob runs them in file-name order, which is the run order above. One
notebook: `make notebooks NB=notebooks/04_global_moran.ipynb`. Interactive:
`uv run jupyter lab`. Use the `python3` kernel of the project venv
(`.venv/share/jupyter/kernels/python3`), not a user-level kernel from another
project.

## Library notes (Python 3.14)

- **esda zero ties.** esda's permutation p counts ties with the observed
  statistic in one tail only, so tracts whose own value and neighbourhood are
  all zero can come out as significant LL or cold spots. Report them and, where
  it matters, exclude them (`docs/METHODS.md`, known limitations).
