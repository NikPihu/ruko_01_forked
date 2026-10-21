"""The numbers RUKO promised (deck slide 7), computed from scores on replayed payments.

Normal payments were subsampled in the replay, so every metric uses the row weights: a kept normal
payment stands for 1/sample_rate real ones. The alert budget fixes the threshold first (at most
`per_1000` flagged legit payments in every 1,000), then everything else is read at that threshold.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score


def threshold_for_budget(score: np.ndarray, y: np.ndarray, w: np.ndarray, per_1000: float) -> float:
    """Lowest score that flags at most `per_1000` of every 1,000 legit payments (weighted)."""
    s, ww = score[~y], w[~y]
    order = np.argsort(-s)
    flagged = np.cumsum(ww[order]) / ww.sum()
    k = np.searchsorted(flagged, per_1000 / 1000, side="right")  # this many can be flagged
    if k == 0:
        return float(s[order][0]) + 1e-9
    if k >= len(s):
        return float(s.min())
    # Flag everything strictly above the (k+1)-th score, so ties never overshoot the budget.
    return float(np.nextafter(s[order][k], np.inf))


def evaluate(df: pd.DataFrame, score: np.ndarray, per_1000: float = 5.0) -> dict:
    y = df["label_is_scam"].to_numpy(bool)
    w = df["weight"].to_numpy(float)
    score = np.asarray(score, float)
    thr = threshold_for_budget(score, y, w, per_1000)
    hit = score >= thr
    legit_w = w[~y].sum()
    flagged_legit = w[~y & hit].sum()
    out = {
        "n_rows": int(len(df)), "n_scam_payments": int(y.sum()),
        "prevalence": float(w[y].sum() / w.sum()),
        "pr_auc": float(average_precision_score(y, score, sample_weight=w)),
        "threshold": thr,
        "alerts_per_1000_legit": float(1000 * flagged_legit / legit_w),
        "recall_payments": float(hit[y].mean()) if y.any() else None,
        "precision": float(w[y & hit].sum() / (w[y & hit].sum() + flagged_legit)) if hit.any() else None,
    }
    # Pre-loss catch: journeys flagged at their very first scam payment.
    first = (df["journey_pay_index"] == 0).to_numpy() & y
    out["pre_loss_catch"] = float(hit[first].mean()) if first.any() else None
    out["n_journeys_first_payment"] = int(first.sum())
    # Rupees at risk on scam payments that would have been flagged.
    amt = df["amount"].to_numpy(float)
    out["rupees_flagged_share"] = float(amt[y & hit].sum() / amt[y].sum()) if y.any() else None
    out["recall_by_playbook"] = {pb: float(hit[(df["playbook"] == pb).to_numpy() & y].mean())
                                 for pb in sorted(df.loc[y, "playbook"].dropna().unique())}
    # Fresh mules: scam payments to payees the registry did not list yet.
    fresh = y & (df["payee_registry_listed"] != True).to_numpy()  # noqa: E712 (None counts as not listed)
    out["recall_fresh_mule"] = float(hit[fresh].mean()) if fresh.any() else None
    out["n_fresh_mule_payments"] = int(fresh.sum())
    out["fairness"] = {col: _fpr_gap(df, hit, y, w, col)
                       for col in ("audit_age_band", "audit_language", "payee_merchant_kind")}
    return out


def _fpr_gap(df, hit, y, w, col) -> dict:
    """False-positive rate per group on legit payments, and the max/min ratio (target <= 1.5)."""
    rates = {}
    groups = df[col].fillna("none").to_numpy()
    for g in np.unique(groups[~y]):
        m = ~y & (groups == g)
        if w[m].sum() > 0:
            rates[str(g)] = float(w[m & hit].sum() / w[m].sum())
    positive = [r for r in rates.values() if r > 0]
    gap = (max(rates.values()) / min(positive)) if positive and min(rates.values()) > 0 else None
    return {"fpr": rates, "max_over_min": gap}


def summary_line(name: str, m: dict) -> str:
    def pct(x):
        return "  n/a" if x is None else f"{100 * x:5.1f}"
    return (f"{name:<28} PR-AUC {m['pr_auc']:.3f} | catch@1st {pct(m['pre_loss_catch'])}% | "
            f"recall {pct(m['recall_payments'])}% | fresh-mule {pct(m['recall_fresh_mule'])}% | "
            f"precision {pct(m['precision'])}% | alerts/1k {m['alerts_per_1000_legit']:.2f}")
