"""Raw-file cleaning: crime events and per-tract census attributes.

Extracted from the scrapped count-model arm (issues #3–#6, 2026-10); only
the data-cleaning steps are kept.

Events
    :func:`filter_events` keeps crimes by **occurrence date** in
    [:data:`DATE_START`, :data:`DATE_END`] and drops unparseable dates (e.g.
    ``'1202-02-28'``). The lower bound removes the ~1,008 bulletins filed in
    2022+ for crimes that occurred earlier (issue #1).
    :func:`assign_tracts` joins each geocoded crime to its 2022 tract by
    point-in-polygon (``predicate='within'``, first match), as
    ``etl.postgis.assign_unit`` does.

Tract attributes (all 2022)
    ``pop_total``               IBGE 2022 Agregados por Setores / Básico ``V0001``.
    ``n_commercial``            CNEFE 2022 ``COD_ESPECIE == 6`` addresses
                                ("other purposes", the commerce proxy),
                                assigned by **point-in-polygon** (see
                                :func:`poi_counts`).
    ``n_education``, ``n_health``, ``n_religious``
                                CNEFE 2022 ``COD_ESPECIE`` 4, 5 and 8, same rule.
                                A CNEFE row is one use type at one address, so
                                rows are deduplicated on (``COD_UNICO_ENDERECO``,
                                ``COD_ESPECIE``): an address with a school and a
                                shop counts once in each (issue #18).
    ``income_head_mean``        IBGE 2022 Rendimento do Responsável ``V06004``:
                                mean nominal monthly income (R$) of household
                                heads with income. Suppressed tracts -> NaN.
    ``income_head_median``      same table, ``V06006`` (median).
    ``literacy_rate``           literate / (literate + illiterate) residents aged
                                15+ (``Painel_IBGE_2022.csv``). Where the
                                illiterate count is blank but the literate count
                                is filled (499 tracts), the illiterate count is
                                set to 0 (learner decision, 2026-10-15).
                                Evidence: non-blank illiterate counts are 0
                                (316 tracts) or >= 3 (never 1-2), so a blank is
                                most likely a suppressed 1-2. If the true value
                                were 2, the error on those 499 tracts would be
                                median 0.62, 95th pct 2.5, max 18.2 literacy
                                points. Tracts with both counts blank (90, the
                                same tracts IBGE suppresses for income) stay NaN.

    The UTB ``rendatemei`` field is a count of low-income residents, not an
    income (issue #1 comment 5), and is not used here.

    from crime.data.cleaning import build_tract_attributes
    tracts = build_tract_attributes()      # GeoDataFrame, EPSG:31983
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from crime.core.config import CRIMES_CSV, CRS_METRIC, CRS_WGS84, GEOBR_CACHE, INPUTS_DIR

DATE_START = "2022-01-01"
DATE_END = "2025-12-31"


@dataclass(frozen=True)
class RawPaths:
    """Where the raw inputs live (defaults: ``inputs/data/`` and the acquired CSV in ``outputs/data/``)."""

    crimes: Path = CRIMES_CSV
    geobr_cache: Path = GEOBR_CACHE
    census_basico: Path = GEOBR_CACHE / "Agregados_por_setores_basico_BR_20260520.zip"
    income: Path = GEOBR_CACHE / "Agregados_por_setores_renda_responsavel_BR_20260508_csv.zip"
    painel: Path = INPUTS_DIR / "Painel_IBGE_2022.csv"
    cnefe: Path = INPUTS_DIR / "qg_810_endereco_Munic3509502.json"


def filter_events(events: pd.DataFrame, *, slugs=None, start: str = DATE_START, end: str = DATE_END
                  ) -> tuple[pd.DataFrame, dict]:
    """Keep events (of ``slugs``, if given) whose ``data_ocorrencia`` lies in
    [start, end]. Unparseable dates are dropped. Returns the kept rows (with
    datetime ``data_ocorrencia`` and integer ``year``) and a dict of row counts
    at each step."""
    log = {"rows_in": int(len(events))}
    ev = events if slugs is None else events[events["crime_slug"].isin(tuple(slugs))]
    ev = ev.copy()
    log["rows_slug"] = int(len(ev))
    ev["data_ocorrencia"] = pd.to_datetime(ev["data_ocorrencia"], errors="coerce")
    lo, hi = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)
    in_window = ev["data_ocorrencia"].ge(lo) & ev["data_ocorrencia"].lt(hi)
    log["rows_before_start"] = int(ev["data_ocorrencia"].lt(lo).sum())
    log["rows_after_end"] = int(ev["data_ocorrencia"].ge(hi).sum())
    log["rows_bad_date"] = int(ev["data_ocorrencia"].isna().sum())
    ev = ev[in_window].copy()
    ev["year"] = ev["data_ocorrencia"].dt.year.astype(int)
    log["rows_window"] = int(len(ev))
    return ev, log


def assign_tracts(events: pd.DataFrame, tracts: gpd.GeoDataFrame) -> pd.Series:
    """Tract ``unit_id`` of each event's (``long``, ``lat``) point, NaN when
    the coordinates are missing or fall outside every tract. Point-in-polygon
    with ``predicate='within'``; first match kept (as ``etl.postgis.assign_unit``)."""
    out = pd.Series(np.nan, index=events.index, dtype=object)
    ok = events["lat"].notna() & events["long"].notna()
    if not ok.any():
        return out
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(events.loc[ok, "long"], events.loc[ok, "lat"]),
                           index=events.index[ok], crs=CRS_WGS84)
    poly = tracts[["unit_id", "geometry"]].to_crs(CRS_WGS84)
    j = gpd.sjoin(pts, poly, how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    out.loc[j.index] = j["unit_id"].to_numpy()
    return out


def tract_attributes(tracts: gpd.GeoDataFrame, *, census: pd.DataFrame, income: pd.DataFrame,
                     literacy: pd.DataFrame, n_commercial: pd.Series,
                     poi: pd.DataFrame | None = None) -> gpd.GeoDataFrame:
    """Per-tract ``area_km2``, ``pop_total``, ``n_commercial``, income and
    ``literacy_rate`` (see module docstring), in EPSG:31983.

    ``tracts``: ``cd_setor`` + geometry; ``census``: ``cd_setor,
    populacao_total``; ``income``: ``cd_setor, income_head_mean,
    income_head_median``; ``literacy``: ``cd_setor, alfa_15_mais_sabe,
    alfa_15_mais_nao_sabe``; ``n_commercial``: Series indexed by ``cd_setor``;
    ``poi`` (optional): :func:`poi_counts` output, adds the other POI columns.
    Missing inputs stay missing, except a tract absent from the CNEFE table,
    which has zero addresses of that type."""
    g = tracts[["cd_setor", "geometry"]].to_crs(CRS_METRIC).rename(columns={"cd_setor": "unit_id"})
    g["unit_id"] = g["unit_id"].astype(str)
    g["area_km2"] = g.geometry.area / 1e6

    def _by(df, cols):
        return df.assign(cd_setor=df["cd_setor"].astype(str)).set_index("cd_setor")[cols]

    g["pop_total"] = g["unit_id"].map(_by(census, ["populacao_total"])["populacao_total"])
    g["n_commercial"] = g["unit_id"].map(n_commercial).fillna(0).astype(int)
    poi_cols = [c for c in POI_SPECIES.values() if c != "n_commercial"] if poi is not None else []
    for c in poi_cols:
        g[c] = g["unit_id"].map(poi[c]).fillna(0).astype(int)
    inc = _by(income, ["income_head_mean", "income_head_median"])
    g["income_head_mean"] = g["unit_id"].map(inc["income_head_mean"])
    g["income_head_median"] = g["unit_id"].map(inc["income_head_median"])
    lit = _by(literacy, ["alfa_15_mais_sabe", "alfa_15_mais_nao_sabe"]).apply(pd.to_numeric, errors="coerce")
    sabe = g["unit_id"].map(lit["alfa_15_mais_sabe"])
    nao = g["unit_id"].map(lit["alfa_15_mais_nao_sabe"])
    nao = nao.where(~(sabe.notna() & nao.isna()), 0.0)  # blank "nao sabe" with "sabe" filled -> 0
    tot = sabe + nao                                   # NaN only when "sabe" is missing too
    g["literacy_rate"] = (sabe / tot).where(tot > 0)
    cols = ["unit_id", "area_km2", "pop_total", "n_commercial", *poi_cols, "income_head_mean",
            "income_head_median", "literacy_rate", "geometry"]
    return gpd.GeoDataFrame(g[cols], geometry="geometry", crs=CRS_METRIC).reset_index(drop=True)


#: CNEFE ``COD_ESPECIE`` -> tract column (IBGE CNEFE 2022 dictionary)
POI_SPECIES = {"4": "n_education", "5": "n_health", "6": "n_commercial", "8": "n_religious"}


def poi_counts(cnefe_path: Path, tracts: gpd.GeoDataFrame) -> pd.DataFrame:
    """CNEFE addresses per tract (``unit_id`` index) for each POI use type in
    :data:`POI_SPECIES`, by **point-in-polygon** on the 2022 tract polygons the
    crimes are assigned to.

    A CNEFE row is one use type at one address (IBGE dictionary), so rows are
    deduplicated on (``COD_UNICO_ENDERECO``, ``COD_ESPECIE``), issue #18.
    CNEFE's own ``COD_SETOR`` is not used: for 15,594 of the 54,898 commercial
    addresses it disagrees with the polygon the point lies in (and 540 of its
    codes are not 2022 tract ids at all), so a code join would lose or move
    ~28% of them. ``vw_sector_features`` still uses the code join."""
    import pyogrio

    codes = ", ".join(f"'{c}'" for c in POI_SPECIES)
    pts = pyogrio.read_dataframe(cnefe_path, columns=["COD_UNICO_ENDERECO", "COD_ESPECIE"],
                                 where=f"COD_ESPECIE IN ({codes})")
    pts["COD_ESPECIE"] = pts["COD_ESPECIE"].astype(str)
    pts = pts.drop_duplicates(subset=["COD_UNICO_ENDERECO", "COD_ESPECIE"])
    j = gpd.sjoin(pts.to_crs(tracts.crs), tracts[["unit_id", "geometry"]], how="inner", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    out = pd.crosstab(j["unit_id"], j["COD_ESPECIE"].map(POI_SPECIES))
    return out.reindex(columns=list(POI_SPECIES.values()), fill_value=0)


def commercial_counts(cnefe_path: Path, tracts: gpd.GeoDataFrame) -> pd.Series:
    """CNEFE ``COD_ESPECIE == 6`` addresses per tract (see :func:`poi_counts`)."""
    return poi_counts(cnefe_path, tracts)["n_commercial"].rename("count")


def build_tract_attributes(paths: RawPaths | None = None) -> gpd.GeoDataFrame:
    """:func:`tract_attributes` for every Campinas 2022 tract, from the raw files."""
    from etl import sources

    p = paths or RawPaths()
    tr = sources.extract_census_tracts(cache_dir=p.geobr_cache)
    poly = tr[["cd_setor", "geometry"]].rename(columns={"cd_setor": "unit_id"}).to_crs(CRS_METRIC)
    poi = poi_counts(p.cnefe, poly)
    return tract_attributes(
        tr,
        census=sources.extract_census_2022(path=p.census_basico),
        income=sources.extract_income_2022(path=p.income),
        literacy=sources.extract_literacy(p.painel),
        n_commercial=poi["n_commercial"],
        poi=poi,
    )
