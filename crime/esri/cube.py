"""Build the space-time cube — **Step 3a: bin events into unit x time.**

Method
    Count events per (spatial unit, time bin); every unit and every bin in the
    study window is present, empty cells are 0.
Reference
    ESRI "Create Space Time Cube By Aggregating Points" (the aggregation, not
    its netCDF format or its location-template interpolation).
Steps
    1. keep events with a unit and a date inside ``dataset.years``;
    2. assign each to a bin (pandas offset alias, "hour" 0-23 or "day_period");
    3. pivot to ``unit x period`` and reindex onto *all* units and *all* bins
       of the window (boundary months with no events are kept).
Inputs → Outputs
    Dataset (``events=True``) → :class:`~crime.core.cube.CubeResult`
    (``.wide`` count layer, ``.panel`` long form, header from the dataset).

    from crime import space_time_cube
    cube = space_time_cube(ds, freq="ME")
"""
from __future__ import annotations

import pandas as pd

from crime.core.cube import CubeResult

DAY_PERIODS = ("De madrugada", "Pela manhã", "A tarde", "A noite")


def space_time_cube(dataset, *, freq: str = "ME", date_col: str = "data_ocorrencia") -> CubeResult:
    if dataset.events is None:
        raise ValueError("Dataset has no events — load it with events=True.")
    df = dataset.events.dropna(subset=["unit_id", date_col]).copy()
    df[date_col] = pd.to_datetime(df[date_col])
    if dataset.years is not None:
        start, end = (pd.Timestamp(dataset.years[0], 1, 1),
                      pd.Timestamp(dataset.years[1] + 1, 1, 1))
        df = df[df[date_col].between(start, end, inclusive="left")]

    if freq == "hour":
        df = df.dropna(subset=["hora_ocorrencia"])
        df["period"] = df["hora_ocorrencia"].astype(str).str.slice(0, 2).astype(int)
        key, all_periods = "period", list(range(24))
    elif freq == "day_period":
        df["period"] = df["periodo"]
        df = df[df["period"].isin(DAY_PERIODS)]
        key, all_periods = "period", list(DAY_PERIODS)
    else:
        key, all_periods = pd.Grouper(key=date_col, freq=freq), None

    panel = df.groupby(["unit_id", key]).size().reset_index(name="crime_count")
    panel.columns = ["unit_id", "period", "crime_count"]
    wide = panel.pivot_table(
        index="unit_id", columns="period", values="crime_count", aggfunc="sum", fill_value=0
    )
    if all_periods is None:
        if dataset.years is not None:
            # Resampling includes empty boundary bins and uses the same labels
            # as the event Grouper, including end-labelled quarterly bins.
            bounds = pd.Series(0, index=pd.DatetimeIndex([start, end - pd.Timedelta(microseconds=1)]))
            all_periods = bounds.resample(freq).size().index
        elif wide.empty:
            raise ValueError("An empty event set needs dataset.years to define the study window.")
        else:
            all_periods = pd.date_range(wide.columns.min(), wide.columns.max(), freq=freq)
    wide = wide.reindex(columns=all_periods, fill_value=0)
    wide = wide.reindex(dataset.gdf[dataset.id_col], fill_value=0)
    wide.columns.name = None
    return CubeResult(panel=panel, wide=wide, gdf=dataset.gdf, freq=freq,
                      meta=getattr(dataset, "meta", None))
