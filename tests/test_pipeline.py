"""The pipes-and-filters framework and the treatment steps (synthetic data; rules 1-15)."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from etl.pipeline import Pipeline, ReportLine, StageFailed, StepResult, make_rejects, no_rejects, report_table
from etl.steps.acquire import RawInputs, VerifyRawInputs
from etl.steps.clean import (
    CollapseBulletins,
    OccurrenceAfterRegistration,
    OccurrenceWindow,
    ParseDates,
    TaxonomyCheck,
)


class _DropOdd:
    rule, action = "x", "exclude"

    def run(self, df):
        odd = df["v"] % 2 == 1
        rej = make_rejects(df[odd], stage="t", step="DropOdd", rule=self.rule, reason="odd", key=df.loc[odd, "v"])
        return StepResult(df[~odd], rej, [ReportLine("DropOdd", self.rule, self.action, len(df), int((~odd).sum()),
                                                     int(odd.sum()))])


class _Double:
    rule, action = "y", "fix"

    def run(self, df):
        return StepResult(df.assign(v=df["v"] * 2), no_rejects(), [ReportLine("Double", self.rule, self.action,
                                                                             len(df), len(df), len(df))])


def test_pipeline_chains_steps_and_collects_rejects():
    res = Pipeline("t", [_DropOdd(), _Double()]).run(pd.DataFrame({"v": [1, 2, 3, 4]}))
    assert res.kept["v"].tolist() == [4, 8]
    assert res.rejects["record_key"].tolist() == ["1", "3"]
    assert json.loads(res.rejects["record"].iloc[0]) == {"v": 1}
    assert [r.step for r in res.report] == ["DropOdd", "Double"]
    assert "| DropOdd | x | exclude | 4 | 2 | 2 |" in report_table(res.report)


def test_pipeline_is_itself_a_step():
    inner = Pipeline("t", [_DropOdd()])
    res = Pipeline("t", [inner, _Double()]).run(pd.DataFrame({"v": [1, 2]}))
    assert res.kept["v"].tolist() == [4] and len(res.rejects) == 1


def test_rule1_fails_on_changed_raw_file(tmp_path, monkeypatch):
    import etl.steps.acquire as acq

    monkeypatch.setattr(acq, "INPUTS_DIR", tmp_path)
    (tmp_path / "a.csv").write_text("x")
    with pytest.raises(StageFailed, match="rule 1"):
        VerifyRawInputs().run(RawInputs(checksums={"a.csv": "0" * 64}))
    with pytest.raises(StageFailed, match="missing"):
        VerifyRawInputs().run(RawInputs(checksums={"b.csv": "0" * 64}))


def _records(**cols):
    base = {"NUM_BO": ["1", "1", "2"], "ANO_BO": [2023, 2023, 2023], "NOME_DELEGACIA": ["D", "D", "D"],
            "NATUREZA_APURADA": ["Furto - Outros", "Lesão corporal - Dolosa", "Furto - Outros"]}
    base.update(cols)
    return pd.DataFrame(base)


def test_rule11_fails_on_unknown_offence():
    with pytest.raises(StageFailed, match="rule 11"):
        TaxonomyCheck().run(_records(NATUREZA_APURADA=["Something new", "Furto - Outros",
                                                       "Furto - Outros"]))


def test_rule9_rejects_merged_records_with_their_group():
    res = CollapseBulletins().run(_records())
    assert len(res.kept) == 2 and len(res.rejects) == 1
    rec = json.loads(res.rejects["record"].iloc[0])
    assert rec["crime_group"] == "bodily_harm" and res.rejects["rule"].iloc[0] == "9"


def test_rule12_window_excludes_and_counts():
    b = pd.DataFrame({"NUM_BO": list("abcd"), "ANO_BO": [2022] * 4, "NOME_DELEGACIA": ["D"] * 4,
                      "DATA_OCORRENCIA_BO": ["2021-12-31", "2022-01-01", "2025-12-31", "1202-02-28"],
                      "DATA_REGISTRO": ["2022-01-02"] * 4})
    parsed = ParseDates().run(b).kept
    res = OccurrenceWindow().run(parsed)
    assert res.kept["NUM_BO"].tolist() == ["b", "c"]
    assert sorted(res.rejects["reason"]) == ["occurrence date before 2022-01-01", "occurrence date missing or invalid"]


def test_rule13_reports_by_default_and_can_exclude():
    b = pd.DataFrame({"NUM_BO": ["a", "b"], "ANO_BO": [2022, 2022], "NOME_DELEGACIA": ["D", "D"],
                      "DATA_OCORRENCIA_BO": pd.to_datetime(["2022-03-01", "2022-03-05"]),
                      "DATA_REGISTRO": pd.to_datetime(["2022-03-02", "2022-03-04"])})
    rep = OccurrenceAfterRegistration().run(b)
    assert len(rep.kept) == 2 and rep.report[0].affected == 1 and len(rep.rejects) == 0
    exc = OccurrenceAfterRegistration("exclude").run(b)
    assert exc.kept["NUM_BO"].tolist() == ["a"] and exc.rejects["record_key"].tolist() == ["2022/b/D"]
