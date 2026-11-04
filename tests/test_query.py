"""The pydantic request model (rule 28: an invalid request fails before any database call)."""
from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from crime.data import CrimeQuery


def test_defaults_are_the_study_window_per_tract_total():
    q = CrimeQuery()
    assert (q.crime_group, q.unit, q.time_unit) == ("all", "census_tract", "total")
    assert (q.start, q.end) == (dt.date(2022, 1, 1), dt.date(2025, 12, 31))


def test_single_slug_and_location_type_become_tuples():
    q = CrimeQuery(crime_group="property", crime_slug="furto_veiculo", location_type="Via pública")
    assert q.crime_slug == ("furto_veiculo",) and q.location_type == ("Via pública",)


@pytest.mark.parametrize("kw", [
    {"crime_group": "theft"},                                     # unknown group
    {"time_unit": "week"},                                        # unknown time unit
    {"crime_slug": ("not_a_slug",)},                              # unknown slug
    {"crime_group": "drug", "crime_slug": ("furto_veiculo",)},    # slug outside the group
    {"start": "2021-06-01"},                                      # outside the study window
    {"start": "2024-01-01", "end": "2023-01-01"},                 # start after end
    {"crime_group": "sexual"},                                    # no coordinates: per tract is impossible
    {"bogus": 1},                                                 # unknown field
])
def test_invalid_requests_fail(kw):
    with pytest.raises(ValidationError):
        CrimeQuery(**kw)


def test_query_is_frozen():
    with pytest.raises(ValidationError):
        CrimeQuery().crime_group = "drug"
