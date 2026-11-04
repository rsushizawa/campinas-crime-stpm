"""Core: configuration and the crime taxonomy. No I/O.

    config     paths, CRS, study window, schema and data versions, database settings
    taxonomy   offence names to slugs and crime groups; maximum penalty per slug
"""
from crime.core.config import DBConfig

__all__ = ["DBConfig"]
