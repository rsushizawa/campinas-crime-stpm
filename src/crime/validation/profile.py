"""Data profile of the loaded warehouse (report only; never stops the build).

For every column of every warehouse table: type, missing share, distinct
values, minimum and maximum. Written to ``outputs/reports/profile.md`` at the
end of ``the guided notebook warehouse setup``, so the profile describes exactly what the analysis reads.
"""
from __future__ import annotations

import pandas as pd

from crime.config import REPORTS_DIR

TABLES = ("fact_bulletin", "dim_census_tract", "poi", "dim_offence", "dim_date")


def profile_table(engine, table: str) -> pd.DataFrame:
    """One row per column of ``table`` (geometry excluded)."""
    from sqlalchemy import text

    with engine.connect() as conn:
        cols = [r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = :t "
            "AND udt_name <> 'geometry' ORDER BY ordinal_position"), {"t": table})]
        df = pd.read_sql(text(f"SELECT {', '.join(cols)} FROM {table}"), conn)
    rows = []
    for c in cols:
        s = df[c]
        num = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
        rows.append({"table": table, "column": c, "dtype": str(s.dtype), "rows": len(s),
                     "missing_%": round(100 * s.isna().mean(), 2), "distinct": int(s.nunique()),
                     "min": s.min() if num or pd.api.types.is_datetime64_any_dtype(s) else "",
                     "max": s.max() if num or pd.api.types.is_datetime64_any_dtype(s) else ""})
    return pd.DataFrame(rows)


def profile_warehouse(engine) -> str:
    """Profile of every table in :data:`TABLES`, saved as Markdown; returns the Markdown."""
    prof = pd.concat([profile_table(engine, t) for t in TABLES], ignore_index=True)
    head = "| " + " | ".join(prof.columns) + " |\n|" + "---|" * len(prof.columns)
    body = "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in prof.itertuples(index=False))
    md = "# Data profile of the warehouse\n\n" + head + "\n" + body + "\n"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "profile.md").write_text(md)
    prof.to_csv(REPORTS_DIR / "profile.csv", index=False)
    return md
