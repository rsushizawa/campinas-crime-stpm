"""Shared result vocabulary.

Every local-statistic result (Gi*, LISA, space-time LISA, EHSA) labels units;
comparisons between them reduce labels to a common **family** —
``"hotspot"`` / ``"coldspot"`` / ``"no pattern"`` — and measure overlap with a
per-family Jaccard index. Those two helpers live here so every comparison
(support sensitivity, prediction agreement) uses the same definition.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from crime.core.metadata import ResultMeta

FAMILIES = ("hotspot", "coldspot", "no pattern")


@runtime_checkable
class LocalStatResult(Protocol):
    """What Gi* / LISA / EHSA results have in common."""

    gdf: pd.DataFrame          # one row per unit, with a ``label``/``category`` column
    alpha: float
    meta: ResultMeta | None

    def summary(self) -> None: ...


def family(labels) -> np.ndarray:
    """Collapse detailed labels ("new hotspot", "HH"-free Gi* labels, EHSA
    categories ...) to ``hotspot`` / ``coldspot`` / ``no pattern`` by substring."""
    s = pd.Series(labels).astype(str)
    return np.select([s.str.contains("hotspot"), s.str.contains("coldspot")],
                     ["hotspot", "coldspot"], default="no pattern")


def jaccard(a, b, value: str) -> float:
    """|A ∩ B| / |A ∪ B| for the units labelled ``value`` in ``a`` and ``b``
    (NaN when neither has any)."""
    A, B = (np.asarray(a) == value), (np.asarray(b) == value)
    union = int((A | B).sum())
    return float((A & B).sum() / union) if union else float("nan")
