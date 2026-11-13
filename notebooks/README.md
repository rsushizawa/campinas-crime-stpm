# Guided examples

Use `stpm_exploration.ipynb` for data acquisition, PostGIS setup, EDA and the
interactive tract-quarter cube. Use `stpm_workflow.ipynb` for the paper pipeline.

Both run against an installed package. Upload a wheel to Colab and set
`PACKAGE_SOURCE` to its path, or install it beforehand. No repository clone is
required. Set the output workspace and external study-data directory before
importing the package; restart the kernel if changing them after import.

Base dos Dados requires Google authentication. SSP spatial analyses require the
external Campinas input release. Municipal aggregates cannot be used as tract
observations. Download the results archive before a temporary Colab runtime ends.
See the [package guide](../README.md) for installation and source configuration.
