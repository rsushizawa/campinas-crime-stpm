"""Multiple-testing control for local statistics.

Method
    Benjamini–Hochberg step-up false-discovery-rate adjustment.
Reference
    Benjamini, Y. & Hochberg, Y. (1995). Controlling the false discovery rate:
    a practical and powerful approach to multiple testing. JRSS B 57(1).
ESRI tool mirrored
    The "Apply False Discovery Rate (FDR) Correction" option of Hot Spot
    Analysis / Emerging Hot Spot Analysis (this is BH on our own testing
    family, not a claim of numerical parity with ArcGIS).
Steps
    1. rank the valid p-values; 2. scale p_(i) by n / i; 3. enforce
    monotonicity from the largest rank down; 4. clip to [0, 1].
Inputs → Outputs
    array of p-values (NaN allowed) → adjusted p-values of the same shape.

    from crime import getis_ord_gi, fdr
    res = getis_ord_gi(ds, fdr=False)
    fdr(res, alpha=0.05)          # relabels res.gdf using adjusted p-values
"""
from __future__ import annotations

import numpy as np


def benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """BH step-up adjusted p-values (NaNs preserved, output clipped to [0, 1])."""
    p = np.asarray(p_values, dtype=float)
    adjusted = np.full_like(p, np.nan)
    mask = ~np.isnan(p)
    p_valid = p[mask]
    n = len(p_valid)
    if n == 0:
        return adjusted
    order = np.argsort(p_valid)
    ranks = np.empty_like(order)
    ranks[order] = np.arange(1, n + 1)
    adj = p_valid * n / ranks
    for i in range(n - 2, -1, -1):
        adj[order[i]] = min(adj[order[i]], adj[order[i + 1]])
    adjusted[mask] = np.clip(adj, 0.0, 1.0)
    return adjusted


def adjust(p_values: np.ndarray, fdr: bool) -> np.ndarray:
    """``benjamini_hochberg(p)`` when ``fdr`` else ``p`` unchanged — the
    "adjust, then threshold at alpha" step every local statistic shares."""
    return benjamini_hochberg(p_values) if fdr else p_values


def fdr(result, *, alpha: float = 0.05):
    """Apply BH FDR to a ``LisaResult`` / ``GiStarResult`` in place and return it."""
    result.relabel(benjamini_hochberg(result.gdf["p_value"].values), alpha)
    return result
