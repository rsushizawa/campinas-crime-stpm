# Guided examples

Use `stpm_exploration.ipynb` for data acquisition, PostGIS setup, EDA and the
interactive tract-quarter cube. Use `stpm_workflow.ipynb` for the paper pipeline.

Both run against an installed package. Upload a wheel to Colab and set
`PACKAGE_SOURCE` to its path, or install it beforehand. No repository clone is
required. Set the output workspace and external study-data directory before
importing the package; restart the kernel if changing them after import.

SSP spatial analyses use the versioned Campinas data release. Set `DATA_PROFILE` to `snapshot` for the
reproducible release, `live` to retrieve current sources, or `hybrid` to keep
the snapshot while refreshing available live sources. For snapshots, set
`DATA_MODE` to `local` when the bundle is already on Drive, `download` to fetch
a selected release, or `auto` to reuse a verified local copy and download only
when it is absent. Set
`AUTO_UPDATE_DATA=True` only when you want the notebook to check the release's
`release.json` for a newer data version. The notebooks retain internal checksum,
schema, treatment, coordinate, and tract-assignment checks. Download the results archive before a temporary Colab
runtime ends.
See the [package guide](../README.md) for installation and source configuration.
