"""pandera checks of stage 5 on synthetic warehouse rows."""
from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("pandera")
from etl import schemas  # noqa: E402

FUNNEL = [{"stage": "occurrence date in window", "all": 2, "property": 1, "definition": ""}]


def _fact():
    return pd.DataFrame({"bulletin_id": ["2022/1/D", "2022/2/D"],
                         "occurrence_date": pd.to_datetime(["2022-01-05", "2025-12-31"]),
                         "crime_slug": ["furto_outros", "trafico_entorpecente"], "coord_status": ["ok", "missing"],
                         "latitude": [-22.9, None], "longitude": [-47.06, None]})


def test_valid_rows_pass():
    schemas.validate(schemas.fact_schema(FUNNEL), _fact())


@pytest.mark.parametrize("plant", [
    lambda d: d.assign(bulletin_id=["x", "x"]),                                   # key not unique
    lambda d: d.assign(occurrence_date=pd.to_datetime(["2021-12-31", "2022-01-01"])),   # outside window
    lambda d: d.assign(crime_slug=["furto_outros", "unknown"]),                   # slug not in taxonomy
    lambda d: d.assign(coord_status=["missing", "missing"]),                      # coordinate without ok status
    lambda d: d.assign(latitude=[0.0, None], longitude=[0.0, None]),              # (0, 0) and out of the box
    lambda d: d.iloc[:1],                                                         # row count != funnel
])
def test_planted_violation_fails(plant):
    with pytest.raises(AssertionError):
        schemas.validate(schemas.fact_schema(FUNNEL), plant(_fact()))
