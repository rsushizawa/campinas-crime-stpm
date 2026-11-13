"""Exceptions raised at public package boundaries."""


class CrimeError(Exception):
    """Base error for the package."""


class ConfigurationError(CrimeError, ValueError):
    """A configuration cannot describe a valid study or operation."""


class DownloadError(CrimeError):
    """A source could not be retrieved or its checksum did not match."""


class ProcessingError(CrimeError):
    """A data treatment or geospatial operation failed."""


class WarehouseError(CrimeError):
    """A warehouse connection, release or transaction failed."""


class ExportError(CrimeError):
    """A result could not be exported."""
