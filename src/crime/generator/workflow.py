"""Notebook-facing orchestration of the study's reusable statistical functions."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from crime.generator.cube import generate_cube
from crime.models import CrimeDataset
from crime.query import SPATIAL_GROUPS, TEMPORAL_GROUPS, CrimeQuery


@dataclass(frozen=True)
class WorkflowConfig:
    """Published defaults; changing these creates a different analysis run."""

    global_permutations: int = 999
    local_permutations: int = 499
    seed: int = 20221
    alpha: float = 0.05
    weights: tuple[str, ...] = ('queen', 'rook', 'knn5')
    monthly_ehsa: bool = True

    def __post_init__(self):
        if min(self.global_permutations, self.local_permutations) < 1:
            raise ValueError('Inference needs at least one permutation')
        if not 0 < self.alpha < 1 or not self.weights or 'queen' not in self.weights:
            raise ValueError('Require 0 < alpha < 1 and include queen weights')
        if set(self.weights) - {'queen', 'rook', 'knn5'}:
            raise ValueError('Unknown spatial weights')


@dataclass
class WorkflowResult:
    """Saved output root and immediately displayable tables and cube histories."""

    output_dir: Path
    tables: dict[str, pd.DataFrame]
    cubes: dict
    ehsa: dict
    manifest: Path


def monthly_series(dataset):
    """All-report and mapped series, with complete bins and disjoint groups."""
    all_reports, mapped = {}, {}
    for group in TEMPORAL_GROUPS:
        c = generate_cube(dataset, CrimeQuery(crime_group=group, unit='city', time_unit='month'))
        all_reports[group] = pd.Series(c.counts[0], index=c.periods)
        if group in SPATIAL_GROUPS:
            c = generate_cube(dataset, CrimeQuery(crime_group=group, time_unit='month'))
            mapped[group] = pd.Series(c.counts.sum(axis=0), index=c.periods)
    return {'all_bulletins': pd.DataFrame(all_reports), 'in_tract': pd.DataFrame(mapped)}


def describe_dataset(dataset: CrimeDataset) -> dict[str, pd.DataFrame]:
    """EDA with geocoding denominators that retain unmapped reports."""
    b = dataset.bulletins.copy()
    date_col = 'occurrence_date' if 'occurrence_date' in b else 'DATA_OCORRENCIA_BO'
    b['year'] = pd.to_datetime(b[date_col]).dt.year
    b['assigned'] = b.census_tract_id.notna()
    group_year = b.groupby(['year', 'crime_group']).agg(
        reports=('assigned', 'size'), assigned=('assigned', 'sum')).reset_index()
    pooled = b.groupby('year').agg(reports=('assigned', 'size'), assigned=('assigned', 'sum')).reset_index()
    pooled['crime_group'] = 'all'
    coverage = pd.concat([pooled, group_year], ignore_index=True)
    coverage['assignment_rate'] = coverage.assigned / coverage.reports
    tracts = dataset.tracts.sort_values('census_tract_id').copy()
    c = generate_cube(dataset)
    counts = pd.DataFrame({'unit_id': c.unit_ids, 'count': c.counts.sum(axis=1)})
    area = tracts.set_index('census_tract_id').area_km2
    counts['per_km2'] = counts['count'] / counts.unit_id.map(area)
    tables = {'geocoding_by_year_group': coverage, 'tract_counts': counts,
              'tract_summary': tracts.select_dtypes('number').describe().T}
    if {'LATITUDE', 'LONGITUDE'} <= set(b):
        stacks = b[b.assigned].groupby(['LATITUDE', 'LONGITUDE']).size().sort_values(ascending=False)
        tables['coordinate_stacks'] = stacks.rename('reports').reset_index()
    return tables


def run_paper_workflow(dataset: CrimeDataset, output_dir, config=None, *, progress=print) -> WorkflowResult:
    """Run Tables 6–10 and their source data without executing other notebooks.

    Outputs are compatible with the existing paper renderer. The study remains
    Campinas 2022–2025; source-native municipal reference series use a separate
    temporal path. No manuscript or live warehouse is modified here.
    """
    from crime.geoprocessor.weights import build_weights
    from crime.stpm.association import (
        EXTENSIVE,
        INTENSIVE,
        bivariate_moran_table,
        local_bivariate,
        spearman_table,
        w_for,
        xy,
    )
    from crime.stpm.ehsa import CATEGORIES, analyze_cube, counts_table
    from crime.stpm.hotspots import local_hotspots
    from crime.stpm.moran import global_moran, moran_scatter
    from crime.stpm.temporal import fit_stl, mann_kendall_table, robust_sensitivity, summarize_stl
    from crime.utils.checksums import sha256

    config = config or WorkflowConfig()
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / 'analysis_run.json'
    if manifest.exists():
        raise FileExistsError('Choose a new run directory; existing run provenance is immutable')
    metadata = {'status': 'running', 'config': asdict(config),
                'started_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'sources': [asdict(s) for s in dataset.sources],
                'multiple_testing': {'static': 'BH separately by statistic, group and weights',
                                     'ehsa': 'BH over all tract-period bins per group and frequency',
                                     'ehsa_tract_trends': 'unadjusted'},
                'scope': 'Campinas 2022–2025, primary-offence report counts'}
    package_root = Path(__file__).parents[1]
    metadata['code'] = {str(p.relative_to(package_root)): sha256(p)
                        for folder in ('generator', 'stpm', 'geoprocessor')
                        for p in sorted((package_root / folder).glob('*.py'))}
    metadata['versions'] = {p: version(p) for p in ('campinas-crime-stpm', 'numpy', 'pandas', 'esda',
                                                   'libpysal', 'pymannkendall', 'statsmodels')}
    manifest.write_text(json.dumps(metadata, indent=2, default=str))
    tables, cubes, ehsa = {}, {}, {}
    def save(frame, folder, name, *, index=False):
        path = root / folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=index)
        return frame
    progress('Descriptive summaries and monthly temporal analysis')
    eda = describe_dataset(dataset)
    for name, table in eda.items():
        save(table, '01_data_overview', name + '.csv', index=name == 'tract_summary')
    save(eda['tract_counts'], '01_data_overview', 'counts_all_tract.csv')
    series = monthly_series(dataset)
    save(pd.concat(series, axis=1), '02_stl', 'monthly_series.csv', index=True)
    temporal = fit_stl(series)
    save(temporal.components, '02_stl', 'stl_components.csv', index=True)
    tables['stl_strength'] = save(summarize_stl(temporal.fits), '02_stl', 'stl_strength.csv')
    tables['trends'] = save(mann_kendall_table(series), '02_stl', 'mann_kendall_sen.csv')
    save(robust_sensitivity(series, temporal.fits), '02_stl', 'stl_robust_vs_nonrobust.csv')
    units = dataset.tracts.sort_values('census_tract_id').rename(columns={'census_tract_id': 'unit_id'})
    units['unit_id'] = units.unit_id.astype(str)
    units = units.reset_index(drop=True)
    weights = {kind: build_weights(units, kind) for kind in config.weights}
    queen = weights['queen'][0]
    # EHSA retains islands, matching the published space–time construction.
    from libpysal.weights import Queen
    queen_all = Queen.from_dataframe(units, ids='unit_id', use_index=False)
    counts, moran_rows, local_rows, queen_labels, weight_rows = {}, [], [], [], []
    for kind, (w, mask, islands) in weights.items():
        card = np.asarray(list(w.cardinalities.values()))
        weight_rows.append(dict(support='tract', weights=kind, n_units=len(units), n_islands=len(islands),
                                islands='; '.join(map(str, islands)), n_components_after_drop=w.n_components,
                                mean_neighbours=card.mean(), median_neighbours=np.median(card),
                                min_neighbours=card.min(), max_neighbours=card.max()))
    save(pd.DataFrame(weight_rows), '04_global_moran', 'weights_summary.csv')
    for group in SPATIAL_GROUPS:
        progress(f'Spatial inference: {group}')
        c = generate_cube(dataset, CrimeQuery(crime_group=group, time_unit='quarter'))
        cubes[group] = c
        y = c.counts.sum(axis=1).astype(float)
        counts[group] = y
        for kind, (w, mask, _) in weights.items():
            g = global_moran(y[mask], w, permutations=config.global_permutations, seed=config.seed)
            moran_rows.append(dict(support='tract', group=group, weights=kind, **asdict(g)))
            local = local_hotspots(y, weights[kind], group=group, kind=kind, alpha=config.alpha,
                                   permutations=config.local_permutations, seed=config.seed)
            local_rows.append(local.summary)
            if kind == 'queen':
                queen_labels.append(local.labels.assign(group=group))
        progress(f'EHSA quarterly bins and histories: {group}')
        Y = pd.DataFrame(c.counts, index=c.unit_ids, columns=c.periods)
        result = analyze_cube(Y, queen_all, alpha=config.alpha)
        ehsa[group] = result
        save(result.labels.assign(group=group, support='tract'), '06_ehsa', f'ehsa_tract_{group}_quarterly.csv')
        save(result.bins.assign(group=group, support='tract'), '06_ehsa', f'bins_tract_{group}_quarterly.csv')
        if config.monthly_ehsa:
            cm = generate_cube(dataset, CrimeQuery(crime_group=group, time_unit='month'))
            monthly = analyze_cube(pd.DataFrame(cm.counts, index=cm.unit_ids, columns=cm.periods),
                                   queen_all, quarterly=False, alpha=config.alpha)
            save(monthly.labels.assign(group=group, support='tract'), '06_ehsa', f'ehsa_tract_{group}_monthly.csv')
    tables['global_moran'] = save(pd.DataFrame(moran_rows), '04_global_moran', 'global_moran.csv')
    z, lag = moran_scatter(counts['all'][weights['queen'][1]], queen)
    save(pd.DataFrame({'unit_id': queen.id_order, 'z': z, 'lag_z': lag,
                       'count': counts['all'][weights['queen'][1]], 'support': 'tract'}),
         '04_global_moran', 'moran_scatter_all_queen.csv')
    tables['local_hotspots'] = save(pd.DataFrame(local_rows), '05_local_gi_lisa', 'local_counts_all_weights.csv')
    save(pd.concat(queen_labels, ignore_index=True), '05_local_gi_lisa', 'labels_tract_queen.csv')
    before_after = {}
    for group, result in ehsa.items():
        for which, column in [('before FDR', 'category'), ('after FDR', 'category_fdr')]:
            before_after[group, 'tract', which] = result.labels[column].value_counts()
    ba = pd.DataFrame(before_after).reindex(CATEGORIES).fillna(0).astype(int)
    tables['ehsa_counts'] = save(ba, '06_ehsa', 'before_after_fdr_counts.csv', index=True)
    save(counts_table({('Q', 'tract', g): r.labels for g, r in ehsa.items()}),
         '06_ehsa', 'category_counts.csv', index=True)
    progress('Feature associations and local bivariate Moran')
    features = units.set_index('unit_id')[[*EXTENSIVE, *INTENSIVE, 'area_km2']]
    save(features, '09_association', 'features_tract.csv', index=True)
    crime = {}
    for group, c in cubes.items():
        crime['tract', group, '2022-2025'] = pd.Series(counts[group], index=features.index)
        crime['tract', group, '2022'] = pd.Series(c.counts[:, :4].sum(axis=1), index=features.index, dtype=float)
    tables['spearman'] = save(spearman_table(crime, {'tract': features}, groups=SPATIAL_GROUPS),
                             '09_association', 'spearman.csv')
    tables['bivariate_moran'] = save(bivariate_moran_table(
        crime, {'tract': features}, {'tract': queen_all}, groups=SPATIAL_GROUPS,
        permutations=config.global_permutations, seed=config.seed), '09_association', 'moran_bv.csv')
    local_bv_rows = []
    for scale in ('count', 'per_km2'):
        x, y = xy(crime['tract', 'all', '2022-2025'], features, 'n_commercial', scale)
        result = local_bivariate(x, y, w_for(queen_all, x.index), scale=scale,
                                 permutations=config.local_permutations, seed=config.seed, alpha=config.alpha)
        local_bv_rows.append(result.summary)
        save(result.labels, '09_association', f'local_bv_crime_commerce_tract_{scale}.csv')
    tables['local_bivariate'] = save(pd.DataFrame(local_bv_rows), '09_association', 'local_bv_counts.csv')
    metadata['status'] = 'complete'
    metadata['completed_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    metadata['outputs'] = {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob('*.csv'))}
    manifest.write_text(json.dumps(metadata, indent=2, default=str))
    progress(f'Complete: {root}')
    return WorkflowResult(root, tables, cubes, ehsa, manifest)


def analyze_reference(series, output_dir):
    """Temporal analysis only for complete, nonconstant source-native indicators.

    Missing or structural-zero months are never imputed for STL or trend tests.
    The status table makes exclusions visible instead of silently dropping them.
    """
    from crime.stpm.temporal import fit_stl, mann_kendall_table, summarize_stl
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    d = series.values
    complete = d.columns[d.notna().all() & d.nunique().gt(1)] if len(d) >= 24 else []
    status = pd.DataFrame({'indicator': d.columns, 'months': len(d), 'available_months': d.notna().sum().values,
                           'analyzed': d.columns.isin(complete)})
    status.to_csv(root / 'temporal_eligibility.csv', index=False)
    d.to_csv(root / 'monthly_reference.csv')
    series.coverage.to_csv(root / 'reference_coverage.csv')
    tables = {'eligibility': status}
    if len(complete):
        selected = {'reference': d[list(complete)]}
        result = fit_stl(selected)
        result.components.to_csv(root / 'stl_components.csv')
        tables['trends'] = mann_kendall_table(selected)
        tables['strength'] = summarize_stl(result.fits)
        tables['trends'].to_csv(root / 'mann_kendall_sen.csv', index=False)
        tables['strength'].to_csv(root / 'stl_strength.csv', index=False)
    return tables
