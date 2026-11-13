"""Rule functions of the acquire stage: raw SSP-SP extracts to one Campinas offence-record table.

The stage itself is :func:`crime.importer.acquisition.acquire_pipeline`; each of its
steps calls one function of this module (IC-Crime#13).

Inputs (``CRIME_DATA_DIR``, never edited):

* ``crimes_campinas_2022_2024.csv.bak``: the 2022-2024 extract (origin unknown,
  see ``docs/data/ssp_raw_inputs.md``); already restricted to
  ``NOME_MUNICIPIO_CIRCUNSCRICAO == "CAMPINAS"``.
* ``SPDadosCriminais_2025.xlsx``: the statewide 2025 SPDados file, two
  half-year sheets.

Rules (each is counted in the stage report):

1. **One municipality filter for all years**:
   ``NOME_MUNICIPIO_CIRCUNSCRICAO == "CAMPINAS"``, the municipality of the
   police station with jurisdiction over the *place of the fact*. The
   analysis assigns events to Campinas tracts by location, so a
   place-of-fact filter is the consistent one; it is also the only filter
   that can be applied to 2022-2024, because the ``.bak`` contains no other
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
from pathlib import Path

import numpy as np
import pandas as pd

from crime.config import SSP_CSV_2022_2024, SSP_XLSX_2025
from crime.geoprocessor.coordinates import LAT_RANGE as LAT_RANGE
from crime.geoprocessor.coordinates import LON_RANGE as LON_RANGE
from crime.geoprocessor.coordinates import REDACTED as REDACTED
from crime.geoprocessor.coordinates import parse_coordinates as parse_coordinates

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
# Loose Campinas bounding box (same as docs/data/ssp_crimes_campinas.md).


# --------------------------------------------------------------------------- #
#  readers: every value comes back as a string (or NA), raw tokens preserved
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


def write_crimes_csv(df: pd.DataFrame, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for c in ("LATITUDE", "LONGITUDE"):
        out[c] = out[c].map(lambda v: "" if pd.isna(v) else repr(float(v)))
    out.to_csv(path, sep=";", index=False, na_rep="", lineterminator="\n", encoding="utf-8")
