"""Support sensitivity (MAUP) — do the hot spots survive a change of support?

Method
    Collapse each finer-support EHSA result (e.g. the statistical grid) onto a
    reference support (census tracts) by area / length-weighted overlay, then
    measure agreement of the hot / cold / no-pattern *families*.
Reference
    The modifiable areal unit problem: Openshaw, S. (1984). The Modifiable
    Areal Unit Problem. CATMOG 38. Cohen's kappa (Cohen 1960) and the Jaccard
    index for agreement. The overlay-majority aggregation rule is a
    project-specific choice.
Steps
    1. family of every unit (:func:`crime.core.results.family`);
    2. for each reference unit, sum the intersection area (polygons) or length
       (lines) of each family among overlapping finer units; take the argmax;
    3. agreement metrics per finer support.
Inputs → Outputs
    reference ``EhsaResult`` + ``{name: EhsaResult}`` → ``(labels, agreement)``.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from crime.core.config import CRS_METRIC
from crime.core.results import family, jaccard


def support_sensitivity(ref, others: dict):
    """Aggregate one or more finer-support EHSA results onto ``ref``'s units by
    area/length-weighted overlay, and report family agreement against ``ref``
    — turns a MAUP support comparison (e.g. sector vs grid) into
    a number instead of three maps side by side. Complements
    :func:`crime.stats.validation.label_agreement`, which compares two label
    series on the *same* support (e.g. weights or trend-method sensitivity);
    this one first collapses each finer support onto ``ref``'s geometry so
    supports of different shape and count become comparable at all.

    Each finer unit's family (``"hotspot"``/``"coldspot"``/``"no pattern"``)
    is assigned to whichever ``ref`` unit it overlaps most (by intersection
    area for polygons, length for lines). Run ``ref``/``others`` under
    matched inference (same ``fdr``, ``alpha``, ``freq``) first, or
    the comparison mixes support choice with inference choice.

    Returns ``(labels, agreement)``: ``labels`` — ref unit x {"ref", *others}
    family DataFrame; ``agreement`` — per other, the same
    ``label_agreement``/``hotspot_jaccard``/``patterned_jaccard`` metrics used
    elsewhere for specification sensitivity, plus Cohen's kappa and a
    cold-spot Jaccard (MAUP-specific — a coarser support's cold spots are
    the ones most likely to average away entirely).
    """
    from sklearn.metrics import cohen_kappa_score

    from crime.stats.validation import label_agreement

    ref_gdf = gpd.GeoDataFrame({"_ref_id": np.arange(len(ref.gdf))}, geometry=ref.gdf.geometry.values,
                              crs=ref.gdf.crs).to_crs(CRS_METRIC)
    labels = pd.DataFrame({"ref": family(ref.gdf["category"])})
    rows = {}
    for name, other in others.items():
        fine = gpd.GeoDataFrame({"_family": family(other.gdf["category"])},
                                geometry=other.gdf.geometry.values, crs=other.gdf.crs).to_crs(ref_gdf.crs)
        is_line = fine.geom_type.isin(["LineString", "MultiLineString"]).any()
        sidx = fine.sindex
        weight = np.zeros((len(ref_gdf), 3))   # columns: hotspot, coldspot, no pattern
        fam_col = {"hotspot": 0, "coldspot": 1, "no pattern": 2}
        for ref_id, ref_geom in zip(ref_gdf["_ref_id"], ref_gdf.geometry):
            cand = list(sidx.query(ref_geom, predicate="intersects"))
            if not cand:
                continue
            sub = fine.iloc[cand]
            inter = sub.geometry.intersection(ref_geom)
            w = inter.length.to_numpy() if is_line else inter.area.to_numpy()
            for fam, wv in zip(sub["_family"], w):
                if wv > 0:
                    weight[ref_id, fam_col[fam]] += wv
        covered = weight.sum(axis=1) > 0
        agg = pd.Series("no pattern", index=ref_gdf["_ref_id"])
        agg[covered] = np.array(["hotspot", "coldspot", "no pattern"])[weight[covered].argmax(axis=1)]
        labels[name] = agg.to_numpy()

        rows[name] = {
            **label_agreement(labels["ref"], labels[name]),
            "coldspot_jaccard": jaccard(labels["ref"], labels[name], "coldspot"),
            "kappa": float(cohen_kappa_score(labels["ref"], labels[name])),
            "uncovered_ref_units": int((~covered).sum()),
        }
    agreement = pd.DataFrame(rows).T
    print("support sensitivity (MAUP, vs ref support): " +
         "; ".join(f"{n}: label_agreement={r['label_agreement']:.1%}, "
                   f"hotspot_jaccard={r['hotspot_jaccard']:.2f}, kappa={r['kappa']:.2f}"
                   for n, r in agreement.iterrows()))
    return labels, agreement
