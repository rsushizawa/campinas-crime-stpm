"""Label agreement metrics — how stable are the per-unit labels?

Method
    Agreement between two labelings of the same units (e.g. two weights
    schemes, two trend methods, two supports overlaid onto one): raw
    agreement and hot-spot / patterned Jaccard.
Inputs → Outputs
    label vectors → dicts of metrics.
"""
import pandas as pd


def label_agreement(reference, candidate):
    """Include hotspot overlap so the no-pattern majority cannot hide instability."""
    ref, alt = pd.Series(reference), pd.Series(candidate)
    ref, alt = ref.align(alt, join="inner")
    def overlap(a, b):
        union = (a | b).sum()
        return float((a & b).sum()/union) if union else float("nan")
    return dict(label_agreement=float((ref == alt).mean()),
                hotspot_jaccard=overlap(ref.str.endswith("hotspot"), alt.str.endswith("hotspot")),
                patterned_jaccard=overlap(~ref.isin(["no pattern", "no data"]),
                                         ~alt.isin(["no pattern", "no data"])))
