"""Data: every read from and write to the outside world.

    query      ``CrimeQuery`` — the crime filter and its SQL ``WHERE`` clause
    postgis    ``PostGISSource`` — the default :class:`~crime.core.protocols.DataSource`
    loaders    ``load_sectors`` / ``load_grid`` / ``load_crime_points`` / ...
    spec       ``DatasetSpec`` — fluent builder over the loaders
    catalog    ``DEFAULT_FEATURES`` and the pre-registered crime-slug scopes
    artifacts  result persistence (``save_result`` / ``load_result`` / ``cached``)
    provenance run stamps (versions, git commit, DB target)
    cleaning   raw-file cleaning: occurrence-date window, tract join, IBGE 2022 income,
               literacy, CNEFE commerce by point-in-polygon

Submodules are imported on demand.
"""
