"""Label agreement metrics — how stable are the per-unit labels?

Method
    Agreement between two labelings of the same units (e.g. two weights
    schemes, two trend methods, an observed vs a re-run result): raw
    agreement, hot-spot / patterned Jaccard, Cohen's kappa (Cohen 1960),
    balanced accuracy and Matthews correlation (MCC).
Inputs → Outputs
    label vectors → dicts of metrics.
"""
import pandas as pd

from crime.core.results import FAMILIES, family, jaccard


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


def prediction_agreement(observed_labels, predicted_labels):
    """Compare two label series on the same support, aligned by ``unit_id``.

    This is deliberately not :func:`crime.esri.maup.support_sensitivity`: no overlay or
    cross-support weighting is appropriate when both labelings already refer
    to the same units.  Besides agreement and Cohen's kappa,
    return class prevalence, balanced accuracy, MCC, and separate hot/cold
    Jaccards so a dominant ``no pattern`` class cannot hide disagreement.
    """
    from sklearn.metrics import (
        balanced_accuracy_score,
        cohen_kappa_score,
        confusion_matrix,
        matthews_corrcoef,
    )

    def _series(x):
        if isinstance(x, pd.DataFrame):
            if "unit_id" not in x or "label" not in x:
                raise ValueError("data frames need unit_id and label columns")
            return x.set_index("unit_id")["label"]
        return pd.Series(x)

    obs, pred = _series(observed_labels), _series(predicted_labels)
    obs, pred = obs.align(pred, join="inner")
    if not len(obs):
        raise ValueError("no aligned labels")
    classes = list(FAMILIES)
    o, p = family(obs), family(pred)
    cm = confusion_matrix(o, p, labels=classes)
    def jac(cls):
        return jaccard(o, p, cls)
    return {
        "n": int(len(o)), "raw_agreement": float((o == p).mean()),
        "cohen_kappa": float(cohen_kappa_score(o, p, labels=classes)),
        "balanced_accuracy": float(balanced_accuracy_score(o, p)),
        "mcc": float(matthews_corrcoef(o, p)),
        "hotspot_jaccard": jac("hotspot"), "coldspot_jaccard": jac("coldspot"),
        "observed_prevalence": {c: float((o == c).mean()) for c in classes},
        "predicted_prevalence": {c: float((p == c).mean()) for c in classes},
        "confusion_matrix": cm.tolist(), "confusion_labels": classes,
    }
