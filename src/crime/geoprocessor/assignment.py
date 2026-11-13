"""Deterministic point-to-polygon assignment, including shared boundaries."""
import geopandas as gpd


def assign_unit(points: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Include boundaries; choose the lowest polygon index for shared edges."""
    if points.crs is None or polygons.crs is None or points.crs != polygons.crs:
        raise ValueError('Points and polygons must have the same declared CRS')
    joined = gpd.sjoin(points, polygons, how='left', predicate='covered_by')
    joined = joined.sort_values('index_right', kind='stable')
    joined = joined[~joined.index.duplicated(keep='first')].reindex(points.index)
    return joined.drop(columns=['index_right'], errors='ignore')
