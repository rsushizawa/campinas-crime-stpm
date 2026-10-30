"""Correlation analysis — urban features vs crime, and crime type vs crime type.

Method
    Rank (Spearman, default) or Pearson correlation; hierarchical average-
    linkage clustering of the crime-type correlation matrix (distance 1 − ρ);
    variance inflation factors and the design-matrix condition number for
    collinearity.
Reference
    Spearman, C. (1904). The proof and measurement of association between two
    things. Am. J. Psychology 15. VIF: statsmodels
    ``variance_inflation_factor``. Clustering: SciPy ``linkage``.
Inputs → Outputs
    Dataset → :class:`CorrelationResult` / :class:`CollinearityResult`.

    from crime import feature_correlation, crime_crime_correlation, feature_collinearity
    fc = feature_correlation(ds)                 # urban features vs crime_count (Spearman)
    cc = crime_crime_correlation()               # co-location of crime types (hier. ordered)
    vif = feature_collinearity(ds)               # VIF + condition number for the feature set

``feature_correlation`` is meant for a Dataset restricted to the demographic
reference year (2022) so the comparison against the 2022 census is valid —
build it with ``load_sectors(years=(2022, 2022), ...)``; it warns otherwise.
"""
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from crime.core.config import DEMOGRAPHIC_YEAR, DBConfig
from crime.core.metadata import ResultMeta, dataset_meta_of
from crime.data.catalog import DEFAULT_FEATURES
from crime.data.postgis import default_source

__all__ = ["DEFAULT_FEATURES", "CorrelationResult", "CollinearityResult", "feature_correlation",
           "crime_crime_correlation", "vif_table", "feature_collinearity"]


@dataclass
class CorrelationResult:
    matrix: pd.DataFrame = field(repr=False)
    target_corr: pd.Series | None = field(default=None, repr=False)
    method: str = "spearman"
    linkage: object = field(default=None, repr=False)   # scipy linkage (crime-crime only)
    order: list | None = field(default=None, repr=False)  # hierarchically-clustered column order
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def summary(self) -> None:
        if self.target_corr is not None:
            print(f"{self.method.title()} correlation with target:")
            print(self.target_corr.round(3).to_string())
        else:
            print(f"{self.method.title()} correlation matrix {self.matrix.shape}")
            if self.order:
                print("clustered order:", ", ".join(self.order))


def feature_correlation(
    dataset, *, cols: list[str] | None = None, method: str = "spearman", target: str = "crime_count"
) -> CorrelationResult:
    """Correlation of numeric columns with ``target``. ``cols=None`` takes every
    numeric column except the unit id (any unit kind: only ``dataset.gdf`` is
    read). Note the default is *not* ``DEFAULT_FEATURES``; and ``income_mean``,
    where present, is a COUNT of residents earning <= 1/2 minimum wage, not an
    income (see ``database/enrich.sql``)."""
    years = getattr(dataset, "years", None)
    if years and tuple(years) != (DEMOGRAPHIC_YEAR, DEMOGRAPHIC_YEAR):
        warnings.warn(
            f"dataset spans {years[0]}–{years[1]} but demographics are a {DEMOGRAPHIC_YEAR} "
            f"census snapshot; restrict to load_sectors(years=({DEMOGRAPHIC_YEAR}, "
            f"{DEMOGRAPHIC_YEAR})) for a temporally valid comparison.",
            stacklevel=2,
        )
    id_col = getattr(dataset, "id_col", "unit_id")
    cols = list(cols) if cols else [c for c in dataset.gdf.select_dtypes("number").columns if c != id_col]
    if target not in cols:
        cols.append(target)
    matrix = dataset.gdf[cols].corr(method=method)
    target_corr = matrix[target].drop(target).sort_values(key=abs, ascending=False)
    return CorrelationResult(matrix=matrix, target_corr=target_corr, method=method, meta=ResultMeta(
        method=f"{method} correlation with {target}", reference="Spearman 1904" if method == "spearman" else "",
        params=dict(cols=list(cols), method=method, target=target), dataset=dataset_meta_of(dataset)))


def crime_crime_correlation(
    *,
    unit: str = "sector",
    year: int = DEMOGRAPHIC_YEAR,
    method: str = "spearman",
    min_total: int = 30,
    cluster: bool = True,
    db: DBConfig | None = None,
    source=None,
) -> CorrelationResult:
    """Correlation between crime *types* across spatial units: per unit, count
    crimes per ``crime_slug`` then correlate the slug columns. High correlation
    = two types concentrate in the same places. ``cluster=True`` also returns a
    hierarchical linkage + a clustered column order so the matrix reads as blocks."""
    counts = default_source(db, source).slug_counts_by_unit(unit, year)
    wide = counts.pivot_table(index="unit_id", columns="crime_slug", values="n", fill_value=0)
    wide = wide.loc[:, wide.sum() >= min_total]
    matrix = wide.corr(method=method)

    linkage = order = None
    if cluster and matrix.shape[0] > 2:
        from scipy.cluster.hierarchy import leaves_list
        from scipy.cluster.hierarchy import linkage as _linkage
        from scipy.spatial.distance import squareform

        dist = squareform(np.clip(1 - matrix.values, 0, 2), checks=False)
        linkage = _linkage(dist, method="average")
        order = [matrix.columns[i] for i in leaves_list(linkage)]
        matrix = matrix.loc[order, order]
    return CorrelationResult(matrix=matrix, target_corr=None, method=method,
                             linkage=linkage, order=order, meta=ResultMeta(
                                 method=f"crime-type {method} correlation",
                                 reference="Spearman 1904" if method == "spearman" else "",
                                 params=dict(unit=unit, year=year, method=method,
                                             min_total=min_total, cluster=cluster)))


@dataclass
class CollinearityResult:
    vif: pd.Series = field(repr=False)
    condition_number: float = float("nan")
    meta: ResultMeta | None = field(default=None, repr=False, compare=False)

    def summary(self) -> None:
        print(f"Variance inflation factors (condition number {self.condition_number:.0f}):")
        print(self.vif.round(2).to_string())
        high = self.vif[self.vif > 5].index.tolist()
        if high:
            print(f"VIF > 5 (collinear, attributions interchangeable): {', '.join(high)}")


def vif_table(X, feature_names: list[str] | None = None) -> CollinearityResult:
    """VIF per column + design-matrix condition number from an explicit feature
    matrix (DataFrame or 2-D array). Standardises, drops all-NaN / zero-variance
    columns, and ignores rows with any NaN. Use this to attach a collinearity
    check to any SHAP result — VIF > 5 means attributions between those columns
    are not separable."""
    df = X if isinstance(X, pd.DataFrame) else pd.DataFrame(X, columns=feature_names)
    df = df.select_dtypes("number").dropna()
    z = (df - df.mean()) / df.std(ddof=0)
    z = z.loc[:, z.notna().any()].fillna(0.0)
    if z.shape[1] < 2 or len(z) < z.shape[1] + 2:
        return CollinearityResult(vif=pd.Series(dtype=float), condition_number=float("nan"))

    from statsmodels.stats.outliers_influence import variance_inflation_factor

    Xc = np.column_stack([np.ones(len(z)), z.to_numpy()])
    vif = pd.Series(
        [variance_inflation_factor(Xc, i + 1) for i in range(z.shape[1])], index=list(z.columns)
    ).sort_values(ascending=False)
    return CollinearityResult(vif=vif, condition_number=float(np.linalg.cond(z.to_numpy())))


def feature_collinearity(dataset, *, features: tuple[str, ...] = DEFAULT_FEATURES) -> CollinearityResult:
    """VIF per feature + the design-matrix condition number for a Dataset's
    urban features. Thin wrapper over :func:`vif_table`."""
    cols = [f for f in features if f in dataset.gdf.columns]
    return vif_table(dataset.gdf[cols])
