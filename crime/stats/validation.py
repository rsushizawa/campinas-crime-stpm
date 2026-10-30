"""Validation and agreement metrics.

Method
    * Targeting budgets and capture rates for ranked units (``select_budget``,
      ``evaluate_rankings``) — capture = share of future crime in the top-k
      units; PAI = capture / area-or-length share (Chainey, Tompson &
      Uhlig 2008, "The utility of hotspot mapping for predicting spatial
      patterns of crime", Security Journal 21).
    * Paired forecast differences with a circular moving-block bootstrap
      (Politis & Romano 1992; Künsch 1989 for the moving-block bootstrap).
    * Label agreement between two labelings of the same units: raw agreement,
      hot-spot / patterned Jaccard, Cohen's kappa, balanced accuracy, MCC.
Inputs → Outputs
    score / label vectors → dicts and DataFrames of metrics.
"""
import numpy as np
import pandas as pd

from crime.core.results import FAMILIES, family, jaccard


def select_budget(scores, lengths, budget, *, budget_type="segments"):
    """Select whole segments without looking at outcomes.

    Segment budgets rank expected counts. Length budgets rank expected counts
    per km, greedily adding whole segments that fit within the km cap. This is
    a distance-cap comparison, not a routing/knapsack optimum. Ties use a fixed
    seeded random priority shared by every model, never future outcomes.
    """
    scores, lengths = np.asarray(scores, float), np.asarray(lengths, float)
    if scores.shape != lengths.shape or scores.ndim != 1 or not len(scores):
        raise ValueError("scores and lengths must be nonempty aligned vectors")
    if not np.isfinite(scores).all() or not np.isfinite(lengths).all() or (lengths <= 0).any():
        raise ValueError("finite scores and positive lengths required")
    if not 0 < budget <= 1 or budget_type not in {"segments", "length"}:
        raise ValueError("invalid budget or budget_type")
    priority = np.random.default_rng(42).random(len(scores))
    rank_score = scores if budget_type == "segments" else scores / lengths
    order = np.lexsort((priority, -rank_score))
    if budget_type == "segments":
        return order[:max(1, int(budget * len(order))) ]
    remaining = budget * lengths.sum()
    selected = []
    for idx in order:
        if lengths[idx] <= remaining + 1e-12:
            selected.append(idx)
            remaining -= lengths[idx]
    return np.asarray(selected, dtype=int)


def evaluate_rankings(rankers, outcome, lengths, *, origin, budgets=(.01, .05, .1, .2)):
    outcome, lengths = np.asarray(outcome, float), np.asarray(lengths, float)
    if (outcome < 0).any() or not np.isfinite(outcome).all() or outcome.sum() <= 0:
        raise ValueError("a finite, positive-total count outcome is required")
    rows = []
    for bt in ("segments", "length"):
        for name, scores in rankers.items():
            for k in budgets:
                sel = select_budget(scores, lengths, k, budget_type=bt)
                capture = outcome[sel].sum() / outcome.sum()
                fraction = lengths[sel].sum() / lengths.sum()
                rows.append(dict(origin=origin, ranker=name, budget_type=bt, k=k,
                                 capture=capture, selected_km=float(lengths[sel].sum()),
                                 selected_segments=len(sel), length_share=fraction,
                                 pai=capture/fraction if fraction > 0 else np.nan))
    return rows


def paired_forecast_differences(results, *, reference="trailing-3mo", block_length=3,
                                resamples=2000, seed=42):
    """Circular moving-block bootstrap of paired month-level capture differences.

    Resamples consecutive origins, retaining short-range dependence. Intervals
    are exploratory with only 29 origins; they are not guarantees for future years.
    """
    rows = []
    for (bt, k), group in results.groupby(["budget_type", "k"]):
        wide = group.pivot(index="origin", columns="ranker", values="capture").sort_index()
        for name in wide.columns:
            if name == reference:
                continue
            delta = (wide[name] - wide[reference]).dropna().to_numpy()
            n = len(delta)
            rng = np.random.default_rng(seed)
            starts = rng.integers(0, n, size=(resamples, int(np.ceil(n/block_length))))
            indices = ((starts[..., None] + np.arange(block_length)) % n).reshape(resamples, -1)[:, :n]
            means = delta[indices].mean(axis=1)
            lo, hi = np.quantile(means, [.025, .975])
            rows.append(dict(budget_type=bt, k=k, ranker=name, reference=reference,
                             delta_mean=delta.mean(), ci_lo=lo, ci_hi=hi,
                             positive_month_share=float((delta > 0).mean()), n=n,
                             block_length=block_length, resamples=resamples, seed=seed))
    return pd.DataFrame(rows)


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
    cross-support weighting is appropriate when a prediction and observation
    already refer to the same sectors.  Besides agreement and Cohen's kappa,
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
