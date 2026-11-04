"""Census-tract attributes and CNEFE points of interest (rules used by the units stage).

Every attribute is for 2022, the census year:

``population``
    IBGE 2022 *Agregados por Setores Censitários, Básico*, ``V0001``.
``households``
    Same table, ``V0007`` (occupied private households).
``income_head_mean``, ``income_head_median``
    IBGE 2022 *Agregados por Setores Censitários, Rendimento do Responsável*,
    ``V06004`` (mean) and ``V06006`` (median) nominal monthly income in R$ of
    household heads with income. Tracts IBGE suppresses for privacy stay
    missing; nothing is imputed.
``literate_15_plus``, ``illiterate_15_plus``, ``literacy_rate``
    Residents aged 15 or more who can and cannot read and write
    (``Painel_IBGE_2022.csv``, values checked equal to the IBGE *Alfabetização*
    table) and literate / (literate + illiterate). Where the illiterate count
    is blank but the literate count is filled (499 tracts) the illiterate
    count is set to 0 (author decision, 2026-10-15): non-blank illiterate
    counts are 0 or at least 3, never 1 or 2, so a blank is most likely a
    suppressed small count. If the true value were 2, the literacy rate of
    those tracts would be off by a median of 0.62 points (95th percentile
    2.5, maximum 18.2). Tracts with both counts blank (the same 90 tracts IBGE
    suppresses for income) stay missing.
``n_commercial``, ``n_education``, ``n_health``, ``n_religious``
    CNEFE 2022 addresses of use type (``COD_ESPECIE``) 6, 4, 5 and 8 inside the
    tract polygon. A CNEFE row is one use type at one address, so rows are
    deduplicated on (``COD_UNICO_ENDERECO``, ``COD_ESPECIE``): an address with a
    school and a shop counts once in each type (IC-Crime#18). Use type 6,
    "other purposes", is the commerce proxy.

The point-in-polygon joins use :func:`geopandas.sjoin` (``predicate="within"``),
keeping the first match when a point lies on a shared edge.

References
----------
IBGE (2022). Censo Demográfico 2022, Agregados por Setores Censitários.
IBGE (2022). Cadastro Nacional de Endereços para Fins Estatísticos (CNEFE).
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

#: CNEFE ``COD_ESPECIE`` to tract column (IBGE CNEFE 2022 data dictionary).
POI_SPECIES = {"4": "n_education", "5": "n_health", "6": "n_commercial", "8": "n_religious"}


def tract_attributes(tracts: gpd.GeoDataFrame, *, census: pd.DataFrame, income: pd.DataFrame,
                     literacy: pd.DataFrame, poi: pd.DataFrame) -> pd.DataFrame:
    """Per-tract census attributes and POI counts (see the module docstring).

    Parameters
    ----------
    tracts : GeoDataFrame
        ``cd_setor`` and geometry.
    census : DataFrame
        ``cd_setor``, ``populacao_total``, ``dom_total``
        (:func:`etl.sources.extract_census_2022`).
    income : DataFrame
        ``cd_setor``, ``income_head_mean``, ``income_head_median``
        (:func:`etl.sources.extract_income_2022`).
    literacy : DataFrame
        ``cd_setor``, ``alfa_15_mais_sabe``, ``alfa_15_mais_nao_sabe``
        (:func:`etl.sources.extract_literacy`).
    poi : DataFrame
        :func:`poi_counts` output, indexed by tract id.

    Returns
    -------
    DataFrame
        One row per tract in ``tracts`` order, indexed by ``cd_setor``.
        A tract absent from the CNEFE table has zero addresses of each type;
        every other missing input stays missing.
    """
    ids = tracts["cd_setor"].astype(str)

    def _by(df, cols):
        return df.assign(cd_setor=df["cd_setor"].astype(str)).set_index("cd_setor")[cols]

    c = _by(census, ["populacao_total", "dom_total"])
    out = pd.DataFrame(index=pd.Index(ids, name="cd_setor"))
    out["population"] = ids.map(c["populacao_total"]).to_numpy()
    out["households"] = ids.map(c["dom_total"]).to_numpy()
    inc = _by(income, ["income_head_mean", "income_head_median"])
    out["income_head_mean"] = ids.map(inc["income_head_mean"]).to_numpy()
    out["income_head_median"] = ids.map(inc["income_head_median"]).to_numpy()
    lit = _by(literacy, ["alfa_15_mais_sabe", "alfa_15_mais_nao_sabe"]).apply(pd.to_numeric, errors="coerce")
    sabe = ids.map(lit["alfa_15_mais_sabe"])
    nao = ids.map(lit["alfa_15_mais_nao_sabe"])
    nao = nao.where(~(sabe.notna() & nao.isna()), 0.0)   # blank illiterate with literate filled -> 0
    tot = sabe + nao                                      # missing only when the literate count is missing too
    out["literate_15_plus"] = sabe.to_numpy()
    out["illiterate_15_plus"] = nao.to_numpy()
    out["literacy_rate"] = (sabe / tot).where(tot > 0).to_numpy()
    for col in POI_SPECIES.values():
        out[col] = ids.map(poi[col]).fillna(0).astype(int).to_numpy()
    return out


def cnefe_poi_points(cnefe_path: Path) -> tuple[gpd.GeoDataFrame, int]:
    """CNEFE 2022 address points of the use types in :data:`POI_SPECIES`.

    Read with :func:`pyogrio.read_dataframe` (filtered in the reader with a SQL
    ``WHERE``), deduplicated on (``COD_UNICO_ENDERECO``, ``COD_ESPECIE``), with a
    ``poi`` column naming the type. CRS as stored in the file (WGS84).

    Returns
    -------
    points : GeoDataFrame
    n_duplicates : int
        Rows removed by the deduplication (rule 22).
    """
    import pyogrio

    codes = ", ".join(f"'{c}'" for c in POI_SPECIES)
    pts = pyogrio.read_dataframe(cnefe_path, columns=["COD_UNICO_ENDERECO", "COD_ESPECIE"],
                                 where=f"COD_ESPECIE IN ({codes})")
    pts["COD_ESPECIE"] = pts["COD_ESPECIE"].astype(str)
    n = len(pts)
    pts = pts.drop_duplicates(subset=["COD_UNICO_ENDERECO", "COD_ESPECIE"]).reset_index(drop=True)
    pts["poi"] = pts["COD_ESPECIE"].map(POI_SPECIES)
    return pts, n - len(pts)


def assign_poi_tracts(pts: gpd.GeoDataFrame, tracts: gpd.GeoDataFrame) -> pd.Series:
    """Tract id of each POI point by point-in-polygon on the tract polygons
    (``unit_id`` + geometry, metric CRS); missing outside every tract.

    CNEFE's own ``COD_SETOR`` is not used: for 15,594 of the 54,898 commercial
    addresses it disagrees with the polygon the point lies in, and 540 of its
    codes are not 2022 tract ids, so a code join would lose or move about 28 %
    of them.
    """
    j = gpd.sjoin(pts.to_crs(tracts.crs), tracts[["unit_id", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    return j["unit_id"].reindex(pts.index)


def poi_counts(pts: gpd.GeoDataFrame, tract_of_point: pd.Series) -> pd.DataFrame:
    """POI addresses per tract (index) and use type (columns of :data:`POI_SPECIES`)."""
    inside = tract_of_point.notna()
    out = pd.crosstab(tract_of_point[inside], pts.loc[inside, "COD_ESPECIE"].map(POI_SPECIES))
    return out.reindex(columns=list(POI_SPECIES.values()), fill_value=0)
