"""The packaged warehouse schema used by transactional release loading."""
from importlib.resources import files


def schema_sql() -> str:
    """Read the versioned PostGIS schema bundled with this package."""
    return files('crime.warehouse').joinpath('schema.sql').read_text(encoding='utf-8')
