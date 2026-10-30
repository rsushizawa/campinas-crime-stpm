"""Knox space–time interaction test and the near-repeat table.

Method
    Count the pairs of events that are close in space (Euclidean distance in
    the metric CRS, EPSG:31983 metres) *and* in time (absolute difference in
    days). Under the null of no space–time interaction the times are
    exchangeable over the locations, so the reference distribution is built by
    permuting the event times over the fixed locations and recounting
    (Monte Carlo); the pseudo p-value is one-sided (excess of close pairs),
    ``p = (r + 1) / (P + 1)`` with ``r`` = permutations whose count is >= the
    observed one. ``ratio = observed / expected`` with ``expected`` the mean of
    the permutation counts — the Knox ratio of the near-repeat literature.
Reference
    Knox, E.G. (1964). The detection of space-time interactions. Journal of
    the Royal Statistical Society C (Applied Statistics) 13(1).
    Mantel, N. (1967). The detection of disease clustering and a generalized
    regression approach. Cancer Research 27(2) — the permutation test of which
    Knox's statistic is a special case.
    Johnson, S.D. & Bowers, K.J. (2004). The stability of space-time clusters
    of burglary. British Journal of Criminology 44(1) — Knox + Monte Carlo
    permutation applied to burglary.
    Ratcliffe, J.H. (2009). Near Repeat Calculator (v1.3). Temple University /
    National Institute of Justice — the band-matrix layout of :func:`knox_table`.
Caveats
    The test detects interaction relative to the observed spatial and temporal
    marginals; a population that shifts in space over the study period can
    produce apparent interaction (Kulldorff, M. & Hjalmars, U. 1999, The Knox
    method and other tests for space-time interaction, Biometrics 55(2)).
    Duplicate records of one incident inflate same-place/same-day pairs: dedupe
    upstream.
Algorithm (project choice, for 10^5 events)
    ``scipy.spatial.cKDTree.query_pairs`` at the largest space band gives the
    candidate pairs once; their distances (hence space bands) are fixed. Each
    permutation shuffles the time array and recomputes |Δt| on those pairs
    only (whole-day times as int16, histogrammed per space band), so the cost
    is O(P · pairs). Memory is ~12-16 bytes per candidate pair;
    use ``sample=`` for very large inputs or long space bands.
Inputs → Outputs
    events (``x``/``y`` metres in EPSG:31983, or a GeoDataFrame) + a date
    column → :class:`KnoxResult` / near-repeat DataFrame.

    from crime.stats.knox import knox_test, knox_table
    kx = knox_test(ev, space_m=200, time_days=14)
    nr = knox_table(ev, space_bands_m=[100, 200, 300, 400], time_bands_days=[7, 14, 21, 28])
    nr["ratio"]                       # rows = space bands, cols = time bands
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from crime.core.config import CRS_METRIC
from crime.core.metadata import ResultMeta

__all__ = ["KnoxResult", "knox_test", "knox_table"]


# --------------------------------------------------------------------------- #
#  preparation
# --------------------------------------------------------------------------- #
def _prepare(events, x: str, y: str, t: str, sample: int | None, seed: int):
    """``(xy (n, 2) metres, days (n,))`` with rows lacking a coordinate or a time
    dropped. A GeoDataFrame without ``x``/``y`` columns is projected to
    EPSG:31983 and its point coordinates used."""
    df = events
    if (x not in df.columns or y not in df.columns) and hasattr(df, "geometry"):
        g = df.to_crs(CRS_METRIC) if df.crs is not None else df
        df = pd.DataFrame({x: g.geometry.x.to_numpy(), y: g.geometry.y.to_numpy(),
                           t: df[t].to_numpy()}, index=df.index)
    df = df[[x, y, t]].dropna()
    if sample is not None and sample < len(df):
        df = df.sample(n=sample, random_state=seed)
    tt = df[t]
    if pd.api.types.is_datetime64_any_dtype(tt) or tt.dtype == object:
        tt = pd.to_datetime(tt)
        days = ((tt - tt.min()) / pd.Timedelta(days=1)).to_numpy(dtype=float)
    else:
        days = tt.to_numpy(dtype=float)                 # already in days
    if len(days) and np.allclose(days, np.round(days)):
        days = np.round(days - days.min())               # whole days: compact ints, cheaper gather
        days = days.astype(np.int16 if days.max() < 2 ** 15 else np.int32)
    return df[[x, y]].to_numpy(dtype=float), days


def _pairs(xy: np.ndarray, r: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``i, j`` (int32) and distance of every pair with distance <= r."""
    from scipy.spatial import cKDTree

    p = cKDTree(xy).query_pairs(r=r, output_type="ndarray")
    i = p[:, 0].astype(np.int32)
    j = p[:, 1].astype(np.int32)
    del p
    d = np.hypot(*(xy[i] - xy[j]).T)
    return i, j, d


def _band_index(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Band k = (edges[k-1], edges[k]] (band 0 = [0, edges[0]]); values above the
    last edge get ``len(edges)``."""
    return np.searchsorted(edges, values, side="left")


def _check_edges(edges, name: str) -> np.ndarray:
    e = np.asarray(edges, dtype=float)
    if e.ndim != 1 or len(e) == 0 or (e <= 0).any() or (np.diff(e) <= 0).any():
        raise ValueError(f"{name} must be a non-empty, strictly increasing list of positive upper limits")
    return e


def _knox_counts(xy, days, se: np.ndarray, te: np.ndarray, permutations: int, seed: int):
    """Observed ``(ns, nt)`` band counts, the ``(P, ns, nt)`` permutation counts
    and the number of candidate pairs (distance <= ``se[-1]``).

    Pairs are sorted by space band once, so each band is a contiguous slice.
    With whole-day times, |Δt| is capped at ``floor(te[-1]) + 1`` ("beyond")
    and histogrammed per slice, then mapped to time bands through a lookup
    table; otherwise ``searchsorted`` on the float |Δt|."""
    i, j, d = _pairs(xy, float(se[-1]))
    sb = _band_index(d, se)
    del d
    order = np.argsort(sb, kind="stable")
    i, j = i[order], j[order]
    bounds = np.searchsorted(sb[order], np.arange(len(se) + 1), side="left")
    del sb, order
    ns, nt = len(se), len(te)
    integer = np.issubdtype(days.dtype, np.integer)
    if integer:
        cap = int(np.floor(te[-1])) + 1
        lut = _band_index(np.arange(cap + 1, dtype=float), te)       # |Δt| value -> time band
    a = np.empty(len(i), dtype=days.dtype)
    b = np.empty(len(i), dtype=days.dtype)

    def counts(tv: np.ndarray) -> np.ndarray:
        np.take(tv, i, out=a)
        np.take(tv, j, out=b)
        np.subtract(a, b, out=a)
        np.abs(a, out=a)
        out = np.zeros((ns, nt), dtype=np.int64)
        if integer:
            np.minimum(a, cap, out=a)
        for k in range(ns):
            seg = a[bounds[k]:bounds[k + 1]]
            if integer:
                h = np.bincount(seg, minlength=cap + 1)
                out[k] = np.bincount(lut, weights=h, minlength=nt + 1)[:nt]
            else:
                out[k] = np.bincount(_band_index(seg, te), minlength=nt + 1)[:nt]
        return out

    obs = counts(days)
    rng = np.random.default_rng(seed)
    sim = np.empty((permutations, ns, nt), dtype=np.int64)
    for p in range(permutations):
        sim[p] = counts(rng.permutation(days))
    return obs, sim, len(i)


def _summarise(obs: np.ndarray, sim: np.ndarray):
    """``expected`` (mean), ``ratio`` (obs / expected) and the one-sided pseudo p."""
    P = len(sim)
    expected = sim.mean(axis=0) if P else np.full(obs.shape, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(expected > 0, obs / expected, np.nan)
    p = ((sim >= obs).sum(axis=0) + 1) / (P + 1)
    return expected, ratio, p


# --------------------------------------------------------------------------- #
#  single threshold
# --------------------------------------------------------------------------- #
@dataclass
class KnoxResult:
    observed: int
    expected: float                   # mean permutation count
    ratio: float                      # observed / expected
    p_value: float                    # (r + 1) / (P + 1), one-sided (excess)
    space_m: float = 0.0
    time_days: float = 0.0
    n_events: int = 0
    n_space_pairs: int = 0            # pairs within space_m (any time gap)
    permutations: int = 999
    sim: np.ndarray | None = field(default=None, repr=False)
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def summary(self) -> None:
        print(f"Knox — {self.n_events} events, <= {self.space_m:g} m and <= {self.time_days:g} days: "
              f"observed {self.observed}, expected {self.expected:.1f}, ratio {self.ratio:.3f}, "
              f"p = {self.p_value:.4f} ({self.permutations} permutations)")


def knox_test(
    events,
    *,
    space_m: float,
    time_days: float,
    permutations: int = 999,
    seed: int = 42,
    x: str = "x",
    y: str = "y",
    t: str = "date",
    sample: int | None = None,
) -> KnoxResult:
    """Knox (1964) count of pairs with distance <= ``space_m`` and |Δt| <=
    ``time_days`` (both closed), with Monte Carlo significance from
    ``permutations`` shuffles of the event times over the locations. ``t`` is a
    datetime column (or numeric days). ``sample`` draws that many events at
    random (seeded) first."""
    xy, days = _prepare(events, x, y, t, sample, seed)
    obs, sim, n_pairs = _knox_counts(xy, days, _check_edges([space_m], "space_m"),
                                     _check_edges([time_days], "time_days"), permutations, seed)
    expected, ratio, p = (float(v[0, 0]) for v in _summarise(obs, sim))
    observed = int(obs[0, 0])
    return KnoxResult(
        observed=observed, expected=expected, ratio=ratio, p_value=p,
        space_m=float(space_m), time_days=float(time_days), n_events=len(days),
        n_space_pairs=n_pairs, permutations=permutations, sim=sim[:, 0, 0],
        meta=ResultMeta(method="Knox space-time interaction test (Monte Carlo)",
                        reference="Knox 1964; Mantel 1967; Johnson & Bowers 2004",
                        params=dict(space_m=space_m, time_days=time_days, permutations=permutations,
                                    seed=seed, sample=sample)))


# --------------------------------------------------------------------------- #
#  near-repeat band table
# --------------------------------------------------------------------------- #
def _label(edges: np.ndarray, unit: str) -> list[str]:
    out = []
    for k, hi in enumerate(edges):
        out.append(f"[0, {hi:g}] {unit}" if k == 0 else f"({edges[k - 1]:g}, {hi:g}] {unit}")
    return out


def knox_table(
    events,
    *,
    space_bands_m: list[float],
    time_bands_days: list[float],
    permutations: int = 999,
    seed: int = 42,
    x: str = "x",
    y: str = "y",
    t: str = "date",
    sample: int | None = None,
) -> pd.DataFrame:
    """Near-repeat matrix (rows = space bands, columns = time bands), one Knox
    test per cell sharing the same permutations.

    Bands are given by their **upper limits** and are half-open on the left:
    band k is ``(b[k-1], b[k]]`` and the first band is ``[0, b[0]]`` (so pairs
    at the same place / on the same day fall in the first band). Pairs beyond
    the last space or time limit are not tabulated. Unlike Ratcliffe's Near
    Repeat Calculator there is no "beyond" row/column, and bands need not be
    equal-width.

    Returns a DataFrame with a two-level column index ``(stat, time band)``,
    ``stat`` in ``observed / expected / ratio / p``: ``df["ratio"]`` is the
    familiar Knox-ratio matrix, ``df["p"]`` the one-sided ``(r+1)/(P+1)``
    pseudo p (no multiple-testing adjustment across cells).
    """
    se = _check_edges(space_bands_m, "space_bands_m")
    te = _check_edges(time_bands_days, "time_bands_days")
    xy, days = _prepare(events, x, y, t, sample, seed)
    obs, sim, n_pairs = _knox_counts(xy, days, se, te, permutations, seed)
    expected, ratio, p = _summarise(obs, sim)

    rows, cols = _label(se, "m"), _label(te, "days")
    out = pd.concat({name: pd.DataFrame(v, index=rows, columns=cols)
                     for name, v in (("observed", obs), ("expected", expected),
                                     ("ratio", ratio), ("p", p))}, axis=1)
    out.index.name = "space band"
    out.columns.names = ["stat", "time band"]
    out.attrs.update(n_events=len(days), n_space_pairs=n_pairs, permutations=permutations,
                     seed=seed, sample=sample, bands="(lo, hi], first band [0, hi]")
    return out
