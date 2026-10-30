"""Shared test configuration: skip ``@pytest.mark.db`` tests when PostGIS is unreachable.

"Unreachable" means *any* failure to open a connection with the configured
``PGHOST``/``PGPORT``/... (see :class:`crime.core.config.DBConfig`): no
server, a timeout, or an authentication error from some other Postgres that
happens to own the port. The probe runs once per session, and only if a
``db`` test was collected.
"""
from __future__ import annotations

import functools

import pytest


@functools.lru_cache(maxsize=1)
def _db_unreachable_reason() -> str | None:
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return "SQLAlchemy not installed (install the `db` extra)"

    from crime.core.config import DBConfig

    db = DBConfig()
    try:
        eng = create_engine(db.url, connect_args={"connect_timeout": 3})
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1 FROM fato_crimes LIMIT 1"))
        finally:
            eng.dispose()
    except Exception as e:  # noqa: BLE001 — connection refused, auth failure, missing table ...
        return f"PostGIS not reachable at {db.host}:{db.port}/{db.database} ({type(e).__name__})"
    return None


def pytest_collection_modifyitems(config, items):
    db_items = [it for it in items if it.get_closest_marker("db")]
    if not db_items:
        return
    reason = _db_unreachable_reason()
    if reason:
        for it in db_items:
            it.add_marker(pytest.mark.skip(reason=reason))
