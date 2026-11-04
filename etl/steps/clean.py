"""Stage 2, clean: offence records to one row per bulletin in the study window.

Treatment rules 9 to 15. The stage runs as::

    from etl.steps.clean import clean_pipeline
    result = clean_pipeline().run(records)     # records: sources.extract_crimes()

``result.kept`` is the bulletin table the warehouse fact table is built from:
one row per ``NUM_BO + ANO_BO + NOME_DELEGACIA`` whose occurrence date lies in
2022-01-01 to 2025-12-31. Bulletins without a usable coordinate stay in the
table; they are part of the monthly series and leave only the spatial event
set (rule 17, units stage).
"""
from __future__ import annotations

import pandas as pd

from crime.core import taxonomy
from crime.core.config import DATE_END, DATE_START
from etl.clean import BULLETIN_KEY, collapse_bulletins, group_transitions
from etl.pipeline import Pipeline, ReportLine, StageFailed, StepResult, make_rejects, no_rejects

STAGE = "clean"


def bulletin_key(df: pd.DataFrame) -> pd.Series:
    """``"ANO_BO/NUM_BO/NOME_DELEGACIA"``: the bulletin identifier used everywhere downstream."""
    return (df["ANO_BO"].astype("string") + "/" + df["NUM_BO"].astype("string") + "/"
            + df["NOME_DELEGACIA"].astype("string")).astype(str)


class TaxonomyCheck:
    """Rule 11 (fail): every ``NATUREZA_APURADA`` must map to a slug in :mod:`crime.core.taxonomy`.

    A new offence name needs a person to decide its crime group and maximum
    penalty, so the run stops and lists the names.
    """

    rule, action = "11", "fail"

    def run(self, records: pd.DataFrame) -> StepResult:
        slug = records["NATUREZA_APURADA"].map(taxonomy.to_slug)
        unmapped = records.loc[slug.isna(), "NATUREZA_APURADA"].value_counts()
        if len(unmapped):
            raise StageFailed("rule 11, offence names missing from crime.core.taxonomy:\n  "
                              + "\n  ".join(f"{k!r}: {v} record(s)" for k, v in unmapped.items()))
        n = len(records)
        return StepResult(records, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, n, n, 0,
            f"{records['NATUREZA_APURADA'].nunique()} offence names, all in the taxonomy")])


class CollapseBulletins:
    """Rules 9 and 10 (fix): one row per bulletin, keeping its most serious offence.

    A bulletin listing several offences appears once per offence. The record
    with the highest maximum penalty is kept, a specific slug beating a
    ``*_outros`` slug on a tie, then source order (:func:`etl.clean.collapse_bulletins`;
    penalty table :data:`crime.core.taxonomy.MAX_PENALTY`). The other records go to
    ``rejects`` with their own slug and group, so the funnel can still count
    offence records per group. Exact duplicate rows (rule 10) are a special
    case of the same collapse and are counted separately.
    """

    rule, action = "9-10", "fix"

    def run(self, records: pd.DataFrame) -> StepResult:
        src = records.assign(_src=range(len(records)))
        kept, rep = collapse_bulletins(src)
        rep["exact_duplicate_rows"] = int(records.duplicated().sum())   # the _src column makes every row unique
        removed = src[~src["_src"].isin(kept["_src"])].drop(columns="_src")
        removed = removed.assign(crime_slug=removed["NATUREZA_APURADA"].map(taxonomy.to_slug))
        removed = removed.assign(crime_group=removed["crime_slug"].map(taxonomy.SLUG_TO_GROUP))
        rejects = make_rejects(removed, stage=STAGE, step=type(self).__name__, rule="9",
                               reason="offence record merged into its bulletin; a more serious offence was kept",
                               key=bulletin_key(removed))
        kept = kept.drop(columns="_src")
        trans = group_transitions(records, kept)
        moved = trans[trans["groups_present"] != trans["kept_group"]]
        rep["multi_group_bulletins"] = int(moved["bulletins"].sum())
        prop_had = trans[trans["groups_present"].str.contains("property")]
        rep["bulletins_with_property_record_kept_as_other_group"] = {
            f"{r.groups_present} -> {r.kept_group}": int(r.bulletins)
            for r in prop_had[prop_had["kept_group"] != "property"].itertuples()}
        return StepResult(kept, rejects, [ReportLine(
            type(self).__name__, self.rule, self.action, len(records), len(kept), rep["rows_removed"],
            f"{rep['multi_record_bulletins']:,} bulletins had several records; "
            f"{rep['exact_duplicate_rows']} exact duplicate; {rep['residual_tie_groups_first_kept']} ties kept first")],
            extra={"dedup_report": rep, "dedup_group_transitions": trans})


class ParseDates:
    """Rule 12, first part (fix): occurrence and registration dates as dates.

    An occurrence date that is not a valid calendar date (``'1202-02-28'``
    once) becomes missing and is then excluded by :class:`OccurrenceWindow`.
    """

    rule, action = "12", "fix"

    def run(self, b: pd.DataFrame) -> StepResult:
        out = b.copy()
        occ = pd.to_datetime(out["DATA_OCORRENCIA_BO"], errors="coerce", format="%Y-%m-%d")
        bad = out.loc[occ.isna() & out["DATA_OCORRENCIA_BO"].notna(), "DATA_OCORRENCIA_BO"].astype(str)
        out["DATA_OCORRENCIA_BO"] = occ
        out["DATA_REGISTRO"] = pd.to_datetime(out["DATA_REGISTRO"], errors="coerce")
        return StepResult(out, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, len(b), len(out), len(bad),
            f"{len(bad)} occurrence date(s) not a calendar date: {', '.join(sorted(set(bad))) or 'none'}")],
            extra={"unparseable_occurrence_dates": bad.value_counts().to_dict()})


class OccurrenceWindow:
    """Rule 12 (exclude): occurrence date missing or outside 2022-01-01 to 2025-12-31.

    Bulletins registered in 2022 or later for events that happened earlier
    are the bulk of these rows. They go to ``rejects`` with their crime group.
    """

    rule, action = "12", "exclude"

    def run(self, b: pd.DataFrame) -> StepResult:
        occ = b["DATA_OCORRENCIA_BO"]
        inside = occ.ge(pd.Timestamp(DATE_START)) & occ.lt(pd.Timestamp(DATE_END) + pd.Timedelta(days=1))
        out = b[inside]
        why = pd.Series("occurrence date before 2022-01-01", index=b.index)
        why[occ.isna()] = "occurrence date missing or invalid"
        why[occ.ge(pd.Timestamp(DATE_END) + pd.Timedelta(days=1))] = "occurrence date after 2025-12-31"
        drop = b[~inside]
        rejects = make_rejects(drop, stage=STAGE, step=type(self).__name__, rule=self.rule,
                               reason=why[~inside], key=bulletin_key(drop))
        counts = why[~inside].value_counts()
        return StepResult(out.reset_index(drop=True), rejects, [ReportLine(
            type(self).__name__, self.rule, self.action, len(b), len(out), int((~inside).sum()),
            "; ".join(f"{k}: {v:,}" for k, v in counts.items()))])


class OccurrenceAfterRegistration:
    """Rule 13: occurrence date later than the registration date.

    A bulletin cannot be registered before the event happened, so these rows
    carry a data-entry error in one of the two dates. They are kept and
    counted (author decision, 2026-11-04): excluding 6 bulletins would change
    counts the paper reports for no material gain. ``action="exclude"`` moves
    them to ``rejects`` instead.
    """

    rule = "13"

    def __init__(self, action: str = "report") -> None:
        if action not in ("report", "exclude"):
            raise ValueError("action must be 'report' or 'exclude'")
        self.action = action

    def run(self, b: pd.DataFrame) -> StepResult:
        bad = b["DATA_OCORRENCIA_BO"].gt(b["DATA_REGISTRO"])
        rejects, out = no_rejects(), b
        if self.action == "exclude":
            rejects = make_rejects(b[bad], stage=STAGE, step=type(self).__name__, rule=self.rule,
                                   reason="occurrence date after registration date", key=bulletin_key(b[bad]))
            out = b[~bad].reset_index(drop=True)
        return StepResult(out, rejects, [ReportLine(
            type(self).__name__, self.rule, self.action, len(b), len(out), int(bad.sum()),
            f"{int(bad.sum())} bulletin(s) dated after their registration")])


class ReportingLag:
    """Rule 14 (report): days from occurrence to registration.

    Bulletins registered after the data were extracted are missing, so the
    last months of the series can be undercounted. The step reports the
    distribution of the delay; the paper discloses it.
    """

    rule, action = "14", "report"

    def run(self, b: pd.DataFrame) -> StepResult:
        d = (b["DATA_REGISTRO"] - b["DATA_OCORRENCIA_BO"]).dt.days
        q = d.quantile([0.5, 0.9, 0.99])
        late = int((d > 30).sum())
        return StepResult(b, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, len(b), len(b), late,
            f"delay days median {q[0.5]:.0f}, p90 {q[0.9]:.0f}, p99 {q[0.99]:.0f}; {late:,} registered > 30 days later; "
            f"last registration {b['DATA_REGISTRO'].max():%Y-%m-%d}")])


class StackedGeocodes:
    """Rule 15 (report): bulletins sharing an identical published coordinate.

    Street-level geocoding puts many bulletins on one point. They are kept;
    the step counts them so the share is visible (notebook 01 has the detail).
    """

    rule, action = "15", "report"

    def run(self, b: pd.DataFrame) -> StepResult:
        xy = b.dropna(subset=["LATITUDE", "LONGITUDE"])
        stacked = xy.duplicated(["LATITUDE", "LONGITUDE"], keep=False)
        largest = int(xy.groupby(["LATITUDE", "LONGITUDE"]).size().max()) if len(xy) else 0
        return StepResult(b, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, len(b), len(b), int(stacked.sum()),
            f"{int(stacked.sum()):,} of {len(xy):,} geocoded bulletins share a coordinate; largest stack {largest:,}")])


def clean_pipeline(after_registration: str = "report") -> Pipeline:
    """Rules 9 to 15, in the order they apply."""
    return Pipeline(STAGE, [TaxonomyCheck(), CollapseBulletins(), ParseDates(), OccurrenceWindow(),
                            OccurrenceAfterRegistration(after_registration), ReportingLag(), StackedGeocodes()])


__all__ = ["BULLETIN_KEY", "bulletin_key", "clean_pipeline"]
