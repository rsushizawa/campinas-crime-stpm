"""The space-time cube as a first-class object.

``SpaceTimeCube`` is a ``unit x time`` frame carrying any number of named
**layers** — 2-D arrays that all share one ``(unit_id index, period columns)``
axis pair. Every space-time stage reads and writes layers instead of
re-deriving its own matrix:

    cube = space_time_cube(ds, freq="ME")          # -> CubeResult (a SpaceTimeCube)
    cube.layer("count")                             # observed unit x period counts
    cube.add_layer("gi_z", z)                       # emerging_hotspots writes this
    panel = cube.to_panel(["count", "gi_z"])        # long form for modelling

``CubeResult`` is the back-compatible subclass returned by ``space_time_cube``:
it keeps ``.wide`` (= the ``count`` layer), ``.panel``, ``.gdf`` and ``.freq``
exactly as before, so existing consumers and notebooks are untouched.

Layer conventions (written by later stages, not the constructor):
  observed    count · exposure · rate
  statistical gi_z · gi_p · ehsa_category · ehsa_ml_category
  predicted   risk · forecast · forecast_lower · forecast_upper
  features    static columns broadcast over time; dynamic lag/rolling/calendar
              and exogenous (tmax, precip, is_holiday, ambient) layers
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from crime.core.metadata import DatasetMeta


class SpaceTimeCube:
    """A ``unit x time`` grid with named layers sharing one index/column axis.

    Parameters
    ----------
    gdf     : one row per spatial unit (geometry + attributes).
    freq    : the time-bin frequency this cube was built at (pandas offset alias
              or a cyclic tag like ``"hour"`` / ``"day_period"``).
    id_col  : the column of ``gdf`` that identifies a unit; also the layer index.
    layers  : optional ``{name: DataFrame}`` to seed the cube with. The first
              layer fixes the ``(index, columns)`` axis; later layers are
              reindexed onto it.
    meta    : the source Dataset's header (support, years, crime filter).
    """

    def __init__(self, gdf: gpd.GeoDataFrame, *, freq: str = "ME",
                 id_col: str = "unit_id", layers: dict[str, pd.DataFrame] | None = None,
                 meta: DatasetMeta | None = None):
        self.gdf = gdf
        self.freq = freq
        self.id_col = id_col
        self.meta = meta
        self._layers: dict[str, pd.DataFrame] = {}
        for name, df in (layers or {}).items():
            self.add_layer(name, df)

    # ------------------------------------------------------------------ layers
    @property
    def layers(self) -> dict[str, pd.DataFrame]:
        """A shallow copy of the ``{name: DataFrame}`` layer map."""
        return dict(self._layers)

    @property
    def layer_names(self) -> list[str]:
        return list(self._layers)

    def has_layer(self, name: str) -> bool:
        return name in self._layers

    def layer(self, name: str) -> pd.DataFrame:
        try:
            return self._layers[name]
        except KeyError:
            raise KeyError(
                f"no layer {name!r}; have {self.layer_names}"
            ) from None

    def _axis(self) -> tuple[pd.Index, pd.Index] | None:
        if not self._layers:
            return None
        ref = next(iter(self._layers.values()))
        return ref.index, ref.columns

    def add_layer(self, name: str, df: pd.DataFrame) -> "SpaceTimeCube":
        """Attach/replace a layer. The first layer defines the axis; subsequent
        layers are reindexed onto it (missing cells become NaN)."""
        df = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
        axis = self._axis()
        if axis is not None:
            index, columns = axis
            df = df.reindex(index=index, columns=columns)
        self._layers[name] = df
        return self

    # ------------------------------------------------------------------ axes
    @property
    def units(self) -> pd.Index:
        axis = self._axis()
        if axis is None:
            return pd.Index(self.gdf[self.id_col])
        return axis[0]

    @property
    def periods(self) -> pd.Index:
        axis = self._axis()
        if axis is None:
            return pd.Index([])
        return axis[1]

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.units), len(self.periods)

    # ------------------------------------------------------------------ reshape
    def to_panel(self, layers: list[str] | None = None, *, dropna_all: bool = False) -> pd.DataFrame:
        """Long form: one row per ``(unit_id, period)`` with one column per layer.

        ``dropna_all`` drops rows where every requested layer is NaN.
        """
        names = list(layers) if layers is not None else self.layer_names
        if not names:
            raise ValueError("cube has no layers to panel")
        out: pd.DataFrame | None = None
        for n in names:
            long = (
                self.layer(n)
                .rename_axis(index=self.id_col, columns="period")
                .reset_index()
                .melt(id_vars=self.id_col, var_name="period", value_name=n)
            )
            out = long if out is None else out.merge(long, on=[self.id_col, "period"], how="outer")
        if dropna_all:
            out = out.dropna(subset=names, how="all")
        return out.reset_index(drop=True)

    def slice(self, *, time) -> pd.DataFrame:
        """One time bin across every layer: a ``unit x layer`` DataFrame."""
        return pd.DataFrame({n: df[time] for n, df in self._layers.items()})

    def split_time(self, date) -> tuple["SpaceTimeCube", "SpaceTimeCube"]:
        """``(past, future)`` cubes: columns ``<= date`` and ``> date``.
        Only valid for datetime-like period columns."""
        cols = self.periods
        past_cols = cols[cols <= date]
        future_cols = cols[cols > date]
        return self._subset_columns(past_cols), self._subset_columns(future_cols)

    def _subset_columns(self, columns: pd.Index) -> "SpaceTimeCube":
        sub = SpaceTimeCube(self.gdf, freq=self.freq, id_col=self.id_col, meta=self.meta)
        for name, df in self._layers.items():
            sub._layers[name] = df.reindex(columns=columns)
        return sub

    def collapse(self, *, freq: str) -> "SpaceTimeCube":
        """Re-bin the time axis to a coarser ``freq`` (datetime columns only).
        Sums the ``count``/``exposure`` layers, means everything else."""
        if not isinstance(self.periods, pd.DatetimeIndex):
            raise ValueError("collapse() needs datetime period columns")
        out = SpaceTimeCube(self.gdf, freq=freq, id_col=self.id_col, meta=self.meta)
        for name, df in self._layers.items():
            agg = "sum" if name in ("count", "exposure") else "mean"
            out._layers[name] = df.T.resample(freq).agg(agg).T
        return out

    def __repr__(self) -> str:
        n, t = self.shape
        return (f"{type(self).__name__}({n} units x {t} bins, freq={self.freq!r}, "
                f"layers={self.layer_names})")


class CubeResult(SpaceTimeCube):
    """Return type of :func:`crime.esri.cube.space_time_cube` — a ``SpaceTimeCube`` whose
    canonical ``count`` layer is also reachable as ``.wide`` (back-compat), plus
    the long-form ``.panel`` the constructor already computed."""

    def __init__(self, *, panel: pd.DataFrame, wide: pd.DataFrame,
                 gdf: gpd.GeoDataFrame, freq: str = "ME", id_col: str = "unit_id",
                 meta: DatasetMeta | None = None):
        super().__init__(gdf, freq=freq, id_col=id_col, layers={"count": wide}, meta=meta)
        self.panel = panel

    @property
    def wide(self) -> pd.DataFrame:
        return self.layer("count")

    def summary(self) -> None:
        print(
            f"Space-time cube — {self.wide.shape[0]} units x {self.wide.shape[1]} "
            f"time bins (freq={self.freq}), {int(self.wide.values.sum())} events"
        )
