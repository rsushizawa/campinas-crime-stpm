"""The warehouse reader against the loaded release (needs `make db load`; skipped otherwise)."""
from __future__ import annotations

import pandas as pd
import pytest

from crime.core.config import DBConfig
from crime.data import CrimeQuery, Warehouse, WarehouseNotRunning, WarehouseVersionError


@pytest.fixture(scope="module")
def wh():
    return Warehouse()


def test_unreachable_database_says_how_to_start_it():      # rule 26: runs without a database
    with pytest.raises(WarehouseNotRunning, match="make db"):
        Warehouse(DBConfig(host="127.0.0.1", port=1))


@pytest.mark.db
def test_other_schema_version_is_refused(monkeypatch):
    import crime.data.warehouse as w

    monkeypatch.setattr(w, "SCHEMA_VERSION", "0.0.0")
    with pytest.raises(WarehouseVersionError):
        w.Warehouse()


@pytest.mark.db
def test_counts_are_long_and_zero_filled(wh):
    q = CrimeQuery(crime_group="violent", time_unit="quarter")
    c = wh.counts(q)
    assert len(c) == 2592 * 16
    assert c.groupby("census_tract_id").size().eq(16).all()
    assert c["census_tract_id"].is_monotonic_increasing
    assert (c["count"] == 0).mean() > 0.9                       # sparse group: most bins empty
    assert c.crs.to_epsg() == 31983


@pytest.mark.db
def test_request_matching_nothing_returns_zero_rows(wh):
    c = wh.counts(CrimeQuery(crime_slug=("roubo_banco",), start="2022-01-01", end="2022-01-01"))
    assert len(c) == 2592 and c["count"].sum() == 0               # rule 29


@pytest.mark.db
def test_city_series_includes_bulletins_without_coordinates(wh):
    city = wh.counts(CrimeQuery(unit="city", time_unit="year"))["count"].sum()
    tract = wh.counts(CrimeQuery())["count"].sum()
    assert city == 137323 and tract == 107859


@pytest.mark.db
def test_bulletins_and_counts_agree(wh):
    pts = wh.bulletins(CrimeQuery(crime_group="drug"))
    c = wh.counts(CrimeQuery(crime_group="drug"))
    assert len(pts) == c["count"].sum()
    assert pts["bulletin_id"].tolist() == sorted(pts["bulletin_id"])
    assert pd.api.types.is_datetime64_any_dtype(pts["occurrence_date"])


@pytest.mark.db
def test_unknown_location_type_is_an_error(wh):
    with pytest.raises(ValueError, match="unknown location_type"):
        wh.counts(CrimeQuery(location_type=("Via publica typo",)))
