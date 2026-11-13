# Package architecture


| Module | Responsibility |
|---|---|
| downloader | Versioned source retrieval, optional release updates and checksum verification |
| importer | Source reading and documented data treatments |
| geoprocessor | Coordinates, census attributes, tract assignment and weights |
| generator | Dataset, cube and paper workflow orchestration |
| warehouse | PostGIS setup, transactions, queries and reference snapshots |
| stpm | Temporal trends, Moran statistics, Gi* and EHSA |
| validation | Data schemas, profiling and external reconciliation |
| visualizer | Static figures and interactive cube exploration |
| exporter | Tables, geospatial files, interactive HTML and publication bundles |
| utils | Logging and checksums |

`crime.CrimeStudy` is the notebook-facing façade. It coordinates downloader,
importer, geoprocessor, generator and visualizer modules while preserving their
lower-level APIs for advanced workflows.

