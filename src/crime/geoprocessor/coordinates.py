"""Published SSP coordinate parsing and the pinned Campinas repair rules."""
import re

import numpy as np
import pandas as pd

REDACTED = "VEDAÇÃO DA DIVULGAÇÃO DOS DADOS RELATIVOS"


LAT_RANGE = (-23.3, -22.5)


LON_RANGE = (-47.5, -46.7)


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
