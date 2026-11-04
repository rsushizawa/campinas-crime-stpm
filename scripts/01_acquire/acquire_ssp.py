"""Stage 1, acquire: raw SSP-SP extracts to outputs/data/crimes_campinas.csv (``make acquire``).

    python scripts/01_acquire/acquire_ssp.py

Runs :func:`etl.steps.acquire.acquire_pipeline` (rules 1 to 8) and writes the
offence-record table, ``acquire_report.json`` and a row-for-row comparison
with the hand-assembled legacy ``inputs/data/crimes_campinas.csv`` (commit
6891c8b). Rejected rows and the stage report go to ``outputs/data/staging/acquire/``.
"""
import json

import pandas as pd

from crime.core.config import CRIMES_CSV, LEGACY_CRIMES_CSV, OUTPUT_DATA_DIR, SSP_CSV_2022_2024, SSP_XLSX_2025
from etl import acquire
from etl.stage_io import save_stage
from etl.steps.acquire import STAGE, RawInputs, acquire_pipeline, acquire_report, sha256


def _row_hash(df: pd.DataFrame) -> pd.Series:
    d = df[acquire.COLUMNS].copy()
    for c in ("LATITUDE", "LONGITUDE"):
        d[c] = d[c].round(9)
    return pd.util.hash_pandas_object(d.astype("string").fillna("<NA>"), index=False)


def compare_with_legacy(new: pd.DataFrame) -> dict:
    """Apply the same acquire rules to the legacy CSV, then match rows as a multiset."""
    leg = pd.read_csv(LEGACY_CRIMES_CSV, sep=";", dtype=str, keep_default_na=False, na_values=[])
    leg_raw_n = len(leg)
    leg, _ = acquire.normalise_missing(leg)
    leg, leg_coords = acquire.parse_coordinates(leg)
    leg["HORA_OCORRENCIA_BO"], _ = acquire.normalise_hour(leg["HORA_OCORRENCIA_BO"])
    hn, hl = _row_hash(new), _row_hash(leg)
    cn, cl = hn.value_counts(), hl.value_counts()
    both = cn.index.intersection(cl.index)
    matched = int(pd.concat([cn[both], cl[both]], axis=1).min(axis=1).sum())
    only_new = new[hn.isin(cn.index.difference(cl.index))]
    only_leg = leg[hl.isin(cl.index.difference(cn.index))]
    def _summ(d):
        return {"rows": int(len(d)),
                "by_NOME_MUNICIPIO": d["NOME_MUNICIPIO"].value_counts().to_dict(),
                "by_NOME_MUNICIPIO_CIRCUNSCRICAO": d["NOME_MUNICIPIO_CIRCUNSCRICAO"].value_counts().to_dict(),
                "by_ANO_ESTATISTICA": d["ANO_ESTATISTICA"].value_counts().to_dict()}
    return {"legacy_rows": leg_raw_n, "new_rows": int(len(new)), "rows_identical_after_same_rules": matched,
            "only_in_new": _summ(only_new), "only_in_legacy": _summ(only_leg),
            "legacy_coord_status_under_same_rules": leg_coords,
            "note": "Both files normalised with etl.acquire rules (missing tokens, coordinates, HH:MM) "
                    "before matching all 25 columns as a multiset."}


def main() -> None:
    result = acquire_pipeline().run(RawInputs())
    df = result.kept
    report = acquire_report(result.extra)
    diff_rows = report.pop("filter_diff_rows")
    acquire.write_crimes_csv(df, CRIMES_CSV)
    OUTPUT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    diff_rows.to_csv(OUTPUT_DATA_DIR / "acquire_filter_diff_rows.csv", sep=";", index=False)
    back = pd.read_csv(CRIMES_CSV, sep=";", dtype=str, keep_default_na=False, na_values=[])
    back, _ = acquire.normalise_missing(back)
    back["LATITUDE"] = pd.to_numeric(back["LATITUDE"]); back["LONGITUDE"] = pd.to_numeric(back["LONGITUDE"])
    report["inputs_sha256"] = {SSP_CSV_2022_2024.name: sha256(SSP_CSV_2022_2024),
                               SSP_XLSX_2025.name: sha256(SSP_XLSX_2025)}
    report["output"] = {"path": str(CRIMES_CSV.relative_to(CRIMES_CSV.parents[2])), "rows": int(len(df)),
                        "sha256": sha256(CRIMES_CSV)}
    report["vs_legacy"] = compare_with_legacy(back)
    (OUTPUT_DATA_DIR / "acquire_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    save_stage(STAGE, result, "Acquire: raw SSP-SP extracts to offence records (rules 1-8)")
    print(f"wrote {CRIMES_CSV} ({len(df):,} offence records, SHA-256 {report['output']['sha256'][:12]})")


if __name__ == "__main__":
    main()
