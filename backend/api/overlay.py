"""Evidence overlay: RUKO's own cross-user evidence counts with any scorer.

The trained model (`lgbm-*`) only knows the features it was trained on. Evidence RUKO computes itself
across users (policy.yaml `evidence_overlay.features`, e.g. `payee_new_and_spreading`) is applied after
scoring: each feature that fired lifts its family to `family_floor` and puts its reason first. The
policy then raises the tier to `min_tier` only when enough families are lit, so this evidence alone
never interrupts (rule 5). Fixed rules, no LLM (rule 13).
"""
from __future__ import annotations

MAX_REASONS = 4


def apply(s: dict, f: dict, cfg: dict) -> dict:
    """The scorer's output with the overlay applied; unchanged when no overlay feature fired.
    Only a feature that is exactly True fires: unknown (None) is never evidence either way."""
    ov = cfg.get("evidence_overlay") or {}
    specs = ov.get("features") or {}
    fired = [name for name in specs if f.get(name) is True]
    if not fired:
        return s
    floor = ov.get("family_floor", 0.6)
    fams = dict(s.get("family_scores") or {})
    reasons = list(s.get("reasons") or [])
    groups: set[str] = set()
    for name in fired:
        fam, code, group = specs[name]["family"], specs[name]["reason"], specs[name].get("group")
        # Features from one source (a group, e.g. one scam campaign) light at most one family (rule 5).
        if group is None or group not in groups:
            fams[fam] = max(fams.get(fam) or 0.0, floor)
            if group is not None:
                groups.add(group)
        if code in reasons:
            reasons.remove(code)
        reasons.insert(0, code)
    return {**s, "family_scores": fams, "reasons": reasons[:MAX_REASONS], "overlay": fired}
