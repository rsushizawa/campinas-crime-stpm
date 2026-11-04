# Methods

One section per method, in notebook order (`notebooks/README.md`). Each
notebook calls the library named here directly; the parameters are set in the
notebook's first code cell, and a value called **project choice** is a
decision of this project, not prescribed by the cited method or by the Esri
tool. "Esri" refers to the ArcGIS Pro *Spatial Statistics* and *Space Time
Pattern Mining* toolboxes, cited by the title of their "How … works"
documentation pages. Nothing here claims numerical parity with an Esri tool.

**Numbers.** Result numbers are produced by the notebooks
(`outputs/nb/<notebook>/`) and are not restated in this file until the
notebooks have been run on the current data; the data counts below are those
of the warehouse release data-v1.0.0.

Common settings: study period 2022-01-01 … 2025-12-31 by occurrence date;
α = 0.05; Benjamini–Hochberg (BH) false-discovery-rate correction on every
family of local tests (Benjamini & Hochberg 1995;
`statsmodels.stats.multitest.multipletests(method="fdr_bh")`); a fixed seed
for every random draw.

## 0. Data, units of analysis and neighbourhoods

**Events.** One row per police bulletin (SSP-SP *boletim de ocorrência*),
offence = the one with the highest maximum penalty on the bulletin
(rule 9 of `docs/TREATMENTS.md`, `etl/clean.py`). Funnel (stored in the
warehouse's `build` table): 139,301 offence records → 138,330 bulletins →
137,323 with occurrence date in the window → 107,912 with a usable coordinate →
107,859 inside a 2022 census tract. Crime groups follow
`crime/core/taxonomy.py:CRIME_GROUPS` (`crime.data.SPATIAL_GROUPS`); `all` is
every group with points. Sexual crimes have no published coordinates and enter the
temporal step only.

**Spatial unit.** The 2,592 IBGE 2022 census tracts (`Warehouse.census_tracts()`).
A bulletin's tract is the polygon that contains its published point
(point-in-polygon, first match on a shared edge; rules 16 and 17), and the
counts per tract and time bin come from `Warehouse.counts`.

**Spatial weights** (libpysal; Rey & Anselin 2007). Queen contiguity is the
headline neighbourhood (project choice); rook contiguity and k-nearest
neighbours between unit centroids are sensitivity runs, with k a project
choice that the notebook states and justifies (the previous pipeline used the
median queen neighbour count of tracts). Row-standardised unless a notebook
says otherwise. Islands (tracts without a neighbour) must be reported and left
out of the BH family; no tract is an island under queen, rook or 5 nearest
neighbours.

## 1. When: monthly series and STL decomposition (`02_stl`)

- **Tests / describes.** Level, trend and seasonality of the recorded count,
  per group. Descriptive, no inference.
- **Inputs.** Monthly counts of *all* bulletins of the group in the window,
  geocoded or not (48 months); the in-tract count is written alongside.
- **Library.** `statsmodels.tsa.seasonal.STL` with period 12 and robust loess
  fits; statsmodels default windows. The all-bulletin monthly series comes
  from `Warehouse.counts(CrimeQuery(unit="city", time_unit="month"))`; the
  in-tract series from the same call with `unit="census_tract"`, summed over
  tracts.
- **Citation.** Cleveland, R.B., Cleveland, W.S., McRae, J.E. & Terpenning, I.
  (1990). STL: A seasonal-trend decomposition procedure based on loess.
  *Journal of Official Statistics* 6(1).
- **Esri.** No direct counterpart (the cube tools show time series but do not
  decompose them).
- **Notebook.** `02_stl` (descriptive counts per group and tract:
  `01_data_overview`).

## 2. Where (static): global Moran's I, Getis–Ord Gi*, local Moran's I (`04_global_moran`, `05_local_gi_lisa`)

### 2a. Global Moran's I

- **Tests.** H0: no spatial autocorrelation of the per-unit count over the
  whole study period.
- **Inputs.** Per-unit count 2022–2025; weights as above.
- **Library / inference.** `esda.Moran`: I, E[I]; permutation pseudo p
  (999 permutations, project choice) and the analytic normality z and p
  (`z_norm`, `p_norm`). Both are reported.
- **Citation.** Moran, P.A.P. (1950). Notes on continuous stochastic
  phenomena. *Biometrika* 37(1/2).
- **Esri.** "How Spatial Autocorrelation (Global Moran's I) works": Esri
  reports the analytic z; this code reports both. The Esri default
  neighbourhood is inverse distance, not contiguity.

### 2b. Getis–Ord Gi* hot and cold spots

- **Tests.** H0 per unit: the weighted sum of the count in the unit and its
  neighbours equals its expectation under spatial randomness.
- **Inputs.** Per-unit count; weights with a self-weight added by esda
  (`G_Local(star=True)`: the self-weight equals the row maximum, then the row
  is re-standardised, so with contiguity weights the unit and each neighbour
  get equal weight).
- **Library / inference.** `esda.G_Local(star=True)`. Analytic z, **two-sided**
  normal p `2·Φ(−|z|)`, BH across units, α = 0.05; or esda's permutation p —
  the notebook states which. `05_local_gi_lisa` maps and counts every unit
  before FDR (unadjusted p) and after BH-FDR (q) side by side, with Esri's
  Gi_Bin confidence classes 99 / 95 / 90 % (p or q ≤ 0.01 / 0.05 / 0.10);
  LISA the same at 0.05. Two esda 2.6 details found in the previous code
  (`archive/pre-notebooks:crime/esri/local.py`, `gi_star_z`): (i) `Zs` uses
  the Getis & Ord (1992) variance, exact only for binary weights; with
  row-standardised weights it shrinks z (about 0.3–0.5× on queen tracts), so
  use binary weights (`transform="B"`) for the analytic z or compute the
  Ord & Getis (1995) general-weights variance explicitly; (ii) `p_norm` is
  one-sided (`norm.sf(|z|)`), half the two-sided p used by ArcGIS Pro.
- **Citation.** Getis, A. & Ord, J.K. (1992). The analysis of spatial
  association by use of distance statistics. *Geographical Analysis* 24(3).
  Ord, J.K. & Getis, A. (1995). Local spatial autocorrelation statistics:
  distributional issues and an application. *Geographical Analysis* 27(4).
- **Esri.** "How Hot Spot Analysis (Getis-Ord Gi*) works": analytic z and
  two-sided p as here. Esri offers an optional FDR correction; we do not
  claim it is numerically identical to the BH correction applied here to all
  units of one run. Esri's default conceptualisation is fixed
  distance band, not contiguity.

### 2c. Local Moran's I (LISA)

- **Tests.** H0 per unit: no association between the unit's value and the
  mean of its neighbours. Labels HH / LL (clusters), HL / LH (outliers), `ns`.
- **Library / inference.** `esda.Moran_Local`: conditional permutation, 499
  permutations (Esri default), esda's folded pseudo p, BH across units.
- **Citation.** Anselin, L. (1995). Local indicators of spatial association —
  LISA. *Geographical Analysis* 27(2).
- **Esri.** "How Cluster and Outlier Analysis (Anselin Local Moran's I)
  works": same 499-permutation default; BH here, with no claim of identity to
  Esri's optional FDR correction.

## 3. How it changes: Emerging Hot Spot Analysis (`06_ehsa`)

### 3a. Space-time cube

Events counted per unit and time bin, every unit and every bin of the window
present, empty cells 0: `Warehouse.counts(CrimeQuery(crime_group=g,
time_unit="quarter"))` (16 bins; project choice for the primary run) or
`time_unit="month"` (48 bins), pivoted to a tract x bin matrix.

### 3b. Emerging Hot Spot Analysis (EHSA)

- **Tests.** For each unit: is it a significant Gi* hot (cold) spot in each
  bin, and does its Gi* z series trend over time? The pattern of significant
  bins plus the trend give one of 17 categories (new, consecutive,
  intensifying, persistent, diminishing, sporadic, oscillating, historical ×
  hot / cold, or no pattern), by Esri's category table with the 90 % rule.
- **Implementation (`06_ehsa`).** Gi* per bin (`esda.G_Local`) with a
  space-time neighbourhood the notebook builds and documents, Mann–Kendall
  on each unit's z series (`pymannkendall.original_test`; the Hamed–Rao
  correction `hamed_rao_modification_test` as a sensitivity), Esri's
  category rules written out in the notebook. Labels are reported before
  FDR (bin p < 0.05) and after Benjamini–Hochberg FDR over all n·T bins of a
  run (bin q < 0.05; the Mann–Kendall trend p is not adjusted), side by side
  in maps and in a counts table.
- **Space-time neighbourhood.** Esri ("How Emerging Hot Spot Analysis works",
  "How Create Space Time Cube works") defines the neighbourhood — the bins
  within the neighbourhood distance and the time step — but, as far as we
  found, does not document how neighbour-bins are weighted relative to each
  other. The binary weighting used here is therefore a project convention;
  the notebook states it and does not claim to reproduce Esri's numbers.
- **Citations.** Esri, "How Emerging Hot Spot Analysis works" (category
  rules). Getis & Ord (1992); Ord & Getis (1995). Mann, H.B. (1945).
  Nonparametric tests against trend. *Econometrica* 13. Kendall, M.G. (1975).
  *Rank Correlation Methods*. Griffin. Hamed, K.H. & Rao, A.R. (1998). A
  modified Mann-Kendall trend test for autocorrelated data. *Journal of
  Hydrology* 204. Benjamini, Y. & Hochberg, Y. (1995). Controlling the false
  discovery rate. *JRSS B* 57(1).

## 4. Association with urban features (`09_association`)

- **Inputs.** Crime count per tract for 2022–2025 and for 2022 alone (the
  census year; project choice to report both). Features
  (`Warehouse.census_tracts()`): CNEFE 2022 address counts by use type
  (education, health, "other purposes" as the commerce proxy, religious;
  deduplicated on address × use type, assigned by point-in-polygon), resident
  population, mean nominal monthly income of household heads
  (`income_head_mean`, IBGE `V06004`) and the literacy rate of residents aged
  15+.
- **Two scales.** Every pair is computed on **raw counts** per unit and on
  **densities** (`scale = per_km2`: crime per km² vs the feature per km², for
  the address counts and population; income and literacy are already
  intensive and appear on the count scale only). Raw counts across units of
  unequal area and population partly reflect unit size — a large tract has
  more addresses, more residents and more bulletins for that reason alone —
  so a positive ρ or bivariate I on counts is in part a size effect. Densities
  remove the area component but not the population one (crime per km² still
  rises with residents per km²); neither scale is a rate per exposed person,
  and neither adjusts for confounding.
- **Spearman's ρ** (`scipy.stats.spearmanr`) with its p-value (no spatial adjustment). Spearman, C.
  (1904). The proof and measurement of association between two things.
  *American Journal of Psychology* 15.
- **Global bivariate Moran's I** (`esda.Moran_BV`; local: `esda.Moran_Local_BV`), both orders (feature vs spatial lag of crime;
  crime vs spatial lag of the feature), queen weights, 999 permutations of the
  lagged variable. Wartenberg, D. (1985). Multivariate spatial correlation: a
  method for exploratory geographical analysis. *Geographical Analysis* 17(4).
  Anselin, L., Syabri, I. & Smirnov, O. (2002). Visualizing multivariate
  spatial correlation with dynamically linked windows. In *New Tools for
  Spatial Data Analysis*, CSISS. The statistic mixes the in-place correlation
  with the autocorrelation of the lagged variable; it is not a test of
  association beyond the plain correlation.
- **Local bivariate Moran** of crime vs the spatial lag of the commerce count,
  tracts, 2022–2025, 499 permutations, BH.
- **Esri.** "Bivariate Spatial Association (Lee's L)" is Esri's bivariate
  tool; it is not used here.
- **No multiple-testing adjustment** across the feature × group table.

## Known limitations

- **Analytic Gi* on skewed, sparse counts; no cold spots.** The normal
  approximation behind the analytic Gi* p-value is poor for skewed counts
  with many zeros: it over-calls hot spots and rarely calls cold spots
  (simulation evidence in the parked issue rsushizawa/IC-Crime#22). The
  previous pipeline found no Gi* or EHSA cold spot on tracts; expect
  the same, and do not read the absence of cold spots as an absence of
  low-crime areas. This affects static Gi* and every EHSA category.
- **Permutation resolution vs BH (LISA, local bivariate
  Moran).** With 499 permutations the smallest attainable pseudo p is
  1/500 = 0.002. BH at 0.05 over n units rejects nothing unless at least
  0.002 · n / 0.05 = n / 25 units sit at that floor (104 of 2,592 tracts).
  Static LISA can therefore report no significant tract even
  where many raw p are < 0.05 (this happened in the previous pipeline on
  tracts). More permutations raise the resolution (9,999 give a floor of
  0.0001); the notebook states the number it uses.
- **esda tie handling.** esda 2.6.0 counts ties with the observed statistic
  only in the upper tail of the permutation distribution, so units whose
  value and neighbourhood are all zero can be labelled significant LL /
  cold (parked issue rsushizawa/IC-Crime#22). This affects LISA LL counts
  and permutation-based Gi* / EHSA cold labels for sparse groups (violent,
  drug, bodily harm on tracts). Notebooks report how many LL / cold units
  are all-zero neighbourhoods; such labels should not be read as low-crime
  clusters.
- **Stacked geocodes.** ~63 % of geocoded bulletins share an exact coordinate
  with another bulletin (street-level geocoding). Counts per unit are
  concentrated on those points.
- **Recorded, not total, crime.** Counts are bulletins registered with the
  police, not incidents; reporting propensity varies by offence and place.
- **Geocoding share differs by group.** Share of in-window bulletins with a
  tract (2022–2025): property 83 %, traffic 96 %, drug 86 %, violent 71 %,
  bodily harm 43 %, sexual 0 % (no published locations). Spatial results for
  bodily harm are based on fewer than half of its bulletins.
- **Reporting lag at the end of 2025.** Time is the occurrence date. Offences
  that occurred in late 2025 but were registered after the extract are
  missing, which can depress the last bins and the end of the STL trend.
- **2022 census covariates** are compared with 2022–2025 crime; the 2022-only
  rows are for the census-year comparison. 90 tracts have no income or
  literacy value (suppressed or uninhabited) and are dropped from those
  pairs.
