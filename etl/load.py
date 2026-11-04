"""Stage 4, load: write the release into the PostGIS warehouse.

Treatment rules 23 to 25, plus the writes. The stage runs as::

    from etl.load import LoadInput, load_pipeline
    load_pipeline().run(LoadInput(...))

Order: apply ``database/schema.sql`` (drops and recreates every table), write
the dimensions, the fact table and the reject rows, check what was written,
then write the single ``build`` row last. If any check fails the ``build`` row
is never written, so a half-loaded database cannot be read
(:class:`crime.data.Warehouse` requires it).

Rows are inserted with :func:`psycopg2.extras.execute_values`; geometries are
sent as WKB and tagged with SRID 31983 by ``ST_SetSRID(ST_GeomFromWKB(...))``.
Foreign keys and ``CHECK`` constraints in the schema enforce rule 24 inside
the database.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
import pandas as pd

from crime.core import taxonomy
from crime.core.config import (
    DATA_VERSION,
    DATE_END,
    DATE_START,
    REPO_ROOT,
    SCHEMA_VERSION,
    __version__,
)
from etl.pipeline import Pipeline, ReportLine, StageFailed, StepResult, no_rejects

STAGE = "load"
SRID = 31983
SCHEMA_SQL = REPO_ROOT / "database" / "schema.sql"


@dataclass
class LoadInput:
    """Everything the load writes: staging tables, buffered rejects, reports, raw checksums."""

    engine: object
    bulletins: gpd.GeoDataFrame
    tracts: gpd.GeoDataFrame
    poi: gpd.GeoDataFrame
    rejects: pd.DataFrame
    stage_reports: dict
    raw_inputs: dict
    written: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  writing helpers
# --------------------------------------------------------------------------- #
def _py(v):
    """A Python value psycopg2 can send (NaN/NA to None, numpy scalars to Python)."""
    if v is None:
        return None
    if isinstance(v, (float, np.floating)) and np.isnan(v):
        return None
    if v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    return v


def insert(engine, table: str, df: pd.DataFrame, *, geometry: str | None = None, page_size: int = 5000) -> int:
    """Insert ``df`` into ``table`` with :func:`psycopg2.extras.execute_values`.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
    table : str
        Target table (an internal constant, never user input).
    df : DataFrame or GeoDataFrame
        Columns named as in the table.
    geometry : str, optional
        Name of the geometry column; sent as WKB with SRID 31983. The frame's
        CRS must be EPSG:31983, else :class:`StageFailed` (rule 25).
    page_size : int
        Rows per ``INSERT`` statement.

    Returns
    -------
    int
        Rows written.

    Raises
    ------
    StageFailed
        A constraint violation or a value the column type rejects (rule 24).
    """
    import psycopg2
    from psycopg2.extras import execute_values

    if geometry and (df.crs is None or df.crs.to_epsg() != SRID):
        raise StageFailed(f"rule 25, {table}: geometry CRS is {df.crs}, expected EPSG:{SRID}")
    cols = [c for c in df.columns if c != geometry]
    names = cols + ([geometry] if geometry else [])
    tmpl = "(" + ", ".join(["%s"] * len(cols)) + (f", ST_SetSRID(ST_GeomFromWKB(%s), {SRID})" if geometry else "") + ")"
    values = df[cols].astype(object).to_numpy()
    rows = []
    geoms = df[geometry].to_numpy() if geometry else None
    for i, r in enumerate(values):
        row = [_py(v) for v in r]
        if geometry:
            g = geoms[i]
            row.append(psycopg2.Binary(g.wkb) if g is not None and not g.is_empty else None)
        rows.append(row)
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            execute_values(cur, f"INSERT INTO {table} ({', '.join(names)}) VALUES %s", rows,
                           template=tmpl, page_size=page_size)
        raw.commit()
    except (psycopg2.IntegrityError, psycopg2.DataError) as exc:
        raw.rollback()
        raise StageFailed(f"rule 24, {table}: {exc.pgerror or exc}") from exc
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return len(rows)


def date_dimension(start: str = DATE_START, end: str = DATE_END) -> pd.DataFrame:
    """One row per day of the study window with its year, quarter and month bins."""
    d = pd.date_range(start, end, freq="D")
    return pd.DataFrame({
        "date": d.date, "year": d.year, "quarter": d.quarter, "month": d.month,
        "year_start": d.to_period("Y").to_timestamp().date,
        "quarter_start": d.to_period("Q").to_timestamp().date,
        "month_start": d.to_period("M").to_timestamp().date,
        "iso_weekday": d.isocalendar().day.to_numpy(),
    })


def offence_dimension() -> pd.DataFrame:
    """One row per slug of :mod:`crime.core.taxonomy` with group, labels and maximum penalty."""
    rows = []
    for slug in sorted(taxonomy.SLUG_TO_GROUP):
        grp = taxonomy.SLUG_TO_GROUP[slug]
        years, basis = taxonomy.MAX_PENALTY[slug]
        rows.append({"crime_slug": slug, "crime_group": grp, "offence_label": taxonomy.CRIME_TYPE_LABELS[slug],
                     "crime_group_label": taxonomy.CRIME_GROUP_LABELS[grp], "max_penalty_years": years,
                     "legal_basis": basis, "is_generic": taxonomy.is_generic(slug)})
    return pd.DataFrame(rows)


def fact_rows(b: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Units-stage bulletins renamed to the ``fact_bulletin`` columns."""
    from etl.steps.clean import bulletin_key

    out = pd.DataFrame({
        "bulletin_id": bulletin_key(b),
        "bulletin_year": b["ANO_BO"].astype("Int64"),
        "bulletin_number": b["NUM_BO"].astype(str),
        "police_station": b["NOME_DELEGACIA"].astype(str),
        "occurrence_date": pd.to_datetime(b["DATA_OCORRENCIA_BO"]).dt.date,
        # rule 8 keeps an unparsed hour as text; the TIME column takes only HH:MM, so anything else is missing
        "occurrence_time": b["HORA_OCORRENCIA_BO"].astype("string").where(
            b["HORA_OCORRENCIA_BO"].astype("string").str.fullmatch(r"([01]\d|2[0-3]):[0-5]\d").fillna(False)),
        "period_of_day": b["DESC_PERIODO"].astype("string"),
        "registration_date": pd.to_datetime(b["DATA_REGISTRO"]),
        "location_type": b["DESCR_SUBTIPOLOCAL"].astype("string"),
        "neighbourhood": b["BAIRRO"].astype("string"),
        "offence_reported": b["NATUREZA_APURADA"].astype(str),
        "crime_slug": b["crime_slug"].astype(str),
        "n_offence_records": b["n_records"].astype(int),
        "offences_on_bulletin": b["slugs_on_bulletin"].astype(str),
        "coord_status": b["COORD_STATUS"].astype(str),
        "latitude": b["LATITUDE"].astype(float),
        "longitude": b["LONGITUDE"].astype(float),
        "census_tract_id": b["census_tract_id"].astype("string"),
        "source_file": b["SOURCE"].astype(str),
    })
    return gpd.GeoDataFrame(out, geometry=b.geometry.values, crs=b.crs)


def git_commit() -> tuple[str, bool]:
    """``(commit, dirty)`` of the repository the code runs from."""
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True).strip()

    return git("rev-parse", "HEAD"), bool(git("status", "--porcelain", "--untracked-files=no"))


# --------------------------------------------------------------------------- #
#  steps
# --------------------------------------------------------------------------- #
class ApplySchema:
    """Drop and recreate every warehouse table from ``database/schema.sql``."""

    rule, action = "-", "fix"

    def run(self, x: LoadInput) -> StepResult:
        from sqlalchemy import text

        with x.engine.begin() as conn:
            conn.execute(text(SCHEMA_SQL.read_text()))
        return StepResult(x, no_rejects(), [ReportLine(type(self).__name__, self.rule, self.action, 0, 0, 0,
                                                        f"schema {SCHEMA_VERSION} applied")])


class WriteTables:
    """Write the dimensions, the points of interest, the fact table and the reject rows.

    Foreign keys and ``CHECK`` constraints run during the insert (rule 24).
    """

    rule, action = "24", "fail"

    def run(self, x: LoadInput) -> StepResult:
        w = {}
        w["dim_date"] = insert(x.engine, "dim_date", date_dimension())
        w["dim_offence"] = insert(x.engine, "dim_offence", offence_dimension())
        w["dim_census_tract"] = insert(x.engine, "dim_census_tract", x.tracts, geometry="geometry")
        w["poi"] = insert(x.engine, "poi", x.poi, geometry="geometry")
        fact = fact_rows(x.bulletins)
        w["fact_bulletin"] = insert(x.engine, "fact_bulletin", fact, geometry="geometry")
        rej = x.rejects.assign(data_version=DATA_VERSION)
        w["reject"] = insert(x.engine, "reject", rej[["data_version", "stage", "step", "rule", "record_key",
                                                      "reason", "record"]])
        x.written = w
        n = sum(w.values())
        return StepResult(x, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, n, n, 0,
            "; ".join(f"{k} {v:,}" for k, v in w.items()) + "; every key and constraint held")])


class CheckRowCounts:
    """Rule 23 (fail): rows in the database equal the rows handed over by the stages."""

    rule, action = "23", "fail"

    def run(self, x: LoadInput) -> StepResult:
        from sqlalchemy import text

        expected = {"dim_census_tract": len(x.tracts), "poi": len(x.poi), "fact_bulletin": len(x.bulletins),
                    "reject": len(x.rejects), "dim_offence": len(taxonomy.SLUG_TO_GROUP),
                    "dim_date": len(date_dimension())}
        with x.engine.connect() as conn:
            got = {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one() for t in expected}
        bad = {t: (got[t], expected[t]) for t in expected if got[t] != expected[t]}
        if bad:
            raise StageFailed("rule 23, row counts differ (database, expected): " + json.dumps(bad))
        n = len(expected)
        return StepResult(x, no_rejects(), [ReportLine(type(self).__name__, self.rule, self.action, n, n, 0,
                                                        f"{n} tables match the staged row counts")])


class CheckSRID:
    """Rule 25 (fail): every stored geometry has SRID 31983.

    :func:`insert` refuses a frame whose CRS is not EPSG:31983 before writing;
    this step checks what the database actually holds."""

    rule, action = "25", "fail"

    def run(self, x: LoadInput) -> StepResult:
        from sqlalchemy import text

        q = {t: f"SELECT COUNT(*) FROM {t} WHERE geometry IS NOT NULL AND ST_SRID(geometry) <> {SRID}"
             for t in ("dim_census_tract", "poi", "fact_bulletin")}
        with x.engine.connect() as conn:
            bad = {t: conn.execute(text(s)).scalar_one() for t, s in q.items()}
        if any(bad.values()):
            raise StageFailed(f"rule 25, geometries not in EPSG:{SRID}: {bad}")
        return StepResult(x, no_rejects(), [ReportLine(type(self).__name__, self.rule, self.action, 3, 3, 0,
                                                        f"all geometries EPSG:{SRID}")])


class WriteBuild:
    """Write the ``build`` row last: release version, commit, raw checksums, funnel, stage reports."""

    rule, action = "-", "fix"

    def run(self, x: LoadInput) -> StepResult:
        from sqlalchemy import text

        from crime.data.warehouse import funnel

        commit, dirty = git_commit()
        f = funnel(x.engine)
        reports = dict(x.stage_reports)
        reports[STAGE] = x.stage_reports.get(STAGE, [])
        with x.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO build (data_version, schema_version, package_version, code_commit, code_dirty, "
                "built_at, raw_inputs, funnel, stage_reports) VALUES (:dv, :sv, :pv, :c, :d, :t, "
                "CAST(:raw AS jsonb), CAST(:f AS jsonb), CAST(:rep AS jsonb))"),
                {"dv": DATA_VERSION, "sv": SCHEMA_VERSION, "pv": __version__, "c": commit, "d": dirty,
                 "t": dt.datetime.now(dt.timezone.utc), "raw": json.dumps(x.raw_inputs), "f": json.dumps(f),
                 "rep": json.dumps(reports)})
        return StepResult(x, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, 1, 1, 0,
            f"data-v{DATA_VERSION} from {commit[:7]}{' (uncommitted changes)' if dirty else ''}")],
            extra={"funnel": f})


def load_pipeline() -> Pipeline:
    """Schema, writes (rule 24), checks (rules 23, 25), then the build row."""
    return Pipeline(STAGE, [ApplySchema(), WriteTables(), CheckRowCounts(), CheckSRID(), WriteBuild()])
