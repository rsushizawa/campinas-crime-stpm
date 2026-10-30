"""Emerging Hot Spot Analysis — **Step 3b: how do hot spots evolve?**

Method
    Getis-Ord Gi* on every time slice of the space-time cube (or a space-time
    Gi* over the whole cube), a Mann–Kendall trend test on each unit's Gi*
    z-score series, and ESRI's rule table mapping (hot/cold history, trend)
    to one of 17 categories ("new", "consecutive", "intensifying",
    "persistent", "diminishing", "sporadic", "oscillating", "historical"
    × hot/cold, or "no pattern").
Reference
    ESRI, "How Emerging Hot Spot Analysis works" (ArcGIS Pro documentation) —
    the category rules in :func:`classify_pattern`.
    Getis & Ord (1992); Ord & Getis (1995) — Gi*.
    Mann (1945); Kendall (1975); Hamed & Rao (1998) — trend (:mod:`crime.esri.trend`).
    Benjamini & Hochberg (1995) — per-slice and per-unit FDR.
ESRI tool mirrored
    "Emerging Hot Spot Analysis" (no claim of numerical parity: our FDR
    families, weights convention and the inflation-only Hamed–Rao variant are
    documented project-specific choices).
Steps
    1. cube → ``unit x period`` counts (optionally ÷ exposure, ``rate=True``);
    2. Gi* per slice (``neighbourhood="space"``) or over a space-time
       neighbourhood (``"spacetime"``) → z, p (FDR per slice), hot/cold masks;
    3. Mann–Kendall on each unit's z series (FDR across units);
    4. :func:`classify_pattern` per unit.
Inputs → Outputs
    Dataset (``events=True``) + weights → :class:`EhsaResult`
    (``gdf`` + category / pct_hot / pct_cold / mk_z / mk_p / mk_p_fdr,
    ``z_matrix`` and hot/cold masks as ``unit x period``).

    from crime import emerging_hotspots
    ehsa = emerging_hotspots(ds, freq="ME", weights="queen")   # or weights="network"

``freq`` is a pandas offset alias ("h", "D", "ME", "YE") or one of two cyclic
bins: "hour" (0-23) and "day_period" (madrugada/manhã/tarde/noite).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from crime.core.metadata import ResultMeta, dataset_meta_of
from crime.data.artifacts import load_gdf, read_layer, register_artifact, save_gdf, write_layer
from crime.esri.cube import space_time_cube
from crime.esri.inference import benjamini_hochberg
from crime.esri.local import gi_star_pseudo_p, gi_star_z
from crime.esri.trend import trend_test
from crime.esri.weights import resolve_weights, space_time_weights, weights_tag

REFERENCE = ("ESRI 'How Emerging Hot Spot Analysis works'; Getis & Ord 1992; "
             "Mann 1945; Kendall 1975; Hamed & Rao 1998; Benjamini & Hochberg 1995")


@dataclass
class EhsaResult:
    gdf: gpd.GeoDataFrame = field(repr=False)     # + category, pct_hot, pct_cold, mk_z, mk_p
    z_matrix: pd.DataFrame = field(repr=False)    # unit x period Gi* z-scores
    hot: pd.DataFrame | None = field(default=None, repr=False)   # unit x period significant-hot mask
    cold: pd.DataFrame | None = field(default=None, repr=False)  # unit x period significant-cold mask
    alpha: float = 0.05
    freq: str = "ME"
    specification: dict = field(default_factory=dict)
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def summary(self) -> None:
        print(f"Emerging Hot Spot Analysis (alpha={self.alpha})")
        print(self.gdf["category"].value_counts().to_string())

    def save(self, path):
        from crime.data.artifacts import save_result
        return save_result(self, path)

    @staticmethod
    def load(path):
        from crime.data.artifacts import load_result
        return load_result(path)


# --------------------------------------------------------------------------- #
#  Gi* over the cube
# --------------------------------------------------------------------------- #
def gi_time_series(wide: pd.DataFrame, w, *, alpha: float = 0.05, fdr: bool = True,
                   permutations: int = 0, seed: int = 42, tie_rule: str = "esda"):
    """Per-time-slice Getis-Ord Gi* over a ``unit x period`` matrix.

    Returns ``(z, p, hot, cold)`` as ``unit x period`` arrays: Gi* z-scores,
    p-values (Benjamini-Hochberg-corrected per slice when ``fdr``), and the hot /
    cold significance masks. ``permutations=0`` uses the analytic normal p-value
    (fast, poor on sparse mostly-zero data); ``permutations>0`` uses a
    **conditional-permutation** pseudo p-value (``esda`` ``p_sim`` — the right
    call for grid / street-segment cubes). ``tie_rule`` other than ``"esda"``
    replaces esda's pseudo p with :func:`crime.esri.permutation.pseudo_p`.
    """
    from esda.getisord import G_Local

    z_cols, p_cols = [], []
    for col in wide.columns:
        values = wide[col].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("Gi* requires finite values")
        if np.ptp(values) == 0:
            z_cols.append(np.zeros(len(values)))
            p_cols.append(np.ones(len(values)))
            continue
        z, p_norm = gi_star_z(values, w)
        z_cols.append(z)
        if permutations and tie_rule != "esda":
            praw = gi_star_pseudo_p(values, w, permutations, seed, tie_rule)
        elif permutations:
            praw = G_Local(wide[col].values, w, star=True, permutations=permutations,
                           keep_simulations=False, seed=seed).p_sim
        else:
            praw = p_norm
        p_cols.append(benjamini_hochberg(praw) if fdr else praw)
    z = np.column_stack(z_cols)
    p = np.column_stack(p_cols)
    return z, p, (z > 0) & (p < alpha), (z < 0) & (p < alpha)


def gi_space_time(wide: pd.DataFrame, w, *, time_step: int = 1, taper: bool = False,
                  alpha: float = 0.05, fdr: bool = True, permutations: int = 0,
                  seed: int = 42, temporal_direction: str = "backward",
                  tie_rule: str = "esda"):
    """Space-**time** Getis-Ord Gi* (ArcGIS EHSA style): the statistic for cell
    ``(i, t)`` borrows strength from unit *i*'s spatial neighbours in the time
    window ``[t - time_step, t]`` by default (or symmetric explicitly), and is standardised against the
    **whole cube** (so slices are comparable and intensification shows up).

    Built as one big Gi* over the stacked ``n·T`` cube with a block weights
    matrix (spatial ``w`` replicated across the time window, ``taper=True`` down-
    weights ``1/(1+|Δt|)``). Returns ``(z, p, hot, cold)`` shaped ``unit x period``.
    """
    from esda.getisord import G_Local
    from libpysal.weights import WSP

    n, T = wide.shape
    W_st = space_time_weights(w, T, time_step=time_step, taper=taper,
                              temporal_direction=temporal_direction)
    x = wide.to_numpy().reshape(-1, order="F")
    if not np.isfinite(x).all():
        raise ValueError("Gi* requires finite values")
    if np.ptp(x) == 0:
        z, p = np.zeros((n, T)), np.ones((n, T))
        return z, p, z.astype(bool), z.astype(bool)
    W_st = WSP(W_st).to_W()
    z_flat, p_norm = gi_star_z(x, W_st)
    z = z_flat.reshape(T, n).T
    if permutations and tie_rule != "esda":
        p_flat = gi_star_pseudo_p(x, W_st, permutations, seed, tie_rule)
    elif permutations:
        p_flat = G_Local(x, W_st, star=True, permutations=permutations,
                         keep_simulations=False, seed=seed).p_sim
    else:
        p_flat = p_norm
    praw = p_flat.reshape(T, n).T
    p = np.column_stack([benjamini_hochberg(praw[:, t]) if fdr else praw[:, t] for t in range(T)])
    return z, p, (z > 0) & (p < alpha), (z < 0) & (p < alpha)


# --------------------------------------------------------------------------- #
#  Emerging Hot Spot Analysis
# --------------------------------------------------------------------------- #
def emerging_hotspots(
    dataset, *, freq: str = "ME", weights="queen", alpha: float = 0.05,
    hot_share: float = 0.9, rate: bool = False, fdr: bool = True,
    trend_fdr: bool | None = None, permutations: int = 0,
    neighbourhood: str = "space", time_step: int = 1, matrix=None,
    temporal_direction: str = "backward", trend_method="hamed_rao",
    trend_max_lag: int = 3, seed: int = 42, tie_rule: str = "esda",
) -> EhsaResult:
    """Gi* per time slice + Mann-Kendall trend -> the standard EHSA categories.

    ``rate=True``  — divide each unit's per-bin count by an exposure before Gi*
      (population/1000 for sector & grid, segment length/1000 for network), so
      low-crime low-exposure areas can register as significantly *cold*. Raw
      counts rarely produce cold spots.
      Units with zero/missing exposure (``rate=True``) are excluded from the Gi*
      computation and its spatial weights, then reinserted with ``category="no data"``
      and NaN trend/percentage fields — they are never silently scored as zero-crime.
    ``fdr``        — Benjamini-Hochberg correction of the per-slice Gi* p-values
      before the hot/cold threshold. **Default True** (thousands of per-bin
      tests). Esri also documents FDR; per-slice BH here is our explicit
      testing family, not a claim of numerical equivalence to Esri.
    ``permutations`` — 0 (default) uses the analytic Gi* p; ``>0`` switches to a
      **conditional-permutation** pseudo p (recommended for sparse grid /
      street-segment cubes where the normal approximation is poor).
    ``tie_rule``   — how permutation ties are counted (:data:`crime.esri.permutation.TIE_RULES`).
      ``"esda"`` (default) keeps esda's p, which treats an all-zero
      neighbourhood as maximally extreme; see :mod:`crime.esri.permutation`.
    ``neighbourhood`` — ``"space"`` (default, Gi* slice by slice) or
      ``"spacetime"`` (:func:`gi_space_time` — each cell borrows strength from
      its spatial neighbours in the requested temporal window, standardised
      against the whole cube). Backward by default; symmetric is retrospective.
    ``trend_fdr``  — also BH-correct the N per-unit Mann-Kendall trend p-values
      (one test per unit). Defaults to ``fdr``; no parity claim for this family.
      ``gdf`` carries both ``mk_p`` (raw) and ``mk_p_fdr`` (used for the label).
    ``trend_method`` — a :func:`~crime.esri.trend.mann_kendall` method name
      ("hamed_rao", "classic", "legacy") or any
      :class:`~crime.core.protocols.TrendTest` callable ``(values) -> (z, p)``.
    ``matrix``     — a precomputed unit x period DataFrame to run EHSA on instead
      of the crime-count cube; its index must match ``dataset``'s unit ids.
      Skips ``space_time_cube`` and ignores ``rate``.
    """
    trend_fdr = fdr if trend_fdr is None else trend_fdr
    if neighbourhood not in {"space", "spacetime"}:
        raise ValueError("neighbourhood must be space or spacetime")
    gdf = dataset.metric().reset_index(drop=True)
    valid = np.ones(len(gdf), dtype=bool)
    if matrix is not None:
        wide = matrix.reindex(gdf[dataset.id_col]).fillna(0.0).astype(float)
    else:
        cube = space_time_cube(dataset, freq=freq)
        wide = cube.wide.reindex(gdf[dataset.id_col]).fillna(0).astype(float)
        if rate:
            exposure = _exposure(dataset, gdf)
            valid = exposure.notna().to_numpy()
            wide = wide.div(exposure.to_numpy(), axis=0)

    gdf_valid = gdf.loc[valid].reset_index(drop=True)
    wide_valid = wide.loc[valid]

    w = resolve_weights(gdf_valid, weights)
    print(f"EHSA — Gi* ({neighbourhood}) on {wide_valid.shape[1]} time slices x {len(gdf_valid)} units"
          f"{' (rate)' if rate else ''}{' + FDR' if fdr else ''}"
          f"{f' + {permutations} perms' if permutations else ''}"
          f"{' + trend-FDR' if trend_fdr else ''}"
          f"{f'  ({(~valid).sum()} units excluded: no exposure data)' if (~valid).any() else ''}")
    _gi = (lambda: gi_space_time(wide_valid, w, time_step=time_step, alpha=alpha, fdr=fdr,
                                 permutations=permutations, temporal_direction=temporal_direction,
                                 seed=seed, tie_rule=tie_rule)) if neighbourhood == "spacetime" \
        else (lambda: gi_time_series(wide_valid, w, alpha=alpha, fdr=fdr, permutations=permutations,
                                     seed=seed, tie_rule=tie_rule))
    z, p, hot, cold = _gi()

    trend = trend_test(trend_method, max_lag=trend_max_lag)
    mk = np.array([trend(row) for row in z])
    mk_p_adj = benjamini_hochberg(mk[:, 1]) if trend_fdr else mk[:, 1]
    categories_valid = [
        classify_pattern(hot[i], cold[i], mk[i, 0], mk_p_adj[i], alpha, hot_share)
        for i in range(len(gdf_valid))
    ]

    out = dataset.gdf.copy()
    out["category"] = "no data"
    out.loc[valid, "category"] = categories_valid
    for col in ("pct_hot", "pct_cold", "mk_z", "mk_p", "mk_p_fdr"):
        out[col] = np.nan
    out.loc[valid, "pct_hot"] = hot.mean(axis=1)
    out.loc[valid, "pct_cold"] = cold.mean(axis=1)
    out.loc[valid, "mk_z"] = mk[:, 0]
    out.loc[valid, "mk_p"] = mk[:, 1]
    out.loc[valid, "mk_p_fdr"] = mk_p_adj

    z_full = pd.DataFrame(np.nan, index=wide.index, columns=wide.columns)
    z_full.loc[wide_valid.index] = z
    hot_full = pd.DataFrame(False, index=wide.index, columns=wide.columns)
    hot_full.loc[wide_valid.index] = hot
    cold_full = pd.DataFrame(False, index=wide.index, columns=wide.columns)
    cold_full.loc[wide_valid.index] = cold
    trend_tag = trend_method if isinstance(trend_method, str) else getattr(trend_method, "__name__", "custom")
    spec = dict(freq=freq, weights=str(weights) if isinstance(weights, str) else "custom",
                neighbourhood=neighbourhood, temporal_direction=temporal_direction,
                time_step=time_step, trend_method=trend_tag, trend_max_lag=trend_max_lag,
                permutations=permutations, fdr=fdr, trend_fdr=trend_fdr, alpha=alpha,
                hot_share=hot_share, rate=rate, seed=seed, tie_rule=tie_rule)
    meta = ResultMeta(method="Emerging Hot Spot Analysis", reference=REFERENCE,
                      params={**spec, "weights": weights_tag(weights), "matrix": matrix is not None},
                      dataset=dataset_meta_of(dataset))
    return EhsaResult(gdf=out, z_matrix=z_full, hot=hot_full, cold=cold_full,
                      alpha=alpha, freq=freq, specification=spec, meta=meta)


def _exposure(dataset, gdf) -> pd.Series:
    """Denominator for rate-based EHSA: population/1000 (sector, grid) or
    segment length/1000 (network). Zero/NaN exposure -> NaN (masked out)."""
    if dataset.unit == "segment" and "length" in gdf:
        exp = gdf["length"] / 1000.0
    elif "pop_total" in gdf:
        exp = gdf["pop_total"] / 1000.0
    else:
        raise ValueError("rate=True needs 'pop_total' (sector/grid) or 'length' (segment).")
    return exp.where(exp > 0)


# --------------------------------------------------------------------------- #
#  ESRI category rules
# --------------------------------------------------------------------------- #
def classify_pattern(hot, cold, mk_z, mk_p, alpha, hot_share) -> str:
    """ESRI EHSA category for one unit from its boolean per-slice ``hot`` /
    ``cold`` significance series and the Mann-Kendall ``(mk_z, mk_p)`` of its
    Gi* z series. Hot rules are tried first, then the mirrored cold rules
    (with the trend sign flipped); otherwise "no pattern".

    ``hot_share`` is the share-of-slices threshold (ESRI uses 90 %) for the
    persistent / intensifying / diminishing / historical categories."""
    for kind, on, off in (("hot", hot, cold), ("cold", cold, hot)):
        label = _classify_side(on, off, mk_z if kind == "hot" else -mk_z, mk_p, alpha, hot_share)
        if label:
            return f"{label} {kind}spot"
    return "no pattern"


def _classify_side(on, off, mk_z, mk_p, alpha, hot_share) -> str | None:
    n = len(on)
    share = on.mean()
    final = bool(on[-1])
    trend_up = mk_p < alpha and mk_z > 0
    trend_down = mk_p < alpha and mk_z < 0
    run = 0
    for v in on[::-1]:
        if not v:
            break
        run += 1

    if share >= hot_share:
        if not final:
            return "historical"
        if trend_up:
            return "intensifying"
        if trend_down:
            return "diminishing"
        return "persistent"
    if final:
        if on[:-1].sum() == 0:
            return "new"
        if run >= 2 and on[: n - run].sum() == 0:
            return "consecutive"
        if off.sum() == 0:
            return "sporadic"
        return "oscillating"
    return None


# --------------------------------------------------------------------------- #
#  persistence (registered with crime.data.artifacts)
# --------------------------------------------------------------------------- #
def _save_ehsa(r: EhsaResult, d: Path) -> dict:
    save_gdf(r.gdf, d / "gdf.parquet")
    write_layer(r.z_matrix, d / "z_matrix.parquet")
    if r.hot is not None:
        write_layer(r.hot, d / "hot.parquet")
    if r.cold is not None:
        write_layer(r.cold, d / "cold.parquet")
    return {"alpha": r.alpha, "freq": r.freq, "specification": r.specification}


def _load_ehsa(d: Path, meta: dict) -> EhsaResult:
    hot_path, cold_path = d / "hot.parquet", d / "cold.parquet"
    rm = meta.get("result_meta")
    return EhsaResult(
        gdf=load_gdf(d / "gdf.parquet"), z_matrix=read_layer(d / "z_matrix.parquet"),
        hot=read_layer(hot_path) if hot_path.exists() else None,
        cold=read_layer(cold_path) if cold_path.exists() else None,
        alpha=meta["alpha"], freq=meta["freq"], specification=meta.get("specification", {}),
        meta=ResultMeta.from_dict(rm) if rm else None,
    )


register_artifact("EhsaResult", _save_ehsa, _load_ehsa, module="crime.esri.ehsa")
