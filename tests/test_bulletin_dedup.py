"""Known-answer tests for the one-row-per-bulletin rule (etl.clean / crime.core.taxonomy.MAX_PENALTY)."""
from __future__ import annotations

import pandas as pd
import pytest

from crime.core import taxonomy
from etl.clean import collapse_bulletins


def _records(rows):
    return pd.DataFrame(rows, columns=["NUM_BO", "ANO_BO", "NOME_DELEGACIA", "NATUREZA_APURADA"])


def test_every_taxonomy_slug_has_a_penalty():
    assert set(taxonomy.MAX_PENALTY) == set(taxonomy.NATUREZA_TO_SLUG.values())


def test_highest_maximum_penalty_is_kept():
    df = _records([("1", 2023, "D1", "Furto - Outros"), ("1", 2023, "D1", "Roubo - Outros"),
                   ("2", 2023, "D1", "Lesão Corporal Dolosa"), ("2", 2023, "D1", "Homicídio Doloso")])
    out, rep = collapse_bulletins(df)
    assert out.set_index("NUM_BO")["crime_slug"].to_dict() == {"1": "roubo_outros", "2": "homicidio_doloso"}
    assert rep["bulletins_out"] == 2 and rep["rows_removed"] == 2


def test_furto_plus_lesao_stays_property():
    df = _records([("7", 2022, "D", "Lesão Corporal Dolosa"), ("7", 2022, "D", "Furto - Outros")])
    out, _ = collapse_bulletins(df)
    assert out.loc[0, "crime_slug"] == "furto_outros" and out.loc[0, "crime_group"] == "property"
    assert out.loc[0, "n_records"] == 2
    assert out.loc[0, "slugs_on_bulletin"] == "furto_outros|lesao_corporal_dolosa"


def test_tie_specific_slug_beats_outros():
    # roubo_outros and roubo_veiculo both have 10 years; the specific one wins, in either order
    for order in ([("9", 2024, "D", "Roubo - Outros"), ("9", 2024, "D", "Roubo - Veículo")],
                  [("9", 2024, "D", "ROUBO DE VEÍCULO"), ("9", 2024, "D", "ROUBO - OUTROS")]):
        out, rep = collapse_bulletins(_records(order))
        assert out.loc[0, "crime_slug"] == "roubo_veiculo"
        assert rep["residual_tie_groups_first_kept"] == 0


def test_residual_tie_keeps_first_and_is_reported():
    df = _records([("5", 2024, "D", "Roubo - Carga"), ("5", 2024, "D", "Roubo - Veículo")])
    out, rep = collapse_bulletins(df)
    assert out.loc[0, "crime_slug"] == "roubo_carga"
    assert rep["residual_tie_groups_first_kept"] == 1


def test_key_includes_police_station():
    df = _records([("3", 2023, "D1", "Furto - Outros"), ("3", 2023, "D2", "Roubo - Outros")])
    out, _ = collapse_bulletins(df)
    assert len(out) == 2


def test_exact_duplicates_collapse_and_are_counted():
    df = _records([("4", 2023, "D", "Furto - Outros")] * 2)
    out, rep = collapse_bulletins(df)
    assert len(out) == 1 and rep["exact_duplicate_rows"] == 1


def test_seizure_ranks_lowest_and_unmapped_below_it():
    df = _records([("6", 2023, "D", "Apreensão de entorpecentes"), ("6", 2023, "D", "Porte de entorpecentes"),
                   ("8", 2023, "D", "Something new"), ("8", 2023, "D", "Apreensão de entorpecentes")])
    out, rep = collapse_bulletins(df)
    assert out.set_index("NUM_BO")["crime_slug"].to_dict() == {"6": "porte_entorpecente",
                                                               "8": "apreensao_entorpecente"}
    assert rep["unmapped_natureza"] == {"Something new": 1}


def test_slug_without_penalty_raises(monkeypatch):
    monkeypatch.setitem(taxonomy.NATUREZA_TO_SLUG, "novo_crime", "novo_crime")
    with pytest.raises(KeyError, match="MAX_PENALTY"):
        collapse_bulletins(_records([("1", 2023, "D", "Novo crime")]))
