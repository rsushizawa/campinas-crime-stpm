"""Acquire, treat, analyze and publish police-recorded offence datasets.

Functional modules expose source retrieval, importing, geoprocessing, dataset
generation, PostGIS, STPM, visualization, export and validation. Importing the
root package performs no downloads, analysis or database connections.
"""
from crime.config import __version__ as __version__
from crime.study import CrimeStudy, CrimeStudyConfig, CrimeStudyResult

__all__ = ["CrimeStudy", "CrimeStudyConfig", "CrimeStudyResult", "__version__"]
