"""crime.data.catalog: counts are derived from data, never typed in."""
from __future__ import annotations

import pandas as pd

from crime.data import catalog


def test_tier_thresholds():
    assert catalog.tier(100, 100, 200) == "classifier"
    assert catalog.tier(99, 500, 599) == "esda_only"
    assert catalog.tier(10, 20, 99) == "excluded"


def test_slug_counts_from_bulletins(tmp_path):
    b = pd.DataFrame({
        "crime_slug": ["furto_outros", "furto_outros", "furto_outros", "roubo_outros"],
        "DATA_OCORRENCIA_BO": pd.to_datetime(["2022-05-01", "2024-02-01", None, "2023-01-01"]),
        "LATITUDE": [-22.9, -22.9, -22.9, None],      # roubo_outros has no coordinate -> not in fato_crimes
        "LONGITUDE": [-47.0, -47.0, -47.0, None],
    })
    p = tmp_path / "b.parquet"
    b.to_parquet(p)
    assert catalog.slug_counts(p) == {"furto_outros": (1, 1, 3)}


def test_readiness_lists_every_scoped_slug_with_zero_default():
    t = catalog.readiness_table(counts={"furto_outros": (200, 200, 400)})
    assert set(t["crime_slug"]) == set(catalog.ESDA_SLUGS + catalog.EXCLUDED_SLUGS)
    row = t.set_index("crime_slug").loc["roubo_outros"]
    assert (row.total_n, row.tier_now, row.status) == (0, "excluded", "classifier")
