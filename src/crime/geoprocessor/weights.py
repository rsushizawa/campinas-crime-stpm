"""Notebook-compatible contiguity and centroid KNN weights and island masks."""
import geopandas as gpd
from libpysal.weights import KNN, Queen, Rook, w_subset


def build_w(u, kind, k_nn=5):
    if kind == "queen":
        w = Queen.from_dataframe(u, ids="unit_id", use_index=False)
    elif kind == "rook":
        w = Rook.from_dataframe(u, ids="unit_id", use_index=False)
    else:
        cent = gpd.GeoDataFrame({"unit_id": u["unit_id"].to_numpy()}, geometry=u.geometry.centroid.to_numpy(), crs=u.crs)
        w = KNN.from_dataframe(cent, k=k_nn, ids="unit_id")
    assert list(w.id_order) == list(u["unit_id"])
    return w



def build_weights(u, kind, k_nn=5):
    """Return weights, the input-row keep mask and the original island IDs."""
    w = build_w(u, kind, k_nn)
    islands = list(w.islands)
    mask = ~u["unit_id"].isin(islands).to_numpy()
    if islands:
        w = w_subset(w, list(u["unit_id"][mask]))
    return w, mask, islands


