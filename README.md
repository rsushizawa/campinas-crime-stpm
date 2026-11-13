# campinas-crime-stpm

Python tools for treating police-report data, building PostGIS warehouses,
space–time analysis, interactive exploration and scientific publication exports.
The included study workflow covers Campinas, Brazil, in 2022–2025.

## Install

Python 3.12 or newer is required. From this source checkout:

```bash
uv sync --all-extras
```

To build an installable wheel:

```bash
uv build --wheel
```

Install a wheel in a fresh environment or upload it to Colab:

```python
%pip install "/content/campinas_crime_stpm-1.0.0-py3-none-any.whl[etl,db,verification]"
```

This release has not yet been published to PyPI. Use the wheel or a source
checkout rather than assuming that a package-index version is available.

## Guided notebooks

- [Exploration](notebooks/stpm_exploration.ipynb): source acquisition, treatments,
  optional PostGIS, descriptive tables/plots, reference checks and cube viewer.
- [Full workflow](notebooks/stpm_workflow.ipynb): temporal trends, global/local
  Moran, Gi*, EHSA, associations and paper figures and Tables 6–10.

The notebooks work with an installed package, without repository scripts or a
Git clone. In their setup form, supply `PACKAGE_SOURCE` (the uploaded wheel path)
or use an already installed package. Choose `PROJECT_ROOT` for outputs and
`STUDY_DATA_DIRECTORY` for external raw data. Run cells in order.

Colab forms also expose the Google project ID (`campinas-crime-stpm` by default),
authentication and query byte limits. Live Base dos Dados access requires your
Google login. Municipal reference counts support temporal analysis and aggregate
reconciliation; tract-level hotspots require geocoded report data.

## Data and workspace

Raw study data are distributed separately. The package contains the eight-file
checksum manifest `crime/downloader/campinas-2022-2025.sha256` and verifies it
before running the pinned treatments. The default external data location is
`~/.local/share/campinas-crime-stpm/campinas-2022-2025`, respecting `XDG_DATA_HOME`.
Set `CRIME_DATA_DIR` before import to override it. Files retain the relative paths
in the manifest. Source notes and datasheets accompany the local data release.
A public data-release URL has not been published yet.

The notebook can download a release from `INPUT_RELEASE_URL` when that server
exposes the manifest's relative paths. It can also read a mounted/uploaded release.
`CRIME_PROJECT_ROOT` selects the workspace (default: current working directory);
results are written beneath its `outputs/` folder. Outputs are not package files.

## PostGIS

Choose temporary PostGIS in Colab, provide an external PostGIS connection, or
use in-memory analysis. The package bundles its SQL schema; no `database/` folder
is needed. The notebook's warehouse cell explicitly creates/loads the database.
Existing releases are protected unless replacement is selected. External reference
snapshots are stored separately from bulletin facts. Database credentials belong
in environment variables, a workspace-local `.env`, or the notebook's hidden prompt.

## Package and commands

[Architecture](docs/PACKAGE_ARCHITECTURE.md) describes the modules and shared
contracts. The package CLI supports cube generation, reference reconciliation and
publication export:

```bash
crime --help
crime cube --help
crime verify --print-sql
crime paper --help
```

Publication export requires the manuscript and its supporting inputs at an explicit
location. Rendering creates a separate bundle; copying into the manuscript is an
explicit operation. The interactive HTML cube displays a tract map, time series
and raw/adjusted significance histories, loading Leaflet and Plotly from CDNs.

## Reproducibility

`pyproject.toml` defines the package; `uv.lock` records the development environment.
Source snapshots, checksums, analysis parameters and output manifests record each
run. The repository contains no raw study files, historical outputs, legacy ETL
scripts or test folder. Python 3.12 wheel installation has been checked in an
isolated local environment; a fresh Colab runtime and live BigQuery queries still
require verification in an authenticated user session.
