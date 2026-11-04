# Data treatments

Every problem the data can have, the treatment chosen for it, and the code
that applies it. The author agreed the table on 2026-11-03. Each rule is one
step of a stage pipeline (`etl/pipeline.py`); the step's report line gives the
number of rows it touched, and every row a rule removes goes to the warehouse's
`reject` table with the rule number.

Treatments:

- **fail**: stop the build with a message that names the rule and the evidence;
- **fix**: change values with a fixed rule and count the rows changed;
- **exclude**: remove the rows (counted in the funnel, kept in `reject`), or, for
  the spatial event set, keep the bulletin in the monthly series without a tract;
- **report**: keep the rows and count them; the paper discloses the ones marked
  *disclose*.

The rule-table categories follow Rahm & Do (2000), "Data cleaning: problems and
current approaches", *IEEE Data Engineering Bulletin* 23(4), and the error
event table of Kimball & Caserta (2004), *The Data Warehouse ETL Toolkit*.

| # | Stage | Problem | Treatment | Step |
|---|---|---|---|---|
| 1 | acquire | raw file missing or changed (SHA-256 differs from `inputs/data/SHA256SUMS`) | fail; checked again at load, so the `build` row records the files the stages read | `etl/steps/acquire.py: VerifyRawInputs`, `scripts/04_load/load_warehouse.py` |
| 2 | acquire | raw columns renamed or missing | fail | `ReadSources` |
| 3 | acquire | the two municipality fields of the 2025 file disagree | report (rows kept only by registration municipality go to `reject`) | `MunicipalityFilter` |
| 4 | acquire | placeholder values (`''`, `NULL`, `NUL,L`) | fix to missing | `NormaliseMissing` |
| 5 | acquire | coordinates `(0, 0)` | fix to missing; the bulletin leaves the spatial event set | `ParseCoordinates` |
| 6 | acquire | decimal point missing in a coordinate | fix when the repaired point is in the Campinas box; flagged `fixed_decimal` | `ParseCoordinates` |
| 7 | acquire | coordinates outside the Campinas box | exclude from the spatial event set (`invalid`) | `ParseCoordinates` |
| 8 | acquire | hour not in `HH:MM` | fix (the hour is not analysed); an hour that still does not parse is stored as missing | `NormaliseHour`, `etl/load.py: fact_rows` |
| 9 | clean | one bulletin, several offence records | fix: keep the most serious offence; the other records go to `reject`; disclose | `etl/steps/clean.py: CollapseBulletins` |
| 10 | clean | exact duplicate rows | fix (collapsed with rule 9, counted) | `CollapseBulletins` |
| 11 | clean | offence name not in the taxonomy | fail | `TaxonomyCheck` |
| 12 | clean | occurrence date missing, invalid or outside 2022-2025 | exclude | `ParseDates`, `OccurrenceWindow` |
| 13 | clean | occurrence date after the registration date | report (author decision, 2026-11-04) | `OccurrenceAfterRegistration` |
| 14 | clean | registration lag at the end of the series | report; disclose | `ReportingLag` |
| 15 | clean | many bulletins on one coordinate | report; disclose | `StackedGeocodes` |
| 16 | units | point on an edge shared by tracts | fix: first match, deterministic | `etl/steps/units.py: AssignTract` |
| 17 | units | point outside every tract | exclude from the spatial event set | `AssignTract` |
| 18 | units | invalid tract polygon or repeated tract id | fail | `LoadTracts` |
| 19 | units | tract without neighbours (island) | report; the notebooks label it "no data"; disclose | `TractIslands` |
| 20 | units | missing census attribute | report; left missing, pairwise exclusion in Spearman | `CensusAttributes` |
| 21 | units | tract with no residents | report (counts are analysed, not rates) | `CensusAttributes` |
| 22 | units | repeated CNEFE address and use type | fix: deduplicate, duplicates to `reject` | `PointsOfInterest` |
| 23 | load | rows in the database differ from the staged rows | fail | `etl/load.py: CheckRowCounts` |
| 24 | load | a bulletin points to a tract or offence that does not exist, or a value breaks a column type or `CHECK` | fail (foreign keys and constraints in `database/schema.sql`) | `WriteTables` |
| 25 | load | geometry not in EPSG:31983 | fail (the writer refuses a frame in another CRS; the check reads the stored SRIDs) | `insert`, `CheckSRID` |
| 26 | library | database not running, or holding no finished load | fail with the command to run (`make db`, `make load`, `make reload`) | `crime/data/warehouse.py: Warehouse` |
| 27 | library | warehouse built with another schema version | fail | `Warehouse` |
| 28 | library | invalid request (unknown group, slug or time unit; period outside the window; unknown location type) | fail (pydantic validation; location types checked against the warehouse) | `crime/data/query.py: CrimeQuery`, `Warehouse` |
| 29 | library | valid request that matches no bulletin | return every tract and bin with count 0 | `Warehouse.counts` |
| 30 | acceptance | warehouse-backed results differ from the paper's | fail | `tests/test_parity.py` |

## Counts in release data-v1.0.0

From the stage reports (`outputs/reports/*.md`):

| Rule | Rows |
|---|---|
| 3 | 46 rows kept on jurisdiction only and 46 dropped on registration only (2025 file) |
| 5-7 | 728 coordinates repaired; 5,632 zero, 13,144 redacted, 11,245 missing, 32 invalid (offence records) |
| 9-10 | 971 offence records merged into 941 bulletins; 1 exact duplicate; 4 ties kept in source order |
| 12 | 1,006 bulletins dated before 2022; 1 invalid date (`1202-02-28`) |
| 13 | 6 bulletins dated after their registration |
| 14 | median delay 1 day, 90th percentile 10, 99th percentile 108; 4,776 bulletins registered more than 30 days later |
| 15 | 68,061 of 107,912 geocoded bulletins share a coordinate; largest stack 413 |
| 17 | 53 geocoded bulletins outside every tract; 29,411 without a usable coordinate |
| 18 | 2,592 valid tracts |
| 19 | no island under queen contiguity |
| 20-21 | income and literacy missing for 90 tracts; 69 tracts with no residents |
| 22 | no repeated address and use type among the POI types |

## Rule 13

The first plan was to exclude the 6 bulletins dated after their registration.
Excluding them would change counts the paper reports (137,323 bulletins in the
window would become 137,317), so the author decided on 2026-11-04 to keep and
count them. `clean_pipeline("exclude")` still applies the exclusion if a later
release needs it.
