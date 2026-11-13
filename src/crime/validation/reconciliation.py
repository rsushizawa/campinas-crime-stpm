"""Reconcile a Base dos Dados municipal census export with local tract totals.

The reference must be an export of br_ibge_populacao.municipio, not an
age/sex/race cross-tabulation whose overlapping categories would double count.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from crime.downloader.basedosdados import POPULATION_SQL
from crime.importer.basedosdados import MunicipalSeries


def compare_population(tracts: pd.DataFrame, reference: pd.DataFrame) -> dict:
    """Compare the complete Campinas tract population with one 2022 census row.

    Fail on missing local populations, duplicate tract IDs, wrong municipality,
    duplicate reference rows or invalid values instead of reporting a false pass.
    """
    ids = tracts['census_tract_id'].astype('string')
    if ids.isna().any() or ids.duplicated().any() or not ids.str.startswith('3509502').all():
        raise ValueError('Expected unique Campinas census tract IDs')
    local = pd.to_numeric(tracts['population'], errors='raise')
    if local.isna().any() or (local < 0).any() or (local % 1 != 0).any():
        raise ValueError('Local populations must be nonnegative integers with no missing values')
    years = pd.to_numeric(reference['ano'], errors='raise')
    rows = reference.loc[(years == 2022) & (reference['id_municipio'].astype('string') == '3509502')]
    if len(rows) != 1:
        raise ValueError('Expected exactly one Campinas 2022 population reference row')
    expected = float(pd.to_numeric(rows['populacao'], errors='raise').iloc[0])
    if not pd.notna(expected) or expected <= 0 or not expected.is_integer():
        raise ValueError('Reference population must be a positive integer')
    total = int(local.sum())
    return dict(status='match' if total == expected else 'mismatch',
                municipality='3509502', year=2022, n_tracts=len(tracts),
                local_population=total, reference_population=int(expected),
                difference=total-int(expected),
                scope='Municipal total only; does not validate individual tracts or police reports')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tracts', type=Path)
    parser.add_argument('--reference', type=Path, help='Base dos Dados CSV export')
    parser.add_argument('--print-sql', action='store_true')
    args = parser.parse_args(argv)
    if args.print_sql:
        print(POPULATION_SQL)
        return 0
    if args.tracts is None or args.reference is None:
        parser.error('--tracts and --reference are required unless --print-sql is used')
    ref = pd.read_csv(args.reference, dtype={'id_municipio': 'string'})
    result = compare_population(pd.read_parquet(args.tracts), ref)
    result['reference_sha256'] = hashlib.sha256(args.reference.read_bytes()).hexdigest()
    result['reference_table'] = 'basedosdados.br_ibge_populacao.municipio'
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'match' else 1


if __name__ == '__main__':
    raise SystemExit(main())


@dataclass(frozen=True)
class IndicatorMapping:
    """An author-reviewed mapping, not a guessed equivalence between taxonomies."""

    indicator: str
    crime_slugs: tuple[str, ...]
    definition_note: str

    def __post_init__(self):
        if not self.indicator or not self.crime_slugs or not self.definition_note.strip():
            raise ValueError('Supply indicator, primary-offence slugs and the reason they are comparable')
        if len(set(self.crime_slugs)) != len(self.crime_slugs):
            raise ValueError('A crosswalk must not repeat offence slugs')


def reconcile_reports(bulletins: pd.DataFrame, reference: MunicipalSeries,
                      mappings: list[IndicatorMapping], *, definitions_confirmed=False) -> pd.DataFrame:
    """Compare monthly primary-offence report counts, including unmapped reports.

    Matching totals is evidence of aggregate consistency, not coordinate or
    hotspot validation. Victim counts cannot be compared with bulletin counts.
    Missing reference observations never become zeros or matches.
    """
    if not definitions_confirmed:
        raise ValueError('Confirm date, primary-offence counting and category definitions before comparison')
    if reference.measure != 'quantidade_ocorrencias':
        raise ValueError('Victim counts cannot be reconciled against report counts')
    if reference.values.empty:
        raise ValueError('No reference months overlap the local release')
    if not mappings or len({m.indicator for m in mappings}) != len(mappings):
        raise ValueError('Supply at least one unique indicator mapping')
    date_col = 'occurrence_date' if 'occurrence_date' in bulletins else 'DATA_OCORRENCIA_BO'
    dates = pd.to_datetime(bulletins[date_col], errors='raise')
    if dates.isna().any():
        raise ValueError('Local occurrence dates must be present')
    # Data must be the canonical one-row-per-report set supplied by the generator.
    if 'bulletin_id' in bulletins and bulletins.bulletin_id.duplicated().any():
        raise ValueError('Local report IDs are duplicated')
    available = set(bulletins.crime_slug.dropna())
    rows = []
    for mapping in mappings:
        if mapping.indicator not in reference.values:
            raise ValueError(f'Unknown reference indicator: {mapping.indicator}')
        # Slugs absent in a period can correctly have zero reports; validate taxonomy instead.
        from crime.taxonomy import SLUG_TO_GROUP
        if unknown := set(mapping.crime_slugs) - (set(SLUG_TO_GROUP) | available):
            raise ValueError(f'Unknown local offence slugs: {sorted(unknown)}')
        selected = dates[bulletins.crime_slug.isin(mapping.crime_slugs)]
        local = selected.dt.to_period('M').dt.to_timestamp().value_counts().reindex(
            reference.values.index, fill_value=0).sort_index()
        ref = reference.values[mapping.indicator]
        result = pd.DataFrame({'period': ref.index, 'indicator': mapping.indicator,
                               'local_reports': local.to_numpy(), 'reference_count': ref.to_numpy(),
                               'coverage': reference.coverage[mapping.indicator].to_numpy()})
        result['difference'] = result.local_reports - result.reference_count
        result['difference_percent'] = 100 * result.difference / result.reference_count.replace(0, float('nan'))
        result['status'] = 'reference_unavailable'
        ok = result.reference_count.notna()
        result.loc[ok, 'status'] = 'different'
        result.loc[ok & result.difference.eq(0), 'status'] = 'match'
        result['institution'] = reference.institution
        result['measure'] = reference.measure
        result['definition_note'] = mapping.definition_note
        rows.append(result)
    return pd.concat(rows, ignore_index=True)
