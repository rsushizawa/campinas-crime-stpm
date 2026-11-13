"""Spatial weights and global Moran inference (notebook 04 defaults)."""
from dataclasses import dataclass

import esda
import numpy as np
from libpysal.weights import lag_spatial

from crime.geoprocessor.weights import build_w as build_w
from crime.geoprocessor.weights import build_weights as build_weights


@dataclass(frozen=True)
class MoranResult:
    n: int
    events: int
    I: float
    EI: float
    z_norm: float
    p_norm_two_sided: float
    z_sim: float
    p_sim: float


def global_moran(y, w, permutations=999, seed=20221):
    """Row-standardised Moran with the notebook's per-run NumPy seed reset."""
    y = np.asarray(y, dtype=float)
    np.random.seed(seed)
    mi = esda.Moran(y, w, transformation="r", permutations=permutations)
    return MoranResult(len(y), int(y.sum()), mi.I, mi.EI, mi.z_norm,
                       mi.p_norm, mi.z_sim, mi.p_sim)


def moran_scatter(y, w):
    """Population-standardised counts and their row-standardised spatial lag."""
    y = np.asarray(y, dtype=float)
    w.transform = "r"
    z = (y - y.mean()) / y.std()
    return z, lag_spatial(w, z)
