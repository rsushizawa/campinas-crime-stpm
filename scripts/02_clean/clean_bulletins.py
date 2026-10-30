"""Stage 02 — Clean: offence records -> one row per bulletin + the N funnel.

    python scripts/02_clean/clean_bulletins.py

Reads ``outputs/data/crimes_campinas.csv`` (stage 01), collapses it to one row
per bulletin (``etl/clean.py``: kept offence = highest maximum penalty), assigns
each geocoded bulletin to its 2022 tract (point-in-polygon, first match) and
writes:

* ``outputs/data/bulletins_clean.parquet`` — the cleaned bulletin table
* ``outputs/data/funnel.json`` — rows at every stage (all offences + property)
* ``outputs/data/dedup_report.json`` / ``dedup_group_transitions.csv``

The database is then loaded from the parquet (``load_database.py``).
"""
import json

import geopandas as gpd
import pandas as pd

from crime.core.config import BULLETINS_PARQUET, CRIMES_CSV, CRS_WGS84, FUNNEL_JSON, OUTPUT_DATA_DIR
from crime.data.cleaning import DATE_END, DATE_START
from etl import sources
from etl.clean import BULLETIN_KEY, collapse_bulletins, group_transitions
from etl.postgis import assign_unit


def funnel(records: pd.DataFrame, bulletins: pd.DataFrame) -> list[dict]:
    """N at every stage, for all offences and for the property group."""
    prop = bulletins["crime_group"].eq("property")
    occ = bulletins["DATA_OCORRENCIA_BO"]
    in_window = occ.ge(pd.Timestamp(DATE_START)) & occ.lt(pd.Timestamp(DATE_END) + pd.Timedelta(days=1))
    has_xy = bulletins["LATITUDE"].notna() & bulletins["LONGITUDE"].notna()
    in_tract = bulletins["cd_setor"].notna()
    rec_prop = records["NATUREZA_APURADA"].map(sources_group).eq("property")

    def row(stage, m, definition):
        return {"stage": stage, "all": int(m.sum()), "property": int((m & prop).sum()), "definition": definition}

    return [
        {"stage": "offence records (acquired CSV)", "all": int(len(records)), "property": int(rec_prop.sum()),
         "definition": "outputs/data/crimes_campinas.csv; property = record's own offence is property"},
        row("bulletins (one row per NUM_BO+ANO_BO+NOME_DELEGACIA)", pd.Series(True, index=bulletins.index),
            "kept offence = highest maximum penalty (etl/clean.py)"),
        row("occurrence date in window", in_window, f"DATA_OCORRENCIA_BO in [{DATE_START}, {DATE_END}]"),
        row("... with a usable coordinate", in_window & has_xy, "COORD_STATUS in {ok, fixed_decimal}"),
        row("... inside a 2022 Campinas tract (cube input)", in_window & has_xy & in_tract,
            "point within a tract polygon"),
    ]


def sources_group(natureza):
    from etl import taxonomy
    return taxonomy.to_group(natureza)


def main() -> None:
    records = sources.extract_crimes(CRIMES_CSV)
    bulletins, report = collapse_bulletins(records)
    occ = pd.to_datetime(bulletins["DATA_OCORRENCIA_BO"], errors="coerce", format="%Y-%m-%d")
    report["unparseable_occurrence_dates"] = (
        bulletins.loc[occ.isna() & bulletins["DATA_OCORRENCIA_BO"].notna(), "DATA_OCORRENCIA_BO"]
        .astype(str).value_counts().to_dict())
    bulletins["DATA_OCORRENCIA_BO"] = occ
    bulletins["DATA_REGISTRO"] = pd.to_datetime(bulletins["DATA_REGISTRO"], errors="coerce")

    # tract assignment (same rule as load_database.py)
    tracts = sources.extract_census_tracts()
    ok = bulletins["LATITUDE"].notna() & bulletins["LONGITUDE"].notna()
    pts = gpd.GeoDataFrame(bulletins.loc[ok, BULLETIN_KEY],
                           geometry=gpd.points_from_xy(bulletins.loc[ok, "LONGITUDE"],
                                                       bulletins.loc[ok, "LATITUDE"]), crs=CRS_WGS84)
    joined = assign_unit(pts, tracts[["cd_setor", "geometry"]])
    bulletins["cd_setor"] = joined["cd_setor"].reindex(bulletins.index)

    trans = group_transitions(records, bulletins)
    moved = trans[trans["groups_present"] != trans["kept_group"]]
    report["multi_group_bulletins"] = int(moved["bulletins"].sum())
    prop_had = trans[trans["groups_present"].str.contains("property")]
    report["bulletins_with_property_record_kept_as_other_group"] = {
        f"{r.groups_present} -> {r.kept_group}": int(r.bulletins)
        for r in prop_had[prop_had["kept_group"] != "property"].itertuples()}

    OUTPUT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for c in bulletins.select_dtypes("object").columns:
        bulletins[c] = bulletins[c].astype("string")
    bulletins.to_parquet(BULLETINS_PARQUET, index=False)
    trans.to_csv(OUTPUT_DATA_DIR / "dedup_group_transitions.csv", index=False)
    f = funnel(records, bulletins)
    FUNNEL_JSON.write_text(json.dumps(f, indent=2))
    (OUTPUT_DATA_DIR / "dedup_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(f, indent=2))
    print(trans.to_string())


if __name__ == "__main__":
    main()
