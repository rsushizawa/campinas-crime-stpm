"""Descriptive figures used by the guided notebooks."""
import matplotlib.pyplot as plt
import pandas as pd

from crime.generator.workflow import describe_dataset, monthly_series


def plot_exploration(dataset):
    """Return figures without saving or mutating notebook state."""
    tables = describe_dataset(dataset)
    monthly = monthly_series(dataset)
    figures = {}
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    monthly['all_bulletins'].drop(columns='all').sum().plot.bar(ax=axes[0, 0], color='#237ab7')
    axes[0, 0].set(title='Reports by offence group', ylabel='Reports')
    counts = tables['tract_counts']['count']
    axes[0, 1].hist(counts, bins=40, color='#237ab7')
    axes[0, 1].set(title='Distribution across tracts', xlabel='Reports per tract', ylabel='Tracts')
    monthly['all_bulletins'].drop(columns='all').plot.box(ax=axes[1, 0], rot=35)
    axes[1, 0].set(title='Monthly report distributions', ylabel='Reports per month')
    for label, values in monthly.items():
        axes[1, 1].plot(values.index, values['all'], label=label.replace('_', ' '))
    axes[1, 1].set(title='All reports and mapped reports', ylabel='Reports per month')
    axes[1, 1].legend()
    figures['descriptive_overview'] = fig
    coverage = tables['geocoding_by_year_group'].pivot(index='year', columns='crime_group', values='assignment_rate')
    fig, ax = plt.subplots(figsize=(10, 4), constrained_layout=True)
    coverage.plot.bar(ax=ax)
    ax.set(title='Tract-assignment coverage', ylabel='Fraction of reports assigned', ylim=(0, 1))
    ax.legend(bbox_to_anchor=(1, 1), loc='upper left')
    figures['geocoding_coverage'] = fig
    return figures


def plot_reference(series):
    """Show native indicators separately; missing observations remain gaps."""
    values = series.values
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    values.plot(ax=axes[0, 0], legend=False)
    axes[0, 0].set(title='Source-native monthly series', ylabel=series.measure)
    values.count().plot.barh(ax=axes[0, 1])
    axes[0, 1].set(title='Available months per indicator', xlabel='Months')
    values.plot.box(ax=axes[1, 0], rot=70)
    axes[1, 0].set(title='Monthly count distributions', ylabel=series.measure)
    for indicator in values:
        axes[1, 1].hist(values[indicator].dropna(), bins=20, histtype='step', label=indicator)
    axes[1, 1].set(title='Distributions by indicator', xlabel=series.measure, ylabel='Months')
    return fig


def plot_reconciliation(comparison):
    """Overlay actual monthly counts rather than just correlating two series."""
    indicators = list(comparison.indicator.unique())
    fig, axes = plt.subplots(len(indicators), 1, figsize=(10, 3 * len(indicators)), squeeze=False,
                             constrained_layout=True)
    for ax, indicator in zip(axes[:, 0], indicators):
        d = comparison[comparison.indicator.eq(indicator)]
        dates = pd.to_datetime(d.period)
        ax.plot(dates, d.local_reports, label='Local primary-offence reports')
        ax.plot(dates, d.reference_count, label='Reference occurrences', linestyle='--')
        ax.set(title=indicator, ylabel='Count')
        ax.legend()
    return fig
