"""Build complete, zero-filled cubes from treated bulletins."""
from __future__ import annotations

import numpy as np
import pandas as pd

from crime.models import CrimeDataset, CrimeQuery, SpaceTimeCube


def generate_cube(dataset: CrimeDataset, query: CrimeQuery | None = None) -> SpaceTimeCube:
    """Aggregate selected reports with every tract and time bin represented.

    City series retain reports without coordinates. Spatial series include only
    reports assigned to one of the dataset's tracts. Bins use occurrence dates.
    """
    query = query or CrimeQuery(time_unit='quarter')
    if query.time_unit == 'total':
        raise ValueError('A space-time cube requires month, quarter or year bins')
    b = dataset.bulletins
    date_col = 'occurrence_date' if 'occurrence_date' in b else 'DATA_OCORRENCIA_BO'
    slug_col = 'crime_slug'
    location_col = 'location_type' if 'location_type' in b else 'DESCR_SUBTIPOLOCAL'
    dates = pd.to_datetime(b[date_col])
    keep = dates.between(pd.Timestamp(query.start), pd.Timestamp(query.end))
    if query.crime_group != 'all':
        keep &= b.crime_group.eq(query.crime_group)
    if query.crime_slug:
        keep &= b[slug_col].isin(query.crime_slug)
    if query.location_type:
        unknown = set(query.location_type) - set(b[location_col].dropna())
        if unknown:
            raise ValueError(f'Unknown location types: {sorted(unknown)}')
        keep &= b[location_col].isin(query.location_type)
    if query.unit == 'census_tract':
        keep &= b.census_tract_id.notna()
        ids = tuple(sorted(dataset.tracts.census_tract_id.astype(str)))
        units = b.loc[keep, 'census_tract_id'].astype(str).to_numpy()
    else:
        ids = (dataset.config.municipality,)
        units = np.repeat(ids[0], int(keep.sum()))
    freq = {'month': 'M', 'quarter': 'Q', 'year': 'Y'}[query.time_unit]
    periods = pd.period_range(query.start, query.end, freq=freq).to_timestamp()
    selected = pd.DataFrame({'unit': units, 'period': dates[keep].dt.to_period(freq).dt.to_timestamp().to_numpy()})
    counts = selected.groupby(['unit', 'period']).size()
    full = pd.MultiIndex.from_product([ids, periods], names=['unit', 'period'])
    values = counts.reindex(full, fill_value=0).to_numpy(dtype=np.int64).reshape(len(ids), len(periods))
    return SpaceTimeCube(values, ids, periods, query.time_unit, query.crime_group,
                         dataset.config.crs, dataset.sources)
