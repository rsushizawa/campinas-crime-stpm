"""Clean stage: one row per bulletin (IC-Crime#13).

    from crime.importer.treatments import collapse_bulletins
    bulletins, report = collapse_bulletins(records)

The acquired SSP-SP table has one row per *offence record*: a bulletin
(``NUM_BO + ANO_BO + NOME_DELEGACIA``) carrying two offences appears twice.
:func:`collapse_bulletins` keeps exactly one record per bulletin: the one
whose offence has the highest maximum penalty (:data:`crime.taxonomy.MAX_PENALTY`),
a specific slug beating a ``*_outros`` slug on a tie. If two records are still
tied (same penalty, both specific or both generic) the first in source order
is kept (owner-confirmed rule, also for cross-group ties such as
estupro + roubo_veiculo); the count of such groups is reported, never hidden.
"""
from __future__ import annotations

import pandas as pd

from crime import taxonomy

BULLETIN_KEY = ["NUM_BO", "ANO_BO", "NOME_DELEGACIA"]


def collapse_bulletins(df: pd.DataFrame, *, key=BULLETIN_KEY, natureza: str = "NATUREZA_APURADA"
                       ) -> tuple[pd.DataFrame, dict]:
    """Keep one row per ``key``; returns (kept rows in source order, report).

    Adds ``crime_slug``, ``crime_group``, ``n_records`` (offence records on the
    bulletin) and ``slugs_on_bulletin`` (sorted, ``|``-joined) to the result.
    """
    d = df.copy()
    d["_order"] = range(len(d))
    d["crime_slug"] = d[natureza].map(taxonomy.to_slug)
    unmapped = d.loc[d["crime_slug"].isna(), natureza].value_counts().to_dict()
    keys = d["crime_slug"].map(taxonomy.severity_key)          # raises on a slug without a penalty
    d["_pen"] = [k[0] for k in keys]
    d["_spec"] = [k[1] for k in keys]

    grp = d.groupby(key, sort=False, dropna=False)
    d["n_records"] = grp["_order"].transform("size")
    d["slugs_on_bulletin"] = grp["crime_slug"].transform(
        lambda s: "|".join(sorted({x for x in s if isinstance(x, str)})))

    ranked = d.sort_values(["_pen", "_spec", "_order"], ascending=[False, False, True], kind="mergesort")
    kept = ranked.drop_duplicates(subset=key, keep="first").sort_values("_order")

    # residual ties: >1 record sharing the top (penalty, specificity) with a different slug
    top = ranked.groupby(key, sort=False, dropna=False).head(2)
    multi = top[top.duplicated(subset=key, keep=False)]
    tie_groups = 0
    if len(multi):
        g = multi.groupby(key, sort=False, dropna=False)
        same_rank = g["_pen"].transform("nunique").eq(1) & g["_spec"].transform("nunique").eq(1)
        diff_slug = g["crime_slug"].transform("nunique").gt(1)
        tie_groups = int(multi[same_rank & diff_slug].drop_duplicates(subset=key).shape[0])

    kept = kept.assign(crime_group=kept["crime_slug"].map(taxonomy.SLUG_TO_GROUP))

    # group membership before (any record in group G) vs after (kept record in G)
    before_any = d.assign(g=d["crime_slug"].map(taxonomy.SLUG_TO_GROUP)).dropna(subset=["g"])
    any_group = before_any.drop_duplicates(subset=key + ["g"])["g"].value_counts()
    multi_keys = d[d["n_records"] > 1]
    report = {
        "rows_in": int(len(d)),
        "bulletins_out": int(len(kept)),
        "rows_removed": int(len(d) - len(kept)),
        "multi_record_bulletins": int(multi_keys.drop_duplicates(subset=key).shape[0]),
        "extra_rows": int(len(multi_keys) - multi_keys.drop_duplicates(subset=key).shape[0]),
        "multi_record_bulletins_differing_natureza": int(
            (multi_keys.groupby(key, sort=False)[natureza].nunique() > 1).sum()),
        "exact_duplicate_rows": int(df.duplicated().sum()),
        "residual_tie_groups_first_kept": tie_groups,
        "unmapped_natureza": {str(k): int(v) for k, v in unmapped.items()},
        "records_per_group_before": {g: int(n) for g, n in
                                     before_any["g"].value_counts().sort_index().items()},
        "bulletins_with_any_record_in_group": {g: int(n) for g, n in any_group.sort_index().items()},
        "bulletins_per_group_after": {g: int(n) for g, n in
                                      kept["crime_group"].value_counts().sort_index().items()},
    }
    out = kept.drop(columns=["_order", "_pen", "_spec"]).reset_index(drop=True)
    return out, report


def group_transitions(df: pd.DataFrame, kept: pd.DataFrame, *, key=BULLETIN_KEY,
                      natureza: str = "NATUREZA_APURADA") -> pd.DataFrame:
    """For multi-record bulletins: which groups appeared on the bulletin vs the
    group of the kept record. One row per (groups present, kept group) with a count."""
    d = df[key + [natureza]].copy()
    d["g"] = d[natureza].map(taxonomy.to_group).fillna("unmapped")
    present = d.groupby(key, sort=False)["g"].agg(lambda s: "|".join(sorted(set(s))))
    n = d.groupby(key, sort=False).size()
    k = kept.set_index(key)["crime_group"].fillna("unmapped")
    t = pd.DataFrame({"groups_present": present, "kept_group": k.reindex(present.index), "n": n})
    t = t[t["n"] > 1]
    return (t.groupby(["groups_present", "kept_group"]).size().rename("bulletins")
            .reset_index().sort_values("bulletins", ascending=False, ignore_index=True))
