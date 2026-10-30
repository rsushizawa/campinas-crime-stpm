"""Acquire stage: raw SSP-SP extracts -> one Campinas offence-record table (issue #13).

    from etl import acquire
    df, report = acquire.build_crimes_table()          # raw inputs from crime.core.config
    acquire.write_crimes_csv(df, CRIMES_CSV)

Inputs (``inputs/data/``, never edited):

* ``crimes_campinas_2022_2024.csv.bak`` — 2022–2024 extract (origin unknown,
  see ``docs/data/ssp_raw_inputs.md``); already restricted to
  ``NOME_MUNICIPIO_CIRCUNSCRICAO == "CAMPINAS"``.
* ``SPDadosCriminais_2025.xlsx`` — statewide 2025 SPDados file, two
  half-year sheets.

Rules (every rule is counted in the returned report):

1. **One municipality filter for all years**:
   ``NOME_MUNICIPIO_CIRCUNSCRICAO == "CAMPINAS"`` — the municipality of the
   police station with jurisdiction over the *place of the fact*. The
   analysis assigns events to Campinas tracts by location, so a
   place-of-fact filter is the consistent one; it is also the only filter
   that can be applied to 2022–2024, because the ``.bak`` contains no other
   municipality's rows.
2. **Missing tokens**: ``''``, ``'NULL'`` and the ``'NUL,L'`` artefact become
   missing in every column. The redaction text ``VEDAÇÃO DA DIVULGAÇÃO DOS
   DADOS RELATIVOS`` is kept in text columns (it is information: the field was
   withheld, not empty).
3. **Coordinates** get an explicit ``COORD_STATUS``:
   ``ok`` · ``fixed_decimal`` (digits without a decimal point, e.g.
   ``-2290311876.0`` -> ``-22.90311876``; fixed only if the result is
   inside the Campinas bounding box) · ``zero`` (``(0,0)``, the 2025
   redaction code, or the ``'0.0,'`` artefact) · ``redacted`` (``VEDAÇÃO``)
   · ``missing`` · ``invalid`` (unparseable or outside the bounding box after
   any fix). Only ``ok``/``fixed_decimal`` rows keep numeric LATITUDE/LONGITUDE.
4. Leading/trailing whitespace is stripped from text fields; times are
   written ``HH:MM``; dates ``YYYY-MM-DD``.

The output keeps the 25-column layout of the legacy
``inputs/data/crimes_campinas.csv`` plus ``COORD_STATUS`` and ``SOURCE``.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import numpy as np
import pandas as pd

from crime.core.config import SSP_CSV_2022_2024, SSP_XLSX_2025

COLUMNS = [
    "NOME_DEPARTAMENTO", "NOME_SECCIONAL", "NOME_DELEGACIA", "NOME_MUNICIPIO", "NUM_BO", "ANO_BO",
    "DATA_REGISTRO", "DATA_OCORRENCIA_BO", "HORA_OCORRENCIA_BO", "DESC_PERIODO", "DESCR_SUBTIPOLOCAL",
    "BAIRRO", "LOGRADOURO", "NUMERO_LOGRADOURO", "LATITUDE", "LONGITUDE",
    "NOME_DELEGACIA_CIRCUNSCRICAO", "NOME_DEPARTAMENTO_CIRCUNSCRICAO", "NOME_SECCIONAL_CIRCUNSCRICAO",
    "NOME_MUNICIPIO_CIRCUNSCRICAO", "RUBRICA", "DESCR_CONDUTA", "NATUREZA_APURADA",
    "MES_ESTATISTICA", "ANO_ESTATISTICA",
]
XLSX_SHEETS = ("JAN-JUN_2025", "JUL-DEZ_2025")
MUNICIPALITY_COL = "NOME_MUNICIPIO_CIRCUNSCRICAO"
MUNICIPALITY = "CAMPINAS"
MISSING_TOKENS = ("", "NULL", "NUL,L")
REDACTED = "VEDAÇÃO DA DIVULGAÇÃO DOS DADOS RELATIVOS"
# Loose Campinas bounding box (same as docs/data/ssp_crimes_campinas.md).
LAT_RANGE = (-23.3, -22.5)
LON_RANGE = (-47.5, -46.7)


# --------------------------------------------------------------------------- #
#  readers — every value comes back as a string (or NA), raw tokens preserved
# --------------------------------------------------------------------------- #
def _to_text(v) -> object:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return pd.NA
    if isinstance(v, pd.Timestamp | _dt.datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, _dt.time):
        return v.strftime("%H:%M:%S")
    return str(v)


def read_2022_2024(path: str | Path = SSP_CSV_2022_2024) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", dtype=str, keep_default_na=False, na_values=[], encoding="utf-8")
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    return df[COLUMNS].assign(SOURCE=Path(path).name)


def read_2025_xlsx(path: str | Path = SSP_XLSX_2025, *, sheets=XLSX_SHEETS) -> pd.DataFrame:
    """Both half-year sheets, columns renamed to the CSV spelling. Only rows that
    some Campinas field selects (circunscrição, registration municipality or
    ``CD_IBGE``) are kept; the statewide row count is in ``attrs``."""
    parts, n_rows = [], 0
    for sheet in sheets:                     # one sheet at a time: the statewide file is large
        df = pd.read_excel(path, sheet_name=sheet, engine="calamine", keep_default_na=False, na_values=[])
        df = df.rename(columns=lambda c: c.replace("CIRCUNCRIÇÃO", "CIRCUNSCRICAO"))
        missing = [c for c in COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"{path} [{sheet}]: missing columns {missing}")
        n_rows += len(df)
        # keep every row any Campinas field selects, so the filters can still be compared
        keep = (municipality_mask(df) | municipality_mask(df, "NOME_MUNICIPIO")
                | df["CD_IBGE"].astype(str).eq("3509502"))
        parts.append(df.loc[keep, COLUMNS + ["CD_IBGE"]].copy())
        del df
    sub = pd.concat(parts, ignore_index=True)
    out = pd.DataFrame({c: sub[c].map(_to_text) for c in COLUMNS + ["CD_IBGE"]})
    out.attrs["rows_read_statewide"] = n_rows
    return out.assign(SOURCE=Path(path).name)


# --------------------------------------------------------------------------- #
#  rules
# --------------------------------------------------------------------------- #
def municipality_mask(df: pd.DataFrame, col: str = MUNICIPALITY_COL) -> pd.Series:
    return df[col].astype("string").str.strip().eq(MUNICIPALITY).fillna(False).astype(bool)


def normalise_missing(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Strip text, map :data:`MISSING_TOKENS` to NA. Returns counts per token."""
    out = df.copy()
    counts = {t: 0 for t in MISSING_TOKENS}
    stripped = 0
    for c in COLUMNS:
        s = out[c].astype("string")
        st = s.str.strip()
        stripped += int((st != s).fillna(False).sum())
        for t in MISSING_TOKENS:
            counts[t] += int(st.eq(t).fillna(False).sum())
        out[c] = st.mask(st.isin(MISSING_TOKENS))
    return out, {"tokens_to_missing": counts, "cells_whitespace_stripped": stripped}


_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def _fix_decimal(v: float, lo: float, hi: float) -> float | None:
    """``-2290311876.0`` -> ``-22.90311876``: put the decimal point after the
    two integer digits Campinas coordinates have. None if not unambiguous."""
    digits = len(str(int(abs(v))))
    if digits <= 2:
        return None
    fixed = v / 10 ** (digits - 2)
    return fixed if lo <= fixed <= hi else None


def parse_coordinates(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Numeric LATITUDE/LONGITUDE + ``COORD_STATUS`` (see module docstring)."""
    lat_s = df["LATITUDE"].astype("string")
    lon_s = df["LONGITUDE"].astype("string")
    status = pd.Series("missing", index=df.index, dtype=object)
    lat = pd.Series(np.nan, index=df.index)
    lon = pd.Series(np.nan, index=df.index)
    for i, a, b in zip(df.index, lat_s, lon_s):
        if pd.isna(a) or pd.isna(b):
            if (isinstance(a, str) and a == REDACTED) or (isinstance(b, str) and b == REDACTED):
                status[i] = "redacted"
            continue
        if a == REDACTED or b == REDACTED:
            status[i] = "redacted"; continue
        a2, b2 = a.rstrip(","), b.rstrip(",")              # the '0.0,' artefact
        if not (_NUM.match(a2) and _NUM.match(b2)):
            status[i] = "invalid"; continue
        x, y = float(a2), float(b2)
        if x == 0 and y == 0:
            status[i] = "zero"; continue
        st = "ok"
        if abs(x) > 90 or abs(y) > 180:
            fx = _fix_decimal(x, *LAT_RANGE) if abs(x) > 90 else x
            fy = _fix_decimal(y, *LON_RANGE) if abs(y) > 180 else y
            if fx is None or fy is None:
                status[i] = "invalid"; continue
            x, y, st = fx, fy, "fixed_decimal"
        if not (LAT_RANGE[0] <= x <= LAT_RANGE[1] and LON_RANGE[0] <= y <= LON_RANGE[1]):
            status[i] = "invalid"; continue
        lat[i], lon[i], status[i] = x, y, st
    out = df.copy()
    out["LATITUDE"], out["LONGITUDE"], out["COORD_STATUS"] = lat, lon, status
    return out, {k: int(v) for k, v in status.value_counts().sort_index().items()}


def normalise_hour(s: pd.Series) -> tuple[pd.Series, dict]:
    """``HH:MM[:SS[.f]]`` -> ``HH:MM``. Reports rows with non-zero seconds (truncated)."""
    t = s.astype("string")
    m = t.str.extract(r"^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?$")
    ok = m[0].notna()
    out = (m[0].str.zfill(2) + ":" + m[1]).where(ok)
    bad = t.notna() & ~ok
    return out.mask(bad, t), {"hour_reformatted": int((ok & (t.str.len() > 5)).sum()),
                              "hour_nonzero_seconds": int((m[2].notna() & m[2].ne("00")).sum()),
                              "hour_unparsed_kept": int(bad.sum())}


# --------------------------------------------------------------------------- #
#  pipeline
# --------------------------------------------------------------------------- #
def build_crimes_table(*, csv_2022_2024: str | Path = SSP_CSV_2022_2024,
                       xlsx_2025: str | Path = SSP_XLSX_2025) -> tuple[pd.DataFrame, dict]:
    report: dict = {"filter": f"{MUNICIPALITY_COL} == {MUNICIPALITY!r}"}
    a = read_2022_2024(csv_2022_2024)
    b = read_2025_xlsx(xlsx_2025)
    report["rows_read"] = {"2022_2024_csv": int(len(a)),
                           "2025_xlsx_statewide": int(b.attrs["rows_read_statewide"]),
                           "2025_xlsx_campinas_candidates": int(len(b))}

    # the two candidate municipality fields, compared on the 2025 file
    circ, muni = municipality_mask(b), municipality_mask(b, "NOME_MUNICIPIO")
    report["xlsx_filter_comparison"] = {
        "circunscricao_campinas": int(circ.sum()), "registro_campinas": int(muni.sum()),
        "cd_ibge_3509502": int(b["CD_IBGE"].eq("3509502").sum()),
        "both": int((circ & muni).sum()),
        "circunscricao_only_kept": int((circ & ~muni).sum()),
        "registro_only_dropped": int((muni & ~circ).sum()),
    }
    report["filter_diff_rows"] = pd.concat([
        b[circ & ~muni].assign(FILTER_DIFF="kept: circunscricao only"),
        b[muni & ~circ].assign(FILTER_DIFF="dropped: registro only"),
    ])[["FILTER_DIFF", "NUM_BO", "ANO_BO", "NOME_DELEGACIA", "NOME_MUNICIPIO", MUNICIPALITY_COL,
        "NATUREZA_APURADA", "LATITUDE", "LONGITUDE"]]
    a_circ = municipality_mask(a)
    report["csv_rows_failing_filter"] = int((~a_circ).sum())

    df = pd.concat([a[a_circ], b[circ].drop(columns="CD_IBGE")], ignore_index=True)
    report["rows_after_filter"] = {"2022_2024_csv": int(a_circ.sum()), "2025_xlsx": int(circ.sum()),
                                   "total": int(len(df))}
    df, miss = normalise_missing(df)
    report.update(miss)
    df, coords = parse_coordinates(df)
    report["coord_status"] = coords
    df["HORA_OCORRENCIA_BO"], hours = normalise_hour(df["HORA_OCORRENCIA_BO"])
    report.update(hours)
    return df[COLUMNS + ["COORD_STATUS", "SOURCE"]], report


def write_crimes_csv(df: pd.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for c in ("LATITUDE", "LONGITUDE"):
        out[c] = out[c].map(lambda v: "" if pd.isna(v) else repr(float(v)))
    out.to_csv(path, sep=";", index=False, na_rep="", lineterminator="\n", encoding="utf-8")
