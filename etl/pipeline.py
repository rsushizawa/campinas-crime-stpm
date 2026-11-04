"""Pipes-and-filters framework for the ETL treatments.

Every data treatment in ``etl/steps/`` is one :class:`Step`. A step receives
the table it works on and returns a :class:`StepResult` with three parts:

* ``kept``: the rows that continue down the pipeline (possibly modified),
* ``rejects``: the rows the step removed, one row each, with the rule that
  removed them and why,
* ``report``: one :class:`ReportLine` with the counts a reader needs to see
  what the step did.

A :class:`Pipeline` is a list of steps run in order, and is itself a step
(the Composite pattern), so a stage pipeline can be nested in a larger one.
The pipeline collects the reject rows of every step in one
:class:`RejectBuffer` and prints its report lines as one Markdown table.
Rejects are only buffered here; ``scripts/04_load`` writes them to the
``reject`` table of the warehouse once the database is loaded.

A step decides one of four outcomes for the rows it inspects (the treatment
table agreed for the paper, rules 1 to 30):

``fail``
    Raise :class:`StageFailed`. Used when the input cannot be trusted
    (changed raw files, an offence name nobody has classified, ...).
``fix``
    Change values with a fixed rule and count the rows changed.
``exclude``
    Move rows to ``rejects``; they leave the pipeline.
``report``
    Leave the rows as they are and count them, so the data profile shows
    how often the issue occurs.

Design references
-----------------
Garlan, D. & Shaw, M. (1993). An introduction to software architecture
    (pipes and filters).
Gamma, E., Helm, R., Johnson, R. & Vlissides, J. (1994). *Design Patterns*
    (Composite).
Kimball, R. & Caserta, J. (2004). *The Data Warehouse ETL Toolkit*, Wiley
    (error event table: one row per rejected record, with the screen that
    rejected it).
Rahm, E. & Do, H. H. (2000). Data cleaning: problems and current approaches.
    *IEEE Data Engineering Bulletin* 23(4).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import pandas as pd

Action = Literal["fail", "fix", "exclude", "report"]

#: Columns of a reject table, in the order the warehouse stores them.
REJECT_COLUMNS = ["stage", "step", "rule", "record_key", "reason", "record"]


class StageFailed(RuntimeError):
    """A ``fail`` rule fired. The message names the rule and the evidence."""


@dataclass(frozen=True)
class ReportLine:
    """What one step did, as one row of the stage report.

    Attributes
    ----------
    step : str
        Step name (the class name).
    rule : str
        Rule number(s) of the treatment table, e.g. ``"9"`` or ``"5-7"``.
    action : {"fail", "fix", "exclude", "report"}
        The treatment the rule applies.
    rows_in, rows_out : int
        Rows entering and leaving the step.
    affected : int
        Rows the rule touched: fixed, excluded, or only counted.
    note : str
        One short sentence with the numbers behind ``affected``.
    """

    step: str
    rule: str
    action: Action
    rows_in: int
    rows_out: int
    affected: int
    note: str = ""


@dataclass
class StepResult:
    """Output of :meth:`Step.run`.

    ``extra`` carries side tables a later stage or the load needs (for
    example the per-tract attribute table), keyed by name.
    """

    kept: Any
    rejects: pd.DataFrame
    report: list[ReportLine]
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Step(Protocol):
    """One treatment. ``rule`` and ``action`` refer to the treatment table."""

    rule: str
    action: Action

    def run(self, data: Any) -> StepResult: ...


def no_rejects() -> pd.DataFrame:
    """An empty reject frame with the standard columns."""
    return pd.DataFrame(columns=REJECT_COLUMNS)


def make_rejects(rows: pd.DataFrame, *, stage: str, step: str, rule: str, reason: str | pd.Series,
                 key: pd.Series) -> pd.DataFrame:
    """Reject frame for ``rows``.

    Parameters
    ----------
    rows : DataFrame
        The removed rows; each is serialised to JSON in ``record`` so the
        original values survive in the warehouse.
    stage, step, rule : str
        Where the rows were removed.
    reason : str or Series
        Why, per row or for all rows.
    key : Series
        Record key per row (bulletin key, address id, ...), aligned on ``rows``.
    """
    if len(rows) == 0:
        return no_rejects()
    records = rows.to_json(orient="records", date_format="iso", force_ascii=False)
    out = pd.DataFrame({
        "stage": stage, "step": step, "rule": rule,
        "record_key": key.astype(str).to_numpy(),
        "reason": reason.to_numpy() if isinstance(reason, pd.Series) else reason,
        "record": [json.dumps(r, ensure_ascii=False) for r in json.loads(records)],
    })
    return out[REJECT_COLUMNS]


class RejectBuffer:
    """Reject rows of a whole run, held in memory until the load writes them."""

    def __init__(self) -> None:
        self._parts: list[pd.DataFrame] = []

    def add(self, rejects: pd.DataFrame) -> None:
        if len(rejects):
            self._parts.append(rejects[REJECT_COLUMNS])

    def frame(self) -> pd.DataFrame:
        return pd.concat(self._parts, ignore_index=True) if self._parts else no_rejects()

    def save(self, path: str | Path) -> Path:
        """Write the buffer to a parquet file (the hand-over to the load stage)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.frame().to_parquet(path, index=False)
        return path


class Pipeline:
    """Run steps in order; a pipeline is itself a :class:`Step`.

    Parameters
    ----------
    stage : str
        Stage name stamped on the report (``acquire``, ``clean``, ...).
    steps : list of Step
        Run in the given order; each receives the ``kept`` output of the
        previous one.

    Examples
    --------
    >>> result = Pipeline("clean", [CollapseBulletins(), OccurrenceWindow()]).run(records)
    >>> print(report_table(result.report))
    """

    rule = "-"
    action: Action = "report"

    def __init__(self, stage: str, steps: list[Step]) -> None:
        self.stage = stage
        self.steps = steps

    def run(self, data: Any) -> StepResult:
        buffer, lines, extra = RejectBuffer(), [], {}
        for step in self.steps:
            res = step.run(data)
            buffer.add(res.rejects)
            lines.extend(res.report)
            extra.update(res.extra)
            data = res.kept
        return StepResult(kept=data, rejects=buffer.frame(), report=lines, extra=extra)


def report_table(lines: list[ReportLine]) -> str:
    """The report lines as a Markdown table (printed by every stage script)."""
    head = "| step | rule | action | rows in | rows out | affected | note |\n|---|---|---|---:|---:|---:|---|"
    body = [f"| {r.step} | {r.rule} | {r.action} | {r.rows_in:,} | {r.rows_out:,} | {r.affected:,} | {r.note} |"
            for r in lines]
    return "\n".join([head, *body])


def report_frame(lines: list[ReportLine]) -> pd.DataFrame:
    """The report lines as a DataFrame (saved next to the Markdown table)."""
    return pd.DataFrame([r.__dict__ for r in lines])
