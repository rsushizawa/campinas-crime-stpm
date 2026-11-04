"""Stage 1, acquire: raw SSP-SP extracts to one Campinas table of offence records.

Treatment rules 1 to 8. The rule functions themselves live in
:mod:`etl.acquire`; each step below applies one of them and reports what it
changed. The stage runs as::

    from etl.steps.acquire import acquire_pipeline
    result = acquire_pipeline().run(RawInputs())

Input is a :class:`RawInputs` (paths). Output (``result.kept``) is the offence
record table written to ``outputs/data/crimes_campinas.csv``.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from crime.core.config import INPUTS_DIR, SSP_CSV_2022_2024, SSP_XLSX_2025
from etl import acquire
from etl.pipeline import Pipeline, ReportLine, StageFailed, StepResult, make_rejects, no_rejects

STAGE = "acquire"
#: Expected SHA-256 of every raw input (``inputs/data/SHA256SUMS``).
SHA256SUMS = INPUTS_DIR / "SHA256SUMS"


def sha256(path: str | Path) -> str:
    """SHA-256 of a file, read in 1 MiB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_checksums(path: Path = SHA256SUMS) -> dict[str, str]:
    """``inputs/data/SHA256SUMS`` as ``{relative path: sha256}`` (``sha256sum`` format)."""
    out = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            digest, name = line.split(maxsplit=1)
            out[name.strip().lstrip("*")] = digest
    return out


@dataclass(frozen=True)
class RawInputs:
    """Paths of the two SSP-SP raw extracts, and the files whose checksums are verified."""

    csv_2022_2024: Path = SSP_CSV_2022_2024
    xlsx_2025: Path = SSP_XLSX_2025
    checksums: dict[str, str] = field(default_factory=expected_checksums)


@dataclass
class _Sources:
    """The two raw tables after reading (internal hand-over between steps)."""

    csv: pd.DataFrame
    xlsx: pd.DataFrame
    report: dict


class VerifyRawInputs:
    """Rule 1 (fail): every raw input must match its recorded SHA-256.

    A changed or missing file means the data no longer match the release the
    paper reports, so the run stops. Checksums come from
    ``inputs/data/SHA256SUMS``; the same values are in ``docs/data/``.
    """

    rule, action = "1", "fail"

    def run(self, raw: RawInputs) -> StepResult:
        bad = []
        for name, digest in raw.checksums.items():
            p = INPUTS_DIR / name
            if not p.exists():
                bad.append(f"{name}: missing")
            elif sha256(p) != digest:
                bad.append(f"{name}: SHA-256 differs from SHA256SUMS")
        if bad:
            raise StageFailed("rule 1, raw inputs changed:\n  " + "\n  ".join(bad))
        n = len(raw.checksums)
        return StepResult(raw, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, n, n, 0, f"{n} raw files match SHA256SUMS")])


class ReadSources:
    """Rule 2 (fail): read both extracts with an explicit column list.

    :func:`etl.acquire.read_2022_2024` and :func:`etl.acquire.read_2025_xlsx`
    raise if any of the 25 expected columns is missing, so a renamed column
    stops the run instead of being guessed. The 2025 file is statewide; only
    rows that some Campinas field selects are kept for the next step.
    """

    rule, action = "2", "fail"

    def run(self, raw: RawInputs) -> StepResult:
        try:
            a = acquire.read_2022_2024(raw.csv_2022_2024)
            b = acquire.read_2025_xlsx(raw.xlsx_2025)
        except ValueError as exc:
            raise StageFailed(f"rule 2, raw columns changed: {exc}") from exc
        rep = {"rows_read": {"2022_2024_csv": int(len(a)),
                             "2025_xlsx_statewide": int(b.attrs["rows_read_statewide"]),
                             "2025_xlsx_campinas_candidates": int(len(b))}}
        n_in = rep["rows_read"]["2022_2024_csv"] + rep["rows_read"]["2025_xlsx_statewide"]
        n_out = len(a) + len(b)
        return StepResult(_Sources(a, b, rep), no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, n_in, n_out, 0,
            f"{len(a):,} rows 2022-2024 csv; {len(b):,} Campinas candidates of "
            f"{rep['rows_read']['2025_xlsx_statewide']:,} statewide 2025 rows")])


class MunicipalityFilter:
    """Rule 3 (report): keep ``NOME_MUNICIPIO_CIRCUNSCRICAO == "CAMPINAS"``.

    The jurisdiction of the place of the fact is the one filter that both
    files support (the 2022-2024 extract holds no other municipality). In the
    2025 file the registration municipality disagrees with it on a few rows;
    rows selected only by the registration municipality go to ``rejects`` and
    the disagreement is counted in both directions.
    """

    rule, action = "3", "report"

    def run(self, src: _Sources) -> StepResult:
        a, b, rep = src.csv, src.xlsx, dict(src.report)
        circ, muni = acquire.municipality_mask(b), acquire.municipality_mask(b, "NOME_MUNICIPIO")
        rep["filter"] = f"{acquire.MUNICIPALITY_COL} == {acquire.MUNICIPALITY!r}"
        rep["xlsx_filter_comparison"] = {
            "circunscricao_campinas": int(circ.sum()), "registro_campinas": int(muni.sum()),
            "cd_ibge_3509502": int(b["CD_IBGE"].eq("3509502").sum()),
            "both": int((circ & muni).sum()),
            "circunscricao_only_kept": int((circ & ~muni).sum()),
            "registro_only_dropped": int((muni & ~circ).sum()),
        }
        rep["filter_diff_rows"] = pd.concat([
            b[circ & ~muni].assign(FILTER_DIFF="kept: circunscricao only"),
            b[muni & ~circ].assign(FILTER_DIFF="dropped: registro only"),
        ])[["FILTER_DIFF", "NUM_BO", "ANO_BO", "NOME_DELEGACIA", "NOME_MUNICIPIO", acquire.MUNICIPALITY_COL,
            "NATUREZA_APURADA", "LATITUDE", "LONGITUDE"]]
        a_circ = acquire.municipality_mask(a)
        rep["csv_rows_failing_filter"] = int((~a_circ).sum())
        dropped = pd.concat([a[~a_circ], b[muni & ~circ].drop(columns="CD_IBGE")])
        why = pd.Series(["2022-2024 extract: jurisdiction of the fact is not Campinas"] * int((~a_circ).sum())
                        + ["registration municipality is Campinas, jurisdiction of the fact is not"]
                        * int((muni & ~circ).sum()), index=dropped.index)
        rejects = make_rejects(dropped, stage=STAGE, step=type(self).__name__, rule=self.rule, reason=why,
                               key=dropped["ANO_BO"].astype(str) + "/" + dropped["NUM_BO"].astype(str) + "/"
                               + dropped["NOME_DELEGACIA"].astype(str))
        df = pd.concat([a[a_circ], b[circ].drop(columns="CD_IBGE")], ignore_index=True)
        rep["rows_after_filter"] = {"2022_2024_csv": int(a_circ.sum()), "2025_xlsx": int(circ.sum()),
                                    "total": int(len(df))}
        c = rep["xlsx_filter_comparison"]
        return StepResult(df, rejects, [ReportLine(
            type(self).__name__, self.rule, self.action, len(a) + len(b), len(df),
            c["circunscricao_only_kept"] + c["registro_only_dropped"],
            f"2025: {c['circunscricao_only_kept']} kept on jurisdiction only, "
            f"{c['registro_only_dropped']} dropped on registration only")], extra={"acquire_report": rep})


class NormaliseMissing:
    """Rule 4 (fix): strip whitespace; ``''``, ``'NULL'`` and ``'NUL,L'`` become missing.

    The redaction text ``VEDAÇÃO DA DIVULGAÇÃO DOS DADOS RELATIVOS`` is kept in
    text columns, since it records that the field was withheld
    (:func:`etl.acquire.normalise_missing`).
    """

    rule, action = "4", "fix"

    def run(self, df: pd.DataFrame) -> StepResult:
        out, rep = acquire.normalise_missing(df)
        n_cells = sum(rep["tokens_to_missing"].values())
        return StepResult(out, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, len(df), len(out), n_cells,
            f"{n_cells:,} cells set missing; {rep['cells_whitespace_stripped']:,} cells stripped")],
            extra={"acquire_report_missing": rep})


class ParseCoordinates:
    """Rules 5 to 7 (fix): numeric coordinates and a ``COORD_STATUS`` flag.

    ``(0, 0)`` becomes missing (rule 5); a missing decimal point is repaired
    when the repaired point falls in the Campinas box (rule 6, flagged
    ``fixed_decimal``); anything outside the box stays missing (rule 7,
    ``invalid``). Rows are kept: a bulletin without a usable coordinate still
    counts in the monthly series, and only leaves the spatial event set
    (:func:`etl.acquire.parse_coordinates`).
    """

    rule, action = "5-7", "fix"

    def run(self, df: pd.DataFrame) -> StepResult:
        out, status = acquire.parse_coordinates(df)
        unusable = sum(v for k, v in status.items() if k not in ("ok", "fixed_decimal"))
        return StepResult(out, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, len(df), len(out), unusable + status.get("fixed_decimal", 0),
            "; ".join(f"{k} {v:,}" for k, v in status.items()))], extra={"acquire_report_coords": status})


class NormaliseHour:
    """Rule 8 (fix): occurrence hour written ``HH:MM`` (:func:`etl.acquire.normalise_hour`).

    The hour is not analysed in the paper; it is kept so the bulletin record is
    complete.
    """

    rule, action = "8", "fix"

    def run(self, df: pd.DataFrame) -> StepResult:
        out = df.copy()
        out["HORA_OCORRENCIA_BO"], rep = acquire.normalise_hour(df["HORA_OCORRENCIA_BO"])
        out = out[acquire.COLUMNS + ["COORD_STATUS", "SOURCE"]]
        return StepResult(out, no_rejects(), [ReportLine(
            type(self).__name__, self.rule, self.action, len(df), len(out), rep["hour_reformatted"],
            f"{rep['hour_reformatted']:,} reformatted; {rep['hour_nonzero_seconds']:,} had seconds; "
            f"{rep['hour_unparsed_kept']} unparsed")], extra={"acquire_report_hours": rep})


def acquire_pipeline() -> Pipeline:
    """Rules 1 to 8, in the order they apply."""
    return Pipeline(STAGE, [VerifyRawInputs(), ReadSources(), MunicipalityFilter(), NormaliseMissing(),
                            ParseCoordinates(), NormaliseHour()])


def acquire_report(extra: dict) -> dict:
    """The JSON acquire report (same keys as before the pipeline refactor)."""
    rep = dict(extra["acquire_report"])
    rep.update(extra["acquire_report_missing"])
    rep["coord_status"] = extra["acquire_report_coords"]
    rep.update(extra["acquire_report_hours"])
    return rep
