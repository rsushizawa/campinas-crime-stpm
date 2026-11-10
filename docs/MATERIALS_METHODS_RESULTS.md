# Materials and Methods and Results — revision draft

This draft accompanies the audit corrections. The corrected pipeline requires execution before submission. Values below describe the previously executed release and must be reconciled with the new release, especially spatial counts after boundary handling and literacy associations after preserving suppression.

## Materials and Methods

We conducted an ecological, retrospective analysis of police-recorded bulletins in Campinas, São Paulo, Brazil, with occurrence dates from January 2022 through December 2025. The geographic support comprised 2,592 census tracts from the 2022 IBGE mesh. Police records were obtained from a preserved 2022–2024 extract and a statewide 2025 workbook. Upstream provenance of the older extract remains incomplete. The final period may be affected by delayed registration.

Records were filtered using the municipality of the occurrence jurisdiction. Multiple offence records on one bulletin were collapsed using the documented maximum-penalty hierarchy. Consequently, group counts represent bulletins assigned to their selected principal offence. Monthly city totals include records without usable coordinates. Spatial analyses include records assigned to census tracts. Suppressed literacy counts are retained as missing. Complete-case literacy analyses report their own sample sizes. CNEFE species 6 is described as establishments for other purposes. Census covariates describe 2022 conditions.

Queen contiguity defines the primary spatial neighbourhood. Rook contiguity and five nearest neighbours assess sensitivity. Global Moran’s I describes spatial autocorrelation of counts. STL decomposes the 48 monthly observations with a period of twelve months. Trend and seasonal strength depend on smoothing and robustness settings. Original, seasonal and Hamed–Rao Mann–Kendall results are reported separately. Sen slopes describe the annual change in the monthly bulletin count.

Local Gi* and emerging hotspot labels are exploratory. EHSA uses sixteen quarterly bins and a binary space-time neighbourhood including the current and preceding quarter. The spatial-only sensitivity retains the whole-cube reference distribution. BH adjustment applies to bin tests. Adjacent local statistics share observations, and calibration of trend inference under this dependence remains required. Undefined trend tests receive an explicit unavailable status. Local Moran permutation inference requires a specified alternative and tie-aware calibration before the corrected local maps can be interpreted inferentially.

Urban features are compared with bulletin counts using Spearman correlation and bivariate Moran statistics. Count and density comparisons describe different variables. Their difference does not isolate an area effect. Ordinary correlation p-values do not account for spatial dependence. Associations are ecological and do not establish effects of establishments or characteristics of individuals.

## Results

The previous executed release contained 139,301 offence records, collapsed to 138,330 bulletins. Of these, 137,323 had occurrence dates within the study window and 107,859 were assigned to a tract. Property bulletins accounted for 90,436 of the mapped records. In-tract coverage differed markedly across groups, including 43.2% for bodily harm and 96.3% for traffic. Repeated exact coordinates occurred for 63.1% of mapped bulletins. These differences constrain comparisons of spatial patterns between groups.

Global Moran’s I for pooled counts was 0.376 with queen weights, 0.391 with rook weights and 0.298 with five nearest neighbours in the previous release. All eighteen group-by-neighbourhood runs indicated positive spatial autocorrelation. Interpretation is restricted to recorded counts on the chosen tract support.

The prior temporal analysis showed declining property bulletins and rising bodily-harm and drug-related bulletins. The pooled decline was sensitive to the trend test, with p = 0.011 for original Mann–Kendall, 0.058 for Hamed–Rao and 0.062 for the seasonal test. The end of the occurrence series remains vulnerable to reporting lag.

The prior quarterly EHSA labelled 294 tracts as hot and six as cold under raw bin thresholds. Bin-level BH reduced these totals to 170 and zero. These contrasts establish sensitivity to the inferential specification. Corrected hotspot subtype counts are pending calibrated execution. Historical LISA prose contradicted saved outputs and has been withdrawn from the notebooks.

Spearman correlation between bulletin counts and other-purpose establishment counts was 0.728, compared with 0.593 for the corresponding densities in the previous release. These values describe association under two scales. Literacy coefficients require regeneration because 499 suppressed illiteracy counts were previously imputed as zero.

## Work required before submission

Execute the revised ETL and notebooks against the full raw inputs. Validate atomic warehouse replacement, local permutation alternatives and ties, serial-dependence calibration, and first/final-bin sensitivity. Reconcile older SSP inputs and quantify geocoding sensitivity. Regenerate all result text and figures against the resulting release. The historical baseline remains a record of the earlier analysis, and differences caused by corrected methodology need an explicit migration review.
