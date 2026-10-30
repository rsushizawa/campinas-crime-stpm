"""Non-spatial exploratory data analysis — what is in the data, and when.

Method
    Descriptive statistics per column; event counts by period / weekday /
    hour / crime type; STL seasonal-trend decomposition of the total series.
Reference
    Cleveland, R.B., Cleveland, W.S., McRae, J.E. & Terpenning, I. (1990).
    STL: a seasonal-trend decomposition procedure based on loess. Journal of
    Official Statistics 6(1). Implementation: statsmodels ``STL`` (robust).
Inputs → Outputs
    Dataset → :class:`DescriptiveResult`; Dataset (``events=True``) →
    :class:`TrendResult`.

    from crime import descriptive_stats, temporal_trends
    stats = descriptive_stats(ds)
    trends = temporal_trends(ds, freq="ME")     # needs events=True
    from crime.stats.eda import stl_decompose
    stl_decompose(trends.by_period, period=12)  # observed/trend/seasonal/resid
"""
from dataclasses import dataclass, field

import pandas as pd

from crime.core.metadata import ResultMeta, dataset_meta_of

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class DescriptiveResult:
    table: pd.DataFrame = field(repr=False)
    by_type: pd.DataFrame | None = field(default=None, repr=False)
    by_group: pd.DataFrame | None = field(default=None, repr=False)
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def summary(self) -> None:
        print(self.table.round(3).to_string())
        if self.by_group is not None:
            print("\nCrimes by group:")
            print(self.by_group.to_string())


def descriptive_stats(dataset, *, cols: list[str] | None = None) -> DescriptiveResult:
    cols = cols or dataset.gdf.select_dtypes("number").columns.tolist()
    table = dataset.gdf[cols].describe().T
    by_type = by_group = None
    if dataset.events is not None:
        by_type = dataset.events["crime_slug"].value_counts().rename("n").to_frame()
        by_group = dataset.events["crime_group"].value_counts().rename("n").to_frame()
    return DescriptiveResult(table=table, by_type=by_type, by_group=by_group, meta=ResultMeta(
        method="descriptive statistics", params=dict(cols=list(cols)), dataset=dataset_meta_of(dataset)))


@dataclass
class TrendResult:
    by_period: pd.Series = field(repr=False)                 # total crimes per period
    by_weekday: pd.Series = field(repr=False)
    by_hour: pd.Series = field(repr=False)
    by_slug: pd.DataFrame | None = field(default=None, repr=False)   # period x crime_slug counts
    stl: dict | None = field(default=None, repr=False)       # observed/trend/seasonal/resid
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def summary(self) -> None:
        print(
            f"{self.by_period.sum()} events over {len(self.by_period)} periods "
            f"({self.by_period.index.min():%Y-%m} … {self.by_period.index.max():%Y-%m})"
        )
        if self.by_slug is not None:
            print(f"{self.by_slug.shape[1]} crime types tracked")
        if self.stl is not None:
            amp = self.stl["seasonal"].abs().mean()
            slope = (self.stl["trend"].iloc[-1] - self.stl["trend"].iloc[0]) / len(self.stl["trend"])
            print(f"STL: mean |seasonal| ≈ {amp:.0f}/period, trend slope ≈ {slope:+.1f}/period")


def temporal_trends(dataset, *, freq: str = "ME") -> TrendResult:
    if dataset.events is None:
        raise ValueError("Dataset has no events — load it with events=True.")
    ev = dataset.events.dropna(subset=["data_ocorrencia"]).copy()
    dates = pd.to_datetime(ev["data_ocorrencia"])
    period = dates.dt.to_period(freq.rstrip("SE") or "M")

    by_period = period.value_counts().sort_index().rename("crimes")
    by_period.index = by_period.index.to_timestamp()

    by_slug = None
    if "crime_slug" in ev.columns and ev["crime_slug"].notna().any():
        by_slug = (
            pd.crosstab(period, ev["crime_slug"])
            .sort_index()
        )
        by_slug.index = by_slug.index.to_timestamp()
        by_slug = by_slug[by_slug.sum().sort_values(ascending=False).index]  # busiest first

    by_weekday = (
        dates.dt.dayofweek.value_counts().sort_index()
        .rename(index=dict(enumerate(_WEEKDAYS))).rename("crimes")
    )
    hours = pd.to_datetime(ev["hora_ocorrencia"], format="%H:%M:%S", errors="coerce").dt.hour
    by_hour = hours.dropna().astype(int).value_counts().sort_index().rename("crimes")

    stl = _stl(by_period, freq)
    return TrendResult(by_period=by_period, by_weekday=by_weekday, by_hour=by_hour,
                       by_slug=by_slug, stl=stl, meta=ResultMeta(
                           method="temporal trends + STL", reference="Cleveland et al. 1990 (STL)",
                           params=dict(freq=freq), dataset=dataset_meta_of(dataset)))


def stl_decompose(series: pd.Series, *, period: int = 12, robust: bool = True) -> pd.DataFrame:
    """STL decomposition (Cleveland et al. 1990) of a regularly spaced series —
    statsmodels ``STL(series, period=period, robust=robust)`` with its default
    loess windows. ``robust=True`` down-weights outlying months in the loess
    fits. Returns columns ``observed / trend / seasonal / resid`` on the
    series' index (``observed = trend + seasonal + resid``). Needs at least two
    full cycles; NaNs are not allowed (fill them first)."""
    from statsmodels.tsa.seasonal import STL

    s = pd.Series(series, dtype=float)
    if len(s) < 2 * period:
        raise ValueError(f"STL needs >= 2 cycles ({2 * period} points), got {len(s)}")
    if s.isna().any():
        raise ValueError("series has NaNs — fill them before decomposing")
    res = STL(s.to_numpy(), period=period, robust=robust).fit()
    return pd.DataFrame({"observed": s.to_numpy(), "trend": res.trend, "seasonal": res.seasonal,
                         "resid": res.resid}, index=s.index)


def _stl(series: pd.Series, freq: str) -> dict | None:
    """STL seasonal-trend decomposition of the total series, when there are at
    least two full seasonal cycles (12 for monthly, 4 for quarterly)."""
    key = freq.rstrip("SE") or "M"
    period = {"M": 12, "Q": 4, "W": 52}.get(key)
    if period is None or series.empty:
        return None
    # by_period is indexed by period *start* and omits periods with no events:
    # those had zero events, so reindex to the full range with 0 (interpolating
    # would invent events in an empty month).
    full = pd.date_range(series.index.min(), series.index.max(),
                         freq={"M": "MS", "Q": "QS", "W": "W-MON"}[key])
    s = series.reindex(full, fill_value=0)
    if len(s) < 2 * period:
        return None
    try:
        return stl_decompose(s, period=period, robust=True).to_dict("series")
    except Exception:  # noqa: BLE001 — decomposition is a nice-to-have
        return None
