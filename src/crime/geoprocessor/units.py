"""Stage 3, units: census tracts, their 2022 attributes, POIs, and the tract of each bulletin.

Treatment rules 16 to 22. The stage runs as::

    from crime.geoprocessor.units import UnitsInput, units_pipeline
    result = units_pipeline().run(UnitsInput(bulletins=clean_result.kept))

``result.kept`` is a :class:`UnitsOutput` with the three tables the warehouse
is loaded from: ``tracts`` (one row per 2022 tract with its attributes and
polygon), ``poi`` (one row per point of interest) and ``bulletins`` (the
clean-stage table plus ``census_tract_id`` and a projected point).

Geometry is stored in EPSG:31983 (SIRGAS 2000 / UTM zone 23S, metres), the
CRS every area, distance and spatial-weights computation uses. The published
latitude and longitude stay on the bulletin row as reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import geopandas as gpd
import pandas as pd

from crime.config import (
    CENSUS_BASICO_ZIP,
    CENSUS_INCOME_ZIP,
    CNEFE_JSON,
    CRS_METRIC,
    CRS_WGS84,
    GEOBR_CACHE,
    PAINEL_CSV,
)
from crime.generator.pipeline import Pipeline, ReportLine, StageFailed, StepResult, make_rejects, no_rejects
from crime.geoprocessor import census
from crime.geoprocessor.assignment import assign_unit
from crime.importer import sources
from crime.importer.cleaning import BULLETIN_KEY

STAGE = "units"


@dataclass
class UnitsInput:
    """Clean-stage bulletins plus the paths of the unit sources."""

    bulletins: pd.DataFrame
    geobr_cache: object = GEOBR_CACHE
    census_basico: object = CENSUS_BASICO_ZIP
    census_income: object = CENSUS_INCOME_ZIP
    painel: object = PAINEL_CSV
    cnefe: object = CNEFE_JSON


@dataclass
class UnitsOutput:
    """The three tables the load stage writes (see the module docstring)."""

    bulletins: pd.DataFrame
    tracts: gpd.GeoDataFrame | None = None
    tracts_wgs84: gpd.GeoDataFrame | None = None
    poi: gpd.GeoDataFrame | None = None
    sources: UnitsInput | None = field(default=None, repr=False)


class LoadTracts:
    """Rule 18 (fail): the 2022 tract polygons must be valid, unique and in the expected CRS.

    Polygons come from IBGE's 2022 tract mesh through ``geobr``
    (:func:`crime.importer.sources.extract_census_tracts`). An invalid polygon or a
    repeated tract id means the input changed, so the run stops; nothing is
    repaired with ``make_valid``.
    """

    rule, action = "18", "fail"

    def run(self, inp: UnitsInput) -> StepResult:
        tr = sources.extract_census_tracts(cache_dir=inp.geobr_cache)
        problems = []
        if tr.crs is None or tr.crs.to_epsg() != 4326:
            problems.append(f"CRS is {tr.crs}, expected EPSG:4326")
        if tr["cd_setor"].duplicated().any():
            problems.append(f"{int(tr['cd_setor'].duplicated().sum())} repeated tract ids")
        metric = tr[["cd_setor", "nm_distrito", "situacao", "geometry"]].to_crs(CRS_METRIC)
        invalid = ~metric.geometry.is_valid
        if invalid.any():
            problems.append(f"{int(invalid.sum())} invalid polygons: {metric.loc[invalid, 'cd_setor'].tolist()[:10]}")
        if problems:
            raise StageFailed("rule 18, tract polygons:\n  " + "\n  ".join(problems))
        metric = metric.rename(columns={"cd_setor": "census_tract_id", "nm_distrito": "district",
                                        "situacao": "situation"})
        metric["census_tract_id"] = metric["census_tract_id"].astype(str)
        metric["area_km2"] = metric.geometry.area / 1e6
        metric = metric.sort_values("census_tract_id", kind="mergesort").reset_index(drop=True)
        out = UnitsOutput(bulletins=inp.bulletins, tracts=metric, tracts_wgs84=tr, sources=inp)
        n = len(metric)
        return StepResult(out, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, n, n, 0,
            f"{n:,} tracts, all valid, ids unique; {int((metric.geom_type == 'MultiPolygon').sum())} multipolygon")])


class PointsOfInterest:
    """Rule 22 (fix): CNEFE POI addresses, deduplicated on address and use type.

    Each POI point gets its tract by point-in-polygon
    (:func:`crime.geoprocessor.census.assign_poi_tracts`); points outside every tract keep a
    missing tract and are not counted in any tract. The removed duplicates go
    to ``rejects``.
    """

    rule, action = "22", "fix"

    def run(self, u: UnitsOutput) -> StepResult:
        import pyogrio

        pts, n_dup = census.cnefe_poi_points(u.sources.cnefe)
        polys = u.tracts[["census_tract_id", "geometry"]].rename(columns={"census_tract_id": "unit_id"})
        tract = census.assign_poi_tracts(pts, polys)
        poi = gpd.GeoDataFrame({
            "address_id": pts["COD_UNICO_ENDERECO"].astype(str),
            "poi_type_code": pts["COD_ESPECIE"].astype(int),
            "poi_type": pts["poi"].str.removeprefix("n_"),
            "census_tract_id": tract.astype("string"),
        }, geometry=pts.geometry.to_crs(CRS_METRIC).values, crs=CRS_METRIC)
        rejects = no_rejects()
        if n_dup:
            codes = ", ".join(f"'{c}'" for c in census.POI_SPECIES)
            raw = pyogrio.read_dataframe(u.sources.cnefe, columns=["COD_UNICO_ENDERECO", "COD_ESPECIE"],
                                         where=f"COD_ESPECIE IN ({codes})", read_geometry=False)
            dup = raw[raw.duplicated(subset=["COD_UNICO_ENDERECO", "COD_ESPECIE"])]
            rejects = make_rejects(dup, stage=STAGE, step=type(self).__name__, rule=self.rule,
                                   reason="repeated address and use type",
                                   key=dup["COD_UNICO_ENDERECO"].astype(str) + "/" + dup["COD_ESPECIE"].astype(str))
        outside = int(tract.isna().sum())
        return StepResult(replace(u, poi=poi), rejects, [ReportLine(
            type(self).__name__, self.rule, self.action, len(pts) + n_dup, len(poi), n_dup,
            f"{n_dup:,} duplicate address-type rows removed; {outside:,} POIs outside every tract")])


class CensusAttributes:
    """Rules 20 and 21 (report): attach the 2022 census attributes to every tract.

    Missing attributes stay missing (rule 20) and tracts with no residents
    keep their crime counts (rule 21; the paper analyses counts, not rates).
    Both are counted. Attribute definitions: :mod:`crime.geoprocessor.census`.
    """

    rule, action = "20-21", "report"

    def run(self, u: UnitsOutput) -> StepResult:
        s = u.sources
        poi = census.poi_counts(u.poi.assign(COD_ESPECIE=u.poi["poi_type_code"].astype(str)),
                                u.poi["census_tract_id"])
        attrs = census.tract_attributes(
            u.tracts.rename(columns={"census_tract_id": "cd_setor"}),
            census=sources.extract_census_2022(path=s.census_basico),
            income=sources.extract_income_2022(path=s.census_income),
            literacy=sources.extract_literacy(s.painel),
            poi=poi,
        )
        tracts = u.tracts.join(attrs.reset_index(drop=True))
        cols = ["census_tract_id", "district", "situation", "area_km2", *attrs.columns, "geometry"]
        tracts = gpd.GeoDataFrame(tracts[cols], geometry="geometry", crs=CRS_METRIC)
        n = len(tracts)
        miss = {c: int(tracts[c].isna().sum()) for c in ("population", "income_head_mean", "literacy_rate")}
        zero_pop = int(tracts["population"].fillna(0).eq(0).sum())
        return StepResult(replace(u, tracts=tracts), no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, n, n, max(miss.values()) + zero_pop,
            "missing: " + ", ".join(f"{k} {v}" for k, v in miss.items()) + f"; population 0 or missing: {zero_pop}")])


class AssignTract:
    """Rules 16 and 17 (fix, exclude): the 2022 tract each geocoded bulletin lies in.

    Point-in-polygon with :func:`geopandas.sjoin` (``predicate="covered_by"``) on
    the WGS84 tract polygons, as published; a point on a shared edge takes the
    lowest polygon index (rule 16). A bulletin outside every tract keeps a missing
    ``census_tract_id`` (rule 17): it stays in the monthly series and leaves the
    spatial event set. Bulletins without a usable coordinate also have no tract.
    """

    rule, action = "16-17", "exclude"

    def run(self, u: UnitsOutput) -> StepResult:
        b = u.bulletins.copy()
        ok = b["LATITUDE"].notna() & b["LONGITUDE"].notna()
        pts = gpd.GeoDataFrame(b.loc[ok, BULLETIN_KEY],
                               geometry=gpd.points_from_xy(b.loc[ok, "LONGITUDE"], b.loc[ok, "LATITUDE"]),
                               crs=CRS_WGS84)
        joined = assign_unit(pts, u.tracts_wgs84[["cd_setor", "geometry"]])
        b["census_tract_id"] = joined["cd_setor"].reindex(b.index).astype("string")
        geom = gpd.GeoSeries(gpd.points_from_xy(b["LONGITUDE"], b["LATITUDE"]), index=b.index, crs=CRS_WGS84)
        b = gpd.GeoDataFrame(b, geometry=geom.to_crs(CRS_METRIC), crs=CRS_METRIC)
        b.loc[~ok, "geometry"] = None
        outside = int((ok & b["census_tract_id"].isna()).sum())
        return StepResult(replace(u, bulletins=b), no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, len(b), len(b), outside,
            f"{int(b['census_tract_id'].notna().sum()):,} in a tract; {outside} geocoded outside every tract; "
            f"{int((~ok).sum()):,} without a usable coordinate")])


class TractIslands:
    """Rule 19 (report): tracts with no queen-contiguity neighbour.

    Queen contiguity from :class:`libpysal.weights.Queen`. Islands have no
    neighbourhood, so the local statistics report them as "no data"; the
    notebooks handle them, the ETL only counts them.
    """

    rule, action = "19", "report"

    def run(self, u: UnitsOutput) -> StepResult:
        from libpysal.weights import Queen

        w = Queen.from_dataframe(u.tracts, ids="census_tract_id", use_index=False, silence_warnings=True)
        n = len(u.tracts)
        return StepResult(u, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, n, n, len(w.islands),
            f"{len(w.islands)} island tract(s): {', '.join(map(str, w.islands)) or 'none'}")])


def units_pipeline() -> Pipeline:
    """Rules 16 to 22, in the order they apply."""
    return Pipeline(STAGE, [LoadTracts(), PointsOfInterest(), CensusAttributes(), AssignTract(), TractIslands()])
