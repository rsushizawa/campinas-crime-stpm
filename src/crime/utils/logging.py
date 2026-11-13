"""Library loggers; configuring handlers belongs to the calling application."""
import logging


def get_logger(name: str) -> logging.Logger:
    """Return a logger without altering the application's logging settings."""
    return logging.getLogger(name)
