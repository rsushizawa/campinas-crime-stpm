"""campinas-crime-stpm: data layer for the space-time analysis of crime in Campinas (SP).

The analysis lives in ``notebooks/``. Each notebook asks the warehouse for its
data through :class:`crime.data.Warehouse` and then calls the statistics
libraries directly (libpysal, esda, pymannkendall, statsmodels, scipy). The
warehouse is built by the ETL stages in ``etl/`` (``make load``).

Subpackages: ``core`` (configuration, taxonomy) and ``data`` (request model,
warehouse reader).
"""
from crime.core.config import __version__ as __version__
