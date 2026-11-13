"""Treat municipal reference series without inventing tract-level observations."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MunicipalSeries:
    """Source-native indicators sharing one institution and counting unit."""

    values: pd.DataFrame
    coverage: pd.DataFrame
    institution: str
    measure: str
    municipality: str


def municipal_series(reference: pd.DataFrame, *, institution: str, measure='quantidade_ocorrencias',
                     municipality='3509502', start='2022-01-01', end='2025-12-31') -> MunicipalSeries:
    """Reindex to every requested month while preserving missing and flagged zeros.

    Values remain source-native indicators. They are not disjoint offence groups
    and must not be summed into an 'all' series. Structural zeros are retained in
    the coverage table but masked in the analysis values until investigated.
    """
    if measure not in ('quantidade_ocorrencias', 'quantidade_vitimas'):
        raise ValueError('Choose occurrence counts or victim counts explicitly')
    required = {'ano', 'mes', 'id_municipio', 'tipo_ocorrencia', 'abrangencia',
                'situacao_registro', measure}
    if missing := required - set(reference):
        raise ValueError(f'Missing source columns: {sorted(missing)}')
    months = pd.date_range(pd.Timestamp(start).to_period('M').start_time,
                           pd.Timestamp(end).to_period('M').start_time, freq='MS', name='period')
    if len(months) == 0:
        raise ValueError('Start must precede end')
    d = reference.loc[reference.id_municipio.astype(str).eq(municipality)
                      & reference.abrangencia.eq(institution)].copy()
    if d.empty:
        raise ValueError(f'No rows for {municipality} / {institution}; inspect available institutions first')
    d['period'] = pd.to_datetime(dict(year=d.ano, month=d.mes, day=1), errors='raise')
    d = d[d.period.isin(months)]
    if d.empty:
        raise ValueError('No rows in the selected date range')
    if d[['period', 'tipo_ocorrencia']].isna().any().any():
        raise ValueError('Month and occurrence type must be present')
    if d.duplicated(['period', 'tipo_ocorrencia']).any():
        raise ValueError('Duplicate municipality-month-indicator rows; do not sum reporting institutions')
    allowed = {'reportado', 'zero_estrutural', 'nao_reportado'}
    if not d.situacao_registro.isin(allowed).all():
        raise ValueError('Unknown coverage flag; inspect the source schema')
    count = pd.to_numeric(d[measure], errors='raise')
    finite = count.dropna().astype(float)
    if not np.isfinite(finite).all() or (finite < 0).any() or (finite % 1 != 0).any():
        raise ValueError('Reference counts must be nonnegative integers or missing')
    if (d.situacao_registro.eq('nao_reportado') & count.notna()).any():
        raise ValueError('Unreported observations must have missing counts')
    d['value'] = count.where(d.situacao_registro.eq('reportado'))
    # Keep wholly missing indicators visible. Only an explicitly populated
    # other measure establishes that an indicator belongs to another unit.
    other_measure = 'quantidade_vitimas' if measure == 'quantidade_ocorrencias' else 'quantidade_ocorrencias'
    d['has_value'] = count.notna()
    d['has_other'] = d[other_measure].notna() if other_measure in d else False
    units = d.groupby('tipo_ocorrencia')[['has_value', 'has_other']].any()
    if (units.has_value & units.has_other).any():
        raise ValueError('An indicator mixes occurrence and victim units; inspect its definition by year')
    indicators = list(units.index[units.has_value | ~units.has_other])
    if not indicators:
        raise ValueError('No values for the selected counting unit')
    values = d.pivot(index='period', columns='tipo_ocorrencia', values='value').reindex(
        index=months, columns=indicators).astype(float)
    coverage = d.pivot(index='period', columns='tipo_ocorrencia', values='situacao_registro').reindex(
        index=months, columns=indicators).fillna('absent')
    return MunicipalSeries(values, coverage, institution, measure, municipality)
