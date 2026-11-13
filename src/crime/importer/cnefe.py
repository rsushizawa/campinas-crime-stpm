"""Read CNEFE address use types and apply documented duplicate removal."""
from pathlib import Path

import geopandas as gpd

POI_SPECIES = {"4": "n_education", "5": "n_health", "6": "n_commercial", "8": "n_religious"}


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
