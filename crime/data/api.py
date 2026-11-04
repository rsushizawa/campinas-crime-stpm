"""The notebook data API — the only project code the analysis notebooks import.

Everything statistical happens in the notebooks with the libraries themselves
(libpysal, esda, pointpats, pymannkendall, statsmodels, scipy, scikit-learn,
tobler); this module only hands them the data, in one CRS, with one event set.

    from crime.data import load_points, load_units, unit_counts, cnefe_poi_points, unit_poi_counts

    pts = load_points("property")            # GeoDataFrame, one row per bulletin
    tr  = load_units("tract")                # 2,592 tracts + census attributes
    y   = unit_counts("tract", "property")   # Series: unit_id -> count (all 2,592 units)
    Y   = unit_counts("utb", "all", freq="M")  # DataFrame: 93 units x 48 months

Event set
    The **geocoded-in-tract** bulletins: rows of
    ``outputs/data/bulletins_clean.parquet`` (stage 02, one row per bulletin)
    with a 2022 census tract (``cd_setor`` not null; the bulletin has a usable
    coordinate that lies in the tract mesh) and an occurrence date in
    2022-01-01 .. 2025-12-31. 107,859 rows on the current data; every support
    counts exactly this set, so tract, UTB and point totals agree.
CRS
    EPSG:31983 (SIRGAS 2000 / UTM 23S, :data:`crime.core.config.CRS_METRIC`),
    metres, for every frame returned here.
Crime groups
    :data:`GROUPS` = ``all`` + the five ``etl.taxonomy.CRIME_GROUPS`` with
    published locations (``property``, ``bodily_harm``, ``traffic``, ``drug``,
    ``violent``). The groups are disjoint — a bulletin has one ``group`` — so
    ``group="all"`` is their union. ``sexual`` has no coordinates (0 %
    geocoded) and is not a spatial group.

Functions
    ``load_points(group="all")``
        GeoDataFrame of points: ``event_id`` (``"ANO_BO/NUM_BO/NOME_DELEGACIA"``,
        the stage-02 bulletin key), ``date`` (occurrence date), ``datetime``
        (date + ``HORA_OCORRENCIA_BO``; NaT where the hour is missing or
        unparseable), ``year``, ``month`` and ``quarter`` (period-start
        Timestamps), ``period_of_day`` (``DESC_PERIODO``), ``crime_slug``,
        ``group``, ``cd_setor``, ``utb`` (UTB ``unit_id``), ``geometry``.
    ``load_units(support)``  (``"tract"`` | ``"utb"``)
        GeoDataFrame: ``unit_id``, ``area_km2``, ``geometry``; tracts add
        ``population`` (IBGE 2022 ``V0001``), ``income_head_mean`` /
        ``income_head_median`` (``V06004`` / ``V06006``, NaN where IBGE
        suppresses) and ``literacy_rate`` (see :mod:`crime.data.cleaning`);
        UTBs add ``utb_sigla``.
    ``unit_counts(support, group="all", freq=None)``
        ``freq=None``: Series ``unit_id -> count`` over 2022-2025.
        ``freq`` in ``"M"`` / ``"Q"`` / ``"Y"``: DataFrame unit x period
        (columns = period-start Timestamps 2022-01 .. 2025-12: 48 / 16 / 4).
        Zero-filled for every unit and period; rows in :func:`load_units` order.
    ``cnefe_poi_points()``
        CNEFE 2022 POI address points (education, health, commercial,
        religious; deduplicated) with a ``poi`` column, EPSG:31983.
    ``unit_poi_counts(support)``
        DataFrame ``unit_id`` x (``n_commercial``, ``n_education``,
        ``n_health``, ``n_religious``), zero-filled.

Assignment rules
    ``cd_setor`` is stage 02's point-in-polygon tract (``within``). ``utb`` is
    the UTB polygon containing the point, else the nearest UTB
    (:func:`crime.data.units.assign_nearest`): 22 in-tract bulletins fall in
    slivers between the UTB polygons, all within 84 m of one.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd

from crime.core.config import BULLETINS_PARQUET, CNEFE_JSON, CRS_METRIC, CRS_WGS84, TRACT_ATTRIBUTES_PARQUET
from crime.data.cleaning import DATE_END, DATE_START
from crime.data.units import SUPPORTS, Support, assign_nearest, assign_points, unit_polygons

#: crime groups with points: "all" + the spatial groups of etl.taxonomy.CRIME_GROUPS
GROUPS = ("all", "property", "bodily_harm", "traffic", "drug", "violent")
#: pandas period alias per ``freq`` accepted by :func:`unit_counts`
FREQS = {"M": "M", "Q": "Q", "Y": "Y"}
_TRACT_ATTRS = {"pop_total": "population", "income_head_mean": "income_head_mean",
                "income_head_median": "income_head_median", "literacy_rate": "literacy_rate"}
_COLS = ["DATA_OCORRENCIA_BO", "HORA_OCORRENCIA_BO", "DESC_PERIODO", "NUM_BO", "ANO_BO",
         "NOME_DELEGACIA", "LATITUDE", "LONGITUDE", "crime_slug", "crime_group", "cd_setor"]


def _check_group(group: str) -> None:
    if group not in GROUPS:
        raise ValueError(f"Unknown group {group!r}. Use one of: {', '.join(GROUPS)}.")


def _check_support(support: str) -> None:
    if support not in SUPPORTS:
        raise ValueError(f"Unknown support {support!r}. Use one of: {', '.join(SUPPORTS)}.")


# --------------------------------------------------------------------------- #
#  points
# --------------------------------------------------------------------------- #
def points_from_bulletins(b: pd.DataFrame, utbs: gpd.GeoDataFrame | None = None) -> gpd.GeoDataFrame:
    """The :func:`load_points` frame built from a cleaned-bulletin table ``b``
    (``bulletins_clean.parquet`` columns). ``utbs`` overrides the UTB polygons
    (for tests)."""
    b = b[b["cd_setor"].notna() & b["LATITUDE"].notna() & b["LONGITUDE"].notna()]
    date = pd.to_datetime(b["DATA_OCORRENCIA_BO"], errors="coerce")
    keep = date.ge(pd.Timestamp(DATE_START)) & date.le(pd.Timestamp(DATE_END))
    b, date = b[keep], date[keep].dt.normalize()
    hour = pd.to_timedelta(b["HORA_OCORRENCIA_BO"].astype("string").str.strip() + ":00", errors="coerce")
    out = pd.DataFrame({
        "event_id": (b["ANO_BO"].astype("string") + "/" + b["NUM_BO"].astype("string") + "/"
                     + b["NOME_DELEGACIA"].astype("string")).astype(str),
        "date": date,
        "datetime": date + hour,
        "year": date.dt.year.astype(int),
        "month": date.dt.to_period("M").dt.to_timestamp(),
        "quarter": date.dt.to_period("Q").dt.to_timestamp(),
        "period_of_day": b["DESC_PERIODO"].astype("string"),
        "crime_slug": b["crime_slug"].astype(str),
        "group": b["crime_group"].astype(str),
        "cd_setor": b["cd_setor"].astype(str),
    }, index=b.index)
    g = gpd.GeoDataFrame(out, geometry=gpd.points_from_xy(b["LONGITUDE"], b["LATITUDE"]),
                         crs=CRS_WGS84).to_crs(CRS_METRIC)
    g.insert(len(g.columns) - 1, "utb", assign_nearest(g, unit_polygons("utb") if utbs is None else utbs))
    return g.reset_index(drop=True)


@functools.lru_cache(maxsize=1)
def _all_points(path: str) -> gpd.GeoDataFrame:
    return points_from_bulletins(pd.read_parquet(path, columns=_COLS))


def load_points(group: str = "all") -> gpd.GeoDataFrame:
    """Geocoded-in-tract bulletins of ``group`` (module docstring), EPSG:31983.
    Returns a fresh copy (the parsed table is cached per process)."""
    _check_group(group)
    g = _all_points(str(BULLETINS_PARQUET))
    if group != "all":
        g = g[g["group"].eq(group)]
    return g.copy().reset_index(drop=True)


# --------------------------------------------------------------------------- #
#  units
# --------------------------------------------------------------------------- #
def _tract_attributes() -> pd.DataFrame:
    """``crime.data.cleaning.build_tract_attributes`` (needs the IBGE census zips in
    ``inputs/data/geobr/``), cached to ``outputs/data/tract_attributes.parquet``."""
    path = Path(TRACT_ATTRIBUTES_PARQUET)
    if not path.exists():
        from crime.data.cleaning import build_tract_attributes

        ta = build_tract_attributes()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")      # atomic: notebooks may run in parallel
        ta.to_parquet(tmp)
        os.replace(tmp, path)
    ta = pd.read_parquet(path)
    return ta.set_index(ta["unit_id"].astype(str))


def load_units(support: Support) -> gpd.GeoDataFrame:
    """Units of ``support`` (``"tract"`` | ``"utb"``) with ``unit_id``, ``area_km2``,
    ``geometry`` (EPSG:31983) and, for tracts, ``population``,
    ``income_head_mean``, ``income_head_median``, ``literacy_rate``."""
    _check_support(support)
    u = unit_polygons(support)
    if support == "tract":
        ta = _tract_attributes()
        for src, dst in _TRACT_ATTRS.items():
            u.insert(len(u.columns) - 1, dst, ta[src].reindex(u["unit_id"]).to_numpy())
    return u


def unit_counts(support: Support, group: str = "all", freq: str | None = None) -> pd.Series | pd.DataFrame:
    """Bulletins of ``group`` per unit of ``support``; per unit x period when
    ``freq`` is ``"M"``, ``"Q"`` or ``"Y"`` (module docstring). Zero-filled."""
    _check_support(support)
    _check_group(group)
    pts = load_points(group)
    col = "cd_setor" if support == "tract" else "utb"
    ids = pd.Index(unit_polygons(support)["unit_id"], name="unit_id")
    if freq is None:
        return pts[col].value_counts().reindex(ids, fill_value=0).astype(int).rename("count")
    if freq not in FREQS:
        raise ValueError(f"freq must be None or one of {', '.join(FREQS)}, got {freq!r}")
    periods = pd.period_range(DATE_START, DATE_END, freq=FREQS[freq]).to_timestamp()
    start = pts["date"].dt.to_period(FREQS[freq]).dt.to_timestamp()
    wide = pd.crosstab(pts[col], start).reindex(index=ids, columns=periods, fill_value=0).astype(int)
    wide.columns.name = "period"
    return wide


# --------------------------------------------------------------------------- #
#  CNEFE points of interest
# --------------------------------------------------------------------------- #
def cnefe_poi_points(cnefe_path: str | Path = CNEFE_JSON) -> gpd.GeoDataFrame:
    """CNEFE 2022 POI address points (:func:`crime.data.cleaning.cnefe_poi_points`:
    use types 4/5/6/8, deduplicated on address + use type) in EPSG:31983."""
    from crime.data.cleaning import cnefe_poi_points as _raw

    return _raw(Path(cnefe_path)).to_crs(CRS_METRIC)


def unit_poi_counts(support: Support, cnefe_path: str | Path = CNEFE_JSON) -> pd.DataFrame:
    """CNEFE POI addresses per unit and use type (``n_commercial`` ...), zero-filled.

    Tracts: :func:`crime.data.cleaning.poi_counts` (point-in-polygon; the counts
    behind the tract attributes). UTBs: POIs inside the tract mesh, assigned
    like the crime points (containing UTB, else nearest)."""
    from crime.data.cleaning import POI_SPECIES, poi_counts

    _check_support(support)
    u = unit_polygons(support)
    cols = list(POI_SPECIES.values())
    if support == "tract":
        out = poi_counts(Path(cnefe_path), u)
    else:
        pts = cnefe_poi_points(cnefe_path)
        pts = pts[assign_points(pts, unit_polygons("tract")).notna()]
        out = pd.crosstab(assign_nearest(pts, u), pts["poi"])
    out = out.reindex(index=pd.Index(u["unit_id"], name="unit_id"), columns=cols, fill_value=0)
    out.columns.name = None
    return out.fillna(0).astype(int)
