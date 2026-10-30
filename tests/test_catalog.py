"""crime.data.catalog: counts are derived from data, never typed in."""
from __future__ import annotations

import pandas as pd

from crime.data import catalog


def test_tier_threshold():
    assert catalog.tier(100) == "esda"
    assert catalog.tier(99) == "excluded"


def test_slug_counts_from_bulletins(tmp_path):
    b = pd.DataFrame({
        "crime_slug": ["furto_outros", "furto_outros", "furto_outros", "roubo_outros"],
        "DATA_OCORRENCIA_BO": pd.to_datetime(["2022-05-01", "2024-02-01", None, "2023-01-01"]),
        "LATITUDE": [-22.9, -22.9, -22.9, None],      # roubo_outros has no coordinate -> not in fato_crimes
        "LONGITUDE": [-47.0, -47.0, -47.0, None],
    })
    p = tmp_path / "b.parquet"
    b.to_parquet(p)
    assert catalog.slug_counts(p) == {"furto_outros": 3}


def test_readiness_lists_every_scoped_slug_with_zero_default():
    t = catalog.readiness_table(counts={"furto_outros": 400})
    assert set(t["crime_slug"]) == set(catalog.ESDA_SLUGS + catalog.EXCLUDED_SLUGS)
    assert len(catalog.ESDA_SLUGS) == 16 and not set(catalog.ESDA_SLUGS) & set(catalog.EXCLUDED_SLUGS)
    row = t.set_index("crime_slug").loc["roubo_outros"]
    assert (row.total_n, row.tier_now, row.status) == (0, "excluded", "esda")
