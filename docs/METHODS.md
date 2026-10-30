# Methods

One section per method, in the order `scripts/04_analyse/run_core.py` runs
them. Every parameter value is set in `scripts/04_analyse/core_config.py`;
values called **project choice** there and here are decisions of this
project, not prescribed by the cited method or by the Esri tool. "Esri" refers
to the ArcGIS Pro *Spatial Statistics* and *Space Time Pattern Mining*
toolboxes, cited by the title of their "How … works" documentation pages. The
code does **not** claim numerical parity with any Esri tool; differences known
to us are listed per method.

Common settings: study period 2022-01-01 … 2025-12-31 by occurrence date;
α = 0.05; Benjamini–Hochberg (BH) false-discovery-rate correction on every
family of local tests (Benjamini & Hochberg 1995); seed 42 for every random
draw.

## 0. Data, units of analysis and neighbourhoods

**Events.** One row per police bulletin (SSP-SP *boletim de ocorrência*),
offence = the one with the highest maximum penalty on the bulletin
(`scripts/02_clean/clean_bulletins.py`, `etl/clean.py`). Funnel
(`outputs/data/funnel.json`): 139,301 offence records → 138,330 bulletins →
137,323 with occurrence date in the window → 107,912 with a usable coordinate →
107,859 inside a 2022 census tract. Crime groups follow
`etl/taxonomy.py:CRIME_GROUPS`; `all` is every group. Sexual crimes have no
published coordinates and enter the temporal step only.

**Supports** (`crime.data.units.load_units`). 2,592 IBGE 2022 census tracts;
93 UTB planning units; regular flat-topped hexagons of 0.5 km² and 0.1 km² and
squares of 0.5 km² laid over the municipality and clipped to it (Esri
"Generate Tessellation" analogue; grid origin and orientation are project
choices). Points are assigned to units by point-in-polygon
(`assign_points`; a point on a shared edge goes to the first unit in row
order).

**Spatial weights** (`crime.esri.weights.spatial_weights`, libpysal; Rey &
Anselin 2007). Queen contiguity, rook contiguity and k-nearest neighbours
between unit centroids with k = 5 (project choice: the median queen neighbour
count of tracts, computed and logged in `outputs/core/weights_info.json`). All
weights are row-standardised. Queen is the headline neighbourhood (project
choice); rook and knn are sensitivity runs.

## 1. When: monthly series and STL decomposition

- **Tests / describes.** Level, trend and seasonality of the recorded count,
  per group. Descriptive, no inference.
- **Inputs.** Monthly counts of *all* bulletins of the group in the window,
  geocoded or not (48 months); the in-tract count is written alongside.
- **Parameters.** STL with period 12 and robust loess fits; statsmodels
  default windows (`crime.stats.eda.stl_decompose`).
- **Citation.** Cleveland, R.B., Cleveland, W.S., McRae, J.E. & Terpenning, I.
  (1990). STL: A seasonal-trend decomposition procedure based on loess.
  *Journal of Official Statistics* 6(1).
- **Esri.** No direct counterpart (the cube tools show time series but do not
  decompose them).
- **Outputs.** `stl_<group>.csv`, `stl_summary.csv`, `monthly_series.csv`,
  and `descriptive.csv` (per group × support: units, events, mean, variance /
  mean, share of zero units, unit areas).

## 2. Where (static): global Moran's I, Getis–Ord Gi*, local Moran's I

### 2a. Global Moran's I

- **Tests.** H0: no spatial autocorrelation of the per-unit count over the
  whole study period.
- **Inputs.** Per-unit count 2022–2025; weights as above.
- **Parameters / inference.** I, E[I]; conditional-permutation pseudo p with
  999 permutations (project choice) and the analytic normality z and p
  (`esda.Moran.z_norm`, `p_norm`). Both are written.
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
- **Inference.** Analytic z with the Ord & Getis (1995) variance for general
  weights (`crime.esri.local.gi_star_z`; esda 2.6's own `Zs` uses the binary
  formula), **two-sided** normal p `2·Φ(−|z|)`, BH across units, α = 0.05.
  Deterministic; no permutations.
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
- **Inference.** Conditional permutation, 499 permutations (Esri default),
  esda's folded pseudo p, BH across units.
- **Citation.** Anselin, L. (1995). Local indicators of spatial association —
  LISA. *Geographical Analysis* 27(2).
- **Esri.** "How Cluster and Outlier Analysis (Anselin Local Moran's I)
  works": same 499-permutation default; BH here, with no claim of identity to
  Esri's optional FDR correction.

**Outputs (2a–c).** `static_summary.csv` (per group × support × weights: I,
z, p; Gi* hot / cold / ns counts; LISA HH / LL / HL / LH / ns counts) and
`static_by_unit/<support>.parquet` (per-unit z, adjusted p and label).

## 3. How it changes: Emerging Hot Spot Analysis and space-time LISA

### 3a. Space-time cube

Events are counted per unit and time bin; every unit and every bin of the
window is present, empty cells are 0 (`crime.esri.cube.space_time_cube`).
Time units: calendar quarter (16 bins, primary; project choice) and calendar
month (48 bins).

### 3b. Emerging Hot Spot Analysis (EHSA)

- **Tests.** For each unit: is it a significant Gi* hot (cold) spot in each
  bin, and does its Gi* z series trend over time? The pattern of significant
  bins plus the trend give one of 17 categories (new, consecutive,
  intensifying, persistent, diminishing, sporadic, oscillating, historical ×
  hot / cold, or no pattern).
- **Space-time Gi*** (`crime.esri.ehsa.gi_space_time`, neighbourhood
  `"spacetime"`, time step 1, backward window). One Gi* over the stacked cube
  (n units × T bins), standardised against the whole cube. **What the code
  does with the weights** (`crime.esri.weights.space_time_weights` followed by
  esda's Gi* self-weight; verified numerically on a toy lattice): the block for
  the same bin is the row-standardised spatial matrix, the block for the
  previous bin is the spatial matrix plus the identity, the whole row is
  row-standardised, then esda adds the self-weight (= row maximum) and
  re-standardises. For any bin after the first, the cell (i, t) therefore
  weights its own value at t by 1/4, its own value at t − 1 by 1/4, its
  neighbours at t by 1/4 in total and its neighbours at t − 1 by 1/4 in total:
  **half own history, half neighbours**. In the first bin (no previous bin)
  the own value gets the same weight as each neighbour, 1/(k + 1). Esri uses
  binary weights over the space-time neighbourhood ("How Emerging Hot Spot
  Analysis works"), so each neighbour-bin counts equally there; the code's
  weighting is a project convention, not an Esri clone.
- **Inference.** Two-sided analytic p per cell, BH within each time bin; a
  cell is hot (cold) if z > 0 (< 0) and adjusted p < 0.05.
- **Trend.** Mann–Kendall on each unit's Gi* z series with the Hamed–Rao
  variance correction for serial correlation (lags up to 3, significant
  autocorrelations only, inflation-only: the variance factor is floored at 1,
  a conservative project adaptation), BH across units.
- **Rules.** Esri's category table with the 90 % rule (persistent /
  intensifying / diminishing / historical need ≥ 90 % of bins significant)
  (`crime.esri.ehsa.classify_pattern`).
- **Citations.** Esri, "How Emerging Hot Spot Analysis works" (category
  rules). Getis & Ord (1992); Ord & Getis (1995). Mann, H.B. (1945).
  Nonparametric tests against trend. *Econometrica* 13. Kendall, M.G. (1975).
  *Rank Correlation Methods*. Griffin. Hamed, K.H. & Rao, A.R. (1998). A
  modified Mann-Kendall trend test for autocorrelated data. *Journal of
  Hydrology* 204. Benjamini, Y. & Hochberg, Y. (1995). Controlling the false
  discovery rate. *JRSS B* 57(1).
- **Esri differences.** Binary vs row-standardised space-time weights (above);
  Esri applies plain Mann–Kendall, here Hamed–Rao; FDR families (per bin for
  Gi*, across units for the trend) are this project's.

### 3c. Space-time LISA

- **Tests.** Local Moran's I on every time bin separately (per-bin BH, 499
  permutations); per unit, the number of HH and LL bins and the modal
  significant label.
- **Citation.** Anselin (1995).
- **Esri.** "Local Outlier Analysis" uses a space-time neighbourhood on the
  cube; the slice-by-slice application here is a project choice.

**Outputs (3).** `ehsa_summary.csv` (per group × support × weights × time unit:
the 17 category counts; space-time LISA bin-label counts and units ever HH /
LL) and `ehsa_by_unit/<support>.parquet`.

## 4. Time Series Clustering

- **Describes.** Groups of units whose monthly series are similar in level
  (`value`) or in shape (`profile`, correlation). No inference.
- **Inputs.** Monthly cube (project choice); units with ≥ 1 event in the
  period (project choice; others get cluster −1).
- **Parameters.** k-means, 10 random starts per k; k ∈ 2…10 chosen by the
  largest Calinski–Harabasz pseudo-F (Esri rule).
- **Citation.** Caliński, T. & Harabasz, J. (1974). A dendrite method for
  cluster analysis. *Communications in Statistics* 3(1).
- **Esri differences** ("How Time Series Clustering works"; listed in
  `crime/esri/tsclust.py`): profile (correlation) uses k-means on z-scored
  series (squared Euclidean distance = 2T(1 − r)) instead of k-medoids on
  1 − r; centres are means, not medoids, and there is no `CENTER_REP` field;
  pseudo-F is scikit-learn's Calinski–Harabasz on the feature space; the
  Fourier option (not run here) uses |DFT| of the first harmonics.
- **Outputs.** `tsc_summary.csv` (k, pseudo-F by k), `tsc_sizes.csv`,
  `tsc_profiles.csv`, `tsc_by_unit/<support>.parquet`.

## 5. MAUP: sensitivity to the support and to the weights

- **Across supports** (`crime.esri.maup.support_sensitivity`). Labels are
  reduced to a family (hotspot / coldspot / no pattern). The common reference
  is the **census tract** (project choice): for each tract, the family whose
  units of the other support cover the largest share of the tract's area is
  assigned (overlay majority by intersection area; project choice). For
  supports coarser than tracts this is the family of the unit covering most of
  the tract. Compared: static Gi* and quarterly EHSA, queen weights.
  Metrics per tract: raw agreement, hot-spot / cold-spot / patterned Jaccard,
  Cohen's kappa.
- **Across weights** within a support: queen vs rook, queen vs knn, rook vs
  knn for Gi*, LISA and EHSA (both time units): raw label agreement, family
  agreement, hot (HH for LISA) and cold (LL) Jaccard, Cohen's kappa.
- **Citations.** Openshaw, S. (1984). *The Modifiable Areal Unit Problem*.
  CATMOG 38. Cohen, J. (1960). A coefficient of agreement for nominal scales.
  *Educational and Psychological Measurement* 20(1). Jaccard, P. (1912). The
  distribution of the flora in the alpine zone. *New Phytologist* 11(2).
- **Esri.** No counterpart.
- **Outputs.** `maup_supports.csv`, `maup_weights.csv`. Agreement is counted
  per tract (unweighted by area or population).

## 6. Point patterns

The points are the geocoded bulletins inside a 2022 tract. About 63 % of them
share an exact coordinate with another bulletin (street-level geocodes stacked
on one point), so Ripley's L and the NNI are computed on **all points** and on
**distinct locations** (one point per coordinate) as a sensitivity.

### 6a. Ripley's K as Besag's L

- **Tests.** H0: complete spatial randomness (CSR) in the municipality, at
  distances 100, 200, …, 3,000 m.
- **Parameters.** Naive estimator, **no edge correction**; seeded random
  subsample of 20,000 points when larger (project choice); min/max envelope of
  99 CSR simulations at the same n (pointwise two-sided level 0.02).
- **Citations.** Ripley, B.D. (1976). The second-order analysis of stationary
  point processes. *J. Applied Probability* 13(2). Besag, J. (1977).
  Contribution to the discussion of Dr Ripley's paper. *JRSS B* 39(2).
  Besag, J. & Diggle, P.J. (1977). Simple Monte Carlo tests for spatial
  pattern. *Applied Statistics* 26(3).
- **Esri.** "How Multi-Distance Spatial Cluster Analysis (Ripley's K-function)
  works": Esri offers edge corrections; none is applied here (the envelope
  shares the window, so the bias is common to observed and simulated curves).

### 6b. Average nearest neighbour (Clark–Evans)

- **Tests.** R = observed / expected mean nearest-neighbour distance under
  CSR; z and two-sided normal p; area = municipality. No edge correction.
  Coincident points (distance 0) are counted and reported.
- **Citation.** Clark, P.J. & Evans, F.C. (1954). Distance to nearest neighbor
  as a measure of spatial relationships in populations. *Ecology* 35(4).
- **Esri.** "How Average Nearest Neighbor works": same ratio, z and p.

### 6c. Kernel density

- **Describes.** Quartic-kernel intensity surface, points per km², 100 m cells
  (project choice), default bandwidth = Esri's spatial variant of Silverman's
  rule of thumb. No inference; no edge correction.
- **Citation.** Silverman, B.W. (1986). *Density Estimation for Statistics and
  Data Analysis*. Chapman & Hall. Esri, "How Kernel Density works".
- **Outputs (6).** `points_summary.csv`, `ripley_<group>.csv`,
  `kde_<group>.parquet` (cell centres and density).

## 7. Space–time interaction: Knox test

- **Tests.** H0: no space–time interaction — the times are exchangeable over
  the fixed locations. Statistic: number of pairs within a space band and a
  time band; Knox ratio = observed / mean of permutations.
- **Parameters.** Space bands [0,100], (100,200], (200,400], (400,800] m; time
  bands [0,7], (7,14], (14,30], (30,60] days (project choice); 999
  permutations of the event dates; one-sided pseudo p `(r + 1)/(P + 1)`, not
  adjusted across the 16 cells. Groups with more than 40,000 events are
  analysed on a seeded random sample of 40,000 (project choice; `all` and
  `property`).
- **Citations.** Knox, E.G. (1964). The detection of space-time interactions.
  *Applied Statistics* 13(1). Johnson, S.D. & Bowers, K.J. (2004). The
  stability of space-time clusters of burglary. *British Journal of
  Criminology* 44(1).
- **Esri.** No counterpart (the band table follows Ratcliffe's Near Repeat
  Calculator layout, without its "beyond" row and column).
- **Caveat.** A population that shifts in space over the period can produce
  apparent interaction (Kulldorff, M. & Hjalmars, U. 1999. The Knox method and
  other tests for space-time interaction. *Biometrics* 55(2)). Stacked
  geocodes create many distance-0 pairs.
- **Outputs.** `knox_<group>.csv` (all 16 cells), `knox_summary.csv`.

## 8. Association with urban features

- **Inputs.** Crime count per unit for 2022–2025 and for 2022 alone (the
  census year; project choice to report both). Features at every support:
  CNEFE 2022 address counts by use type (education, health, "other purposes"
  as the commerce proxy, religious; deduplicated on address × use type,
  assigned by point-in-polygon) and resident population. Population on
  non-tract supports is the tract value split by **area share** (Goodchild,
  M.F. & Lam, N.S.-N. 1980. Areal interpolation: a variant of the traditional
  spatial problem. *Geo-Processing* 1; project choice; assumes residents are
  uniform within a tract; `crime.data.units.areal_interpolate`). Tract only:
  mean nominal monthly income of household heads (`income_head_mean`, IBGE
  `V06004`) and the literacy rate of residents aged 15+.
- **Spearman's ρ** with its p-value (no spatial adjustment). Spearman, C.
  (1904). The proof and measurement of association between two things.
  *American Journal of Psychology* 15.
- **Global bivariate Moran's I**, both orders (feature vs spatial lag of crime;
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
- **No multiple-testing adjustment** across the feature × group × support
  table.
- **Outputs.** `association.csv`, `association_local.csv`,
  `association_local_by_unit.parquet`.

## Known limitations

- **Analytic Gi* on skewed, sparse counts.** The normal approximation behind
  the analytic Gi* p-value is poor for skewed counts with many zeros: it
  over-calls hot spots and rarely calls cold spots. Simulation evidence is in
  the parked issue rsushizawa/IC-Crime#22. This affects static Gi* and every
  EHSA category.
- **Permutation resolution vs BH (LISA, space-time LISA, local bivariate
  Moran).** With 499 permutations the smallest attainable pseudo p is
  1/500 = 0.002. BH at 0.05 over n units rejects nothing unless at least
  0.002 · n / 0.05 = n / 25 units sit at that floor (104 of 2,592 tracts,
  333 of 8,313 0.1 km² hexagons). Static LISA can therefore report no
  significant unit on the larger supports even where many raw p are < 0.05
  (property, tracts, queen: 517 units with raw p < 0.05, 59 at the floor, 0
  after BH). More permutations or a different error-rate family would change
  this; the defaults are kept as configured.
- **esda tie handling.** esda 2.6.0 counts ties with the observed statistic
  only in the upper tail of the permutation distribution, so units whose
  value and neighbourhood are all zero can be labelled significant LL /
  cold (parked issue rsushizawa/IC-Crime#22). This affects LISA and
  space-time LISA LL counts for sparse groups and fine supports.
- **Stacked geocodes.** ~63 % of geocoded bulletins share an exact coordinate
  with another bulletin (street-level geocoding). Counts per unit are
  concentrated on those points, point-pattern statistics see many
  zero-distance pairs (hence the distinct-location sensitivity), and Knox's
  closest band is inflated by same-place pairs.
- **Recorded, not total, crime.** Counts are bulletins registered with the
  police, not incidents; reporting propensity varies by offence and place.
- **Geocoding share differs by group.** Share of in-window bulletins with a
  tract (2022–2025): property 83 %, traffic 96 %, drug 86 %, violent 71 %,
  bodily harm 43 %, sexual 0 % (no published locations). Spatial results for
  bodily harm are based on fewer than half of its bulletins.
- **Ripley's L and NNI without edge correction**, with the area of the whole
  municipality (including sparsely settled rural land) as the window.
- **Reporting lag at the end of 2025.** Time is the occurrence date. Offences
  that occurred in late 2025 but were registered after the extract are
  missing, which can depress the last bins and the end of the STL trend.
- **2022 census covariates** are compared with 2022–2025 crime; the 2022-only
  rows are written for the census-year comparison. 90 tracts have no income
  or literacy value (suppressed or uninhabited) and are dropped from those
  pairs.
