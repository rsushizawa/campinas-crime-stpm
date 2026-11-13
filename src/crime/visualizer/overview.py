"""Manuscript overview plots from persisted counts, features and assigned bulletins.

Only tallying and plot summaries happen here; no spatial/temporal inference is rerun.
"""
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LogNorm

from . import mapstyle as ms


def render_overview(context, *, brazil_path=None, bulletins_path=None):
    """Render overview assets; return a list of unavailable optional assets.

    Brazil outlines and assigned bulletins are explicit file inputs. Neither is
    downloaded or loaded from a warehouse. The summary figure uses tallies of
    the persisted bulletin assignments, not recalculated scientific estimates.
    """
    gaps = []
    tracts = context.tracts.copy()
    ids = tracts.unit_id.astype(str)

    def read(nb, name):
        return pd.read_csv(context.source(nb, name), dtype={"unit_id": str}).set_index("unit_id").reindex(ids)

    counts = read("01_data_overview", "counts_all_tract.csv")
    features = read("09_association", "features_tract.csv")
    if counts["count"].isna().any() or features["area_km2"].isna().any():
        raise ValueError("Overview inputs must cover every tract")

    def save(fig, name):
        context.save(fig, context.output_dir / name)
        plt.close(fig)

    def map_panel(ax, values, label, cmap="Blues", log=True):
        values = np.asarray(values, dtype=float)
        ok = np.isfinite(values) & ((values > 0) if log else True)
        tracts.plot(ax=ax, color="#d9d9d9", linewidth=0)
        if ok.any():
            lo, hi = values[ok].min(), values[ok].max()
            norm = LogNorm(max(lo, 1e-9), max(hi, lo * 1.001)) if log else None
            tracts.loc[ok].plot(ax=ax, column=values[ok], cmap=cmap, norm=norm,
                               linewidth=0, legend=True, legend_kwds={"shrink": 0.6})
        ms.decorate(ax, tracts.crs, basemap=context.basemap, basemap_strict=True)
        ax.set_title(label, fontsize=8)

    with plt.rc_context({"font.size": 8, "pdf.fonttype": 42}):
        fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.6))
        for ax, col, label in zip(axes, ["count", "per_km2"],
                                  ["(a) Bulletins per tract", "(b) Bulletins per km²"]):
            map_panel(ax, counts[col], label)
        fig.tight_layout()
        save(fig, "fig_counts_map.png")

        cols = ["n_commercial", "n_education", "n_health", "n_religious", "population",
                "income_head_mean", "literacy_rate"]
        labels = ["Other-purpose addresses", "Education addresses", "Health addresses",
                  "Religious addresses", "Resident population", "Income of household heads (R$/month)",
                  "Literacy rate (15+)"]
        fig, axes = plt.subplots(3, 3, figsize=(10.8, 10))
        for i, (col, label) in enumerate(zip(cols, labels)):
            map_panel(axes.flat[i], features[col], f"({chr(97+i)}) {label}",
                      cmap="viridis", log=col != "literacy_rate")
        map_panel(axes.flat[7], features.population / features.area_km2,
                  "(h) Residents per km²", cmap="Oranges")
        axes.flat[8].set_visible(False)
        fig.tight_layout()
        save(fig, "fig_feature_maps.png")

        path = context.source("02_stl", "monthly_series.csv")
        monthly = pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)
        fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.4), sharex=True)
        for series, label in [("all_bulletins", "All bulletins"), ("in_tract", "Assigned to a tract")]:
            axes[0].plot(monthly.index, monthly[(series, "all")], label=label)
        for group in monthly["all_bulletins"].columns:
            if group != "all":
                axes[1].plot(monthly.index, monthly[("all_bulletins", group)], label=group.replace("_", " "))
        for ax in axes:
            ax.set_ylabel("Bulletins per month"); ax.legend(frameon=False, fontsize=7)
            ax.grid(alpha=0.2)
        axes[1].set_xlabel("Month of occurrence")
        fig.tight_layout()
        save(fig, "fig_monthly_series.pdf")

        if brazil_path is not None and brazil_path.is_file():
            context.sources.add(brazil_path.resolve())
            brazil = gpd.read_file(brazil_path).to_crs(tracts.crs)
            fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.9))
            brazil.plot(ax=axes[0], color="#eeeeee", edgecolor="#777777", linewidth=0.3)
            if "codarea" in brazil:
                brazil[brazil.codarea.astype(str) == "35"].plot(ax=axes[0], color="#bbbbbb")
            centre = tracts.geometry.union_all().centroid
            axes[0].scatter([centre.x], [centre.y], color="#d7191c", s=16, label="Campinas")
            axes[0].legend(frameon=False); axes[0].set_axis_off()
            tracts.boundary.plot(ax=axes[1], color="#777777", linewidth=0.15)
            ms.decorate(axes[1], tracts.crs, basemap=context.basemap, basemap_strict=True)
            axes[0].set_title("(a) Brazil and Campinas"); axes[1].set_title("(b) Census tracts")
            fig.tight_layout(); save(fig, "study_area.png")
        else:
            gaps.append("study_area.png: supply a local Brazil outlines file")

        if bulletins_path is not None and bulletins_path.is_file():
            context.sources.add(bulletins_path.resolve())
            bulletins = pd.read_parquet(bulletins_path)
            _summary(context, features, counts, bulletins)
        else:
            gaps.append("summary_boxplots.pdf: supply persisted assigned bulletins")
    return gaps


def _summary(context, features, counts, bulletins):
    """Match the manuscript's nine panels from stored observations and topology."""
    tracts = context.tracts
    ids = tracts.unit_id.astype(str)
    date = pd.to_datetime(bulletins.DATA_OCORRENCIA_BO)
    bul = bulletins.loc[date.between("2022-01-01", "2025-12-31") & bulletins.census_tract_id.notna()].copy()
    bul["unit_id"] = bul.census_tract_id.astype(str)
    bul["month"] = date.loc[bul.index].dt.to_period("M")
    months = pd.period_range("2022-01", "2025-12", freq="M")
    groups = ["all", "property", "bodily_harm", "traffic", "drug", "violent"]
    per_tract, per_month = [], []
    for group in groups:
        subset = bul if group == "all" else bul[bul.crime_group == group]
        tallies = pd.crosstab(subset.unit_id, subset.month).reindex(index=ids, columns=months, fill_value=0)
        per_tract.append(tallies.sum(axis=1).to_numpy())
        per_month.append(tallies.to_numpy().ravel())
    if not np.array_equal(per_tract[0], counts["count"].to_numpy()):
        raise ValueError("Stored bulletin assignments disagree with overview counts")
    # Queen neighbours are topology metadata for the distribution panel only.
    # No spatial statistic, permutation, p-value, or FDR classification is computed.
    from libpysal.weights import Queen

    neighbors = np.asarray(list(Queen.from_dataframe(tracts, use_index=False,
                                                   silence_warnings=True).cardinalities.values()))
    fig = plt.figure(figsize=(7.2, 9.6))
    grid = fig.add_gridspec(5, 3, height_ratios=[1.35, 1.35, 1, 1, 1], hspace=1.0, wspace=0.5)
    axes = [fig.add_subplot(grid[0, :]), fig.add_subplot(grid[1, :]),
            fig.add_subplot(grid[2, :2]), fig.add_subplot(grid[2, 2])]
    axes += [fig.add_subplot(grid[i, j]) for i, j in [(3, 0), (3, 1), (3, 2), (4, 0), (4, 1)]]
    arrays = [per_tract, per_month,
              [features[c].dropna() for c in ["n_commercial", "n_education", "n_health", "n_religious"]],
              [features.population], [features.population / features.area_km2],
              [features.income_head_mean.dropna()], [100 * features.literacy_rate.dropna()],
              [features.area_km2], [neighbors]]
    labels = [groups, groups, ["Other purposes", "Education", "Health", "Religious"]] + [[""]] * 6
    titles = ["Bulletins per tract", "Bulletins per tract-month", "CNEFE addresses per tract",
              "Residents per tract", "Residents per km²", "Income (R$/month)", "Literacy (15+), %",
              "Tract area, km²", "Queen neighbours per tract"]
    for i, (ax, values, labs, title) in enumerate(zip(axes, arrays, labels, titles)):
        ax.boxplot(values, orientation="horizontal", tick_labels=labs,
                   flierprops={"marker": ".", "markersize": 1.5, "rasterized": True})
        if i in [0, 1, 2, 4, 7]:
            ax.set_xscale("symlog", linthresh=1)
        ax.set_xlabel(f"({chr(97+i)}) {title}", fontsize=8)
        ax.tick_params(labelsize=7); ax.grid(axis="x", alpha=0.2)
    context.save(fig, context.output_dir / "summary_boxplots.pdf")
    plt.close(fig)
