# Notebooks

All analysis lives here. Each notebook loads its data from `crime.data` and
then calls the statistics libraries **directly** — libpysal, esda, pointpats,
pymannkendall, statsmodels, scipy, scikit-learn, tobler — and draws
with plain matplotlib / geopandas (mapclassify for class breaks). There is no
project statistics package: if a notebook needs a method, it calls the library
function and cites it in a markdown cell.

## Maps

`notebooks/_mapstyle.py` (≈ 150 lines of matplotlib / geopandas / contextily,
imported as `ms`) holds the map furniture every map shares: Esri World Light
Gray Canvas basemap tiles (`contextily`; the map is drawn without tiles when
offline), the UTB boundaries as thin dark lines over tract maps, a lat / lon
graticule, an alternating scale bar and a north arrow (`ms.decorate`), and
categorical layers that encode a class by colour **and** hatch pattern with a
grouped legend (`ms.plot_categories`, `ms.category_legend`). Conventions:
Gi* hot / cold = reds / blues, confidence 99 / 95 / 90 % = solid / `//` / `..`;
LISA HH / LL solid, outliers HL / LH hatched; EHSA hot / cold = reds / blues,
pattern type by hatch, *no pattern* light grey and drawn for every unit.
The look follows the earlier `crime.viz` maps (branch `archive/pre-notebooks`).

## Data API

`crime.data` is the only project package a notebook imports (full contract:
the docstring of `crime/data/api.py`). Every frame is in **EPSG:31983**
(SIRGAS 2000 / UTM 23S, metres). No database is needed; the inputs are
`outputs/data/bulletins_clean.parquet` (`make clean-data`) and the tracked
files in `inputs/data/`.

```python
from crime.data import GROUPS, load_points, load_units, unit_counts, cnefe_poi_points, unit_poi_counts

load_points(group="all")                      # GeoDataFrame, one row per bulletin
load_units(support)                           # support: "tract" | "utb"
unit_counts(support, group="all", freq=None)  # freq: None | "M" | "Q" | "Y"
cnefe_poi_points()                            # CNEFE 2022 POI addresses, column `poi`
unit_poi_counts(support)                      # unit_id x n_commercial / n_education / n_health / n_religious
GROUPS                                        # ("all", "property", "bodily_harm", "traffic", "drug", "violent")
```

| Call | Returns | Current size |
|---|---|---|
| `load_points()` | `event_id`, `date`, `datetime` (NaT where the hour is missing), `year`, `month`, `quarter` (period-start Timestamps), `period_of_day`, `crime_slug`, `group`, `cd_setor`, `utb`, `geometry` | 107,859 rows (property 90,436; bodily_harm 6,590; traffic 6,302; drug 4,032; violent 499) |
| `load_units("tract")` | `unit_id` (= `cd_setor`), `area_km2`, `population`, `income_head_mean`, `income_head_median`, `literacy_rate`, `geometry` | 2,592 tracts (income / literacy NaN on 90) |
| `load_units("utb")` | `unit_id` (= `denominacao`), `area_km2`, `utb_sigla`, `geometry` | 93 UTBs |
| `unit_counts(s, g)` | Series `unit_id -> count`, every unit, zero-filled | sums to the `load_points(g)` total on both supports |
| `unit_counts(s, g, "M")` | DataFrame unit x period, columns = period-start Timestamps 2022-01 .. 2025-12, zero-filled | 48 months (`"Q"`: 16, `"Y"`: 4) |

The event set is the same for every support: geocoded bulletins inside a 2022
census tract with an occurrence date in 2022-01-01 .. 2025-12-31. The groups
are disjoint, so `"all"` is their union; `sexual` has no coordinates and is not
a spatial group (for its time series read the parquet directly). The 22
in-tract bulletins that fall in slivers between UTB polygons (all within 84 m
of one) are assigned to the nearest UTB. `load_units("tract")` caches the
census attributes in `outputs/data/tract_attributes.parquet`; building it the
first time needs the two IBGE zips in `inputs/data/geobr/` (see the main
README).

Row order of `load_units(s)` and the index of `unit_counts(s, ...)` are the
same, so `libpysal.weights.Queen.from_dataframe(load_units(s), ids="unit_id",
use_index=False)` lines up with `unit_counts(s, g).to_numpy()` (checked on both
supports); still `reindex` on `unit_id` when in doubt.

## Outputs

A notebook writes its tables and figures to `outputs/nb/<notebook-stem>/`
(git-ignored, like all of `outputs/`):

```python
from crime.core.config import NOTEBOOK_OUTPUTS_DIR
OUT = NOTEBOOK_OUTPUTS_DIR / "04_global_moran"
OUT.mkdir(parents=True, exist_ok=True)
```

Numbers quoted in `README.md` and `docs/METHODS.md` must be the ones the
notebooks print; rerun the notebooks before quoting them.

## Run order

Each notebook reads only `crime.data`. Run them in this order:

| Notebook | Content |
|---|---|
| `01_data_overview` | funnel, counts per group / support, unit areas, stacked geocodes |
| `02_stl` | monthly series per group, STL decomposition (statsmodels) |
| `03_point_patterns` | Ripley's K / L, nearest-neighbour index, KDE (pointpats, scipy) |
| `04_global_moran` | global Moran's I on tracts and UTBs (libpysal, esda) |
| `05_local_gi_lisa` | Getis–Ord Gi* and local Moran (esda), BH FDR (statsmodels) |
| `06_ehsa` | Emerging Hot Spot Analysis built from esda Gi* per bin + pymannkendall + Esri's category rules |
| `07_time_series_clustering` | k-means on unit series, k by Calinski–Harabasz (scikit-learn) |
| `08_knox` | Knox space–time interaction test (`pointpats.spacetime.Knox`) |
| `09_association` | Spearman (scipy) and bivariate Moran (esda) with census and CNEFE features |
| `10_maup` | tract vs UTB vs points; areal interpolation (tobler) |

## Running headless

```bash
make notebooks
# = uv run jupyter nbconvert --to notebook --execute --inplace \
#       --ExecutePreprocessor.timeout=-1 --ExecutePreprocessor.kernel_name=python3 notebooks/*.ipynb
```

The glob runs them in file-name order, which is the run order above. One
notebook: `uv run jupyter nbconvert --to notebook --execute --inplace
notebooks/04_global_moran.ipynb`. Interactive: `uv run jupyter lab`. Use the
`python3` kernel of the project venv (`.venv/share/jupyter/kernels/python3`),
not a user-level kernel from another project.

## Library notes found while setting up (Python 3.14)

- **esda zero ties.** esda's permutation p counts ties with the observed
  statistic in one tail only, so units whose own value and neighbourhood are
  all zero can come out as significant LL / cold spots. Report and, where it
  matters, exclude them (see `docs/METHODS.md`, known limitations).
