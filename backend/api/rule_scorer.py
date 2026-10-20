"""Rule-based scorer with the same output shape a trained model (LightGBM + calibration) will have.

score(features) -> {p_scam, family_scores, reasons, playbook, model_version}

Each signal has a strength in [0, 1] and a reason code. Signals inside a family combine as
"noisy-or" (1 - Π(1 - s)); families combine through a logistic. Weights are hand-set and
deliberately simple -- the point is a transparent fallback, not a tuned model.
"""
from __future__ import annotations

import math

MODEL_VERSION = "rules-0.3"
# L rose from 2.0 in rules-0.3: it now carries the phone's 30-day task-scam episode, which is as
# strong as live call context. One family alone still stays far below any tier (p < 0.15).
FAMILY_WEIGHT = {"C": 3.2, "L": 3.5, "P": 3.2, "B": 2.4}
BIAS = -5.0  # two strong families (~0.9 each) land near p=0.55; one alone stays under 0.1
REASON_MIN_STRENGTH = 0.3


def _signals(f: dict) -> dict[str, list[tuple[float, str]]]:
    s: dict[str, list[tuple[float, str]]] = {"C": [], "L": [], "P": [], "B": []}
    add = lambda fam, strength, code: s[fam].append((strength, code))  # noqa: E731

    # Context: who is on the line, and who can see the screen.
    if f["on_call"] and f["caller_unknown"]:
        add("C", 0.9 if f["foreign_caller"] else 0.8 if f["voip_call"] else 0.7, "R1_live_unknown_call")
    elif f["on_call"] and f["outgoing_to_unknown"]:
        add("C", 0.5, "R1_live_unknown_call")
    if f["remote_control"]:
        add("C", 0.85, "R2_remote_control")
    if f["untrusted_accessibility"]:
        add("C", 0.7, "R2_remote_control")
    if f["sideloaded_last_24h"]:
        add("C", 0.5, "R2_remote_control")

    # Lure: a scam-script message recently, or small "reward" credits from strangers.
    if (f["lure_max_conf_72h"] or 0) >= 0.6:
        add("L", f["lure_max_conf_72h"], "R5_lure_message")
    # The phone's task-scam episode is ONE lure signal: rewards in, then paying more and more.
    ep = f["episode_state"]
    if ep == 2:  # active
        add("L", 0.85, "R10_bait_then_pay")
    elif ep == 1 and f["first_time_payee"]:  # watching
        add("L", 0.5, "R10_bait_then_pay")
    elif ep == 3 and (f["payee_registry_listed"] or (f["payee_fri_level"] or 0) >= 2):
        add("L", 0.6, "R10_bait_then_pay")  # "I know them" is overridden by an intel hit

    # Payee: mule-like behaviour seen by the payee's bank, and what the lists say.
    u6, u7, rep = f["payee_uniq_payers_6h"], f["payee_uniq_payers_7d"], f["payee_repeat_ratio"]
    pt, age, hold = f["payee_pass_through_24h"], f["payee_account_age_days"], f["payee_median_hold_min"]
    if u6 is not None and rep is not None and u6 >= 10 and rep < 0.3:
        add("P", 0.8, "R3_mule_like_payee")
    if u7 is not None and rep is not None and u7 >= 20 and rep < 0.2:
        add("P", 0.6, "R3_mule_like_payee")
    if pt is not None and age is not None and pt >= 0.8 and age < 30:
        add("P", 0.75, "R3_mule_like_payee")
    if hold is not None and pt is not None and hold <= 30 and pt >= 0.6:
        add("P", 0.5, "R3_mule_like_payee")
    if age is not None and age < 14 and f["payee_holder_type"] == "person":
        add("P", 0.3, "R3_mule_like_payee")
    if (f["payee_mulehunter"] or 0) >= 0.5:
        add("P", f["payee_mulehunter"], "R3_mule_like_payee")
    if f["payee_registry_listed"]:
        add("P", 0.8, "R8_intel_hit")
    if f["caller_registry_listed"]:
        add("P", 0.7, "R8_intel_hit")
    for lvl in (f["payee_fri_level"], f["caller_fri_level"]):
        if lvl:
            add("P", {1: 0.4, 2: 0.7, 3: 0.9}[lvl], "R8_intel_hit")
    if f["story_mismatch"]:
        add("P", 0.8, "R9_story_mismatch")

    # Behaviour: is this payment unlike the payer's usual ones?
    ratio = f["amount_to_max_90d"]
    if ratio is not None and ratio >= 3:
        add("B", 0.8, "R4_unusual_amount")
    elif ratio is not None and ratio >= 1.5:
        add("B", 0.5, "R4_unusual_amount")
    elif ratio is None and f["amount_inr"] >= 50_000:
        add("B", 0.4, "R4_unusual_amount")
    if f["first_time_payee"]:
        add("B", 0.35 if f["entry_typed"] else 0.15, "R6_new_payee_typed")
    if f["attempts_72h"] >= 2:
        add("B", 0.7, "R7_tranche_pattern")
    elif f["attempts_72h"] >= 1:
        add("B", 0.4, "R7_tranche_pattern")
    if (f["new_payee_sum_to_max_90d"] or 0) >= 3 and f["attempts_72h"] >= 1:
        add("B", 0.6, "R7_tranche_pattern")
    return s


def _noisy_or(xs: list[float]) -> float:
    return 1 - math.prod(1 - x for x in xs)


def _playbook(f: dict) -> str | None:
    tag = f["lure_tag"]
    # An active task-scam episode beats any older message on the phone.
    if f["episode_state"] == 2:
        return "task_job"
    if f["sideloaded_last_24h"] and tag == "kyc":
        return "fake_kyc_apk"
    if f["outgoing_to_unknown"] and f["remote_control"]:
        return "fake_customer_care"
    if tag == "arrest_threat" or (f["on_call"] and f["caller_unknown"]
                                  and (f["remote_control"] or f["story_mismatch"])):
        return "digital_arrest"
    if tag == "trading_tip":
        return "trading_group"
    if tag == "task_job":
        return "task_job"
    if f["on_call"] and f["caller_unknown"] and not f["entry_typed"]:
        return "refund_qr"
    return None


def score(f: dict) -> dict:
    sig = _signals(f)
    fam = {k: round(_noisy_or([x for x, _ in v]), 3) for k, v in sig.items()}
    # A verified, long-standing merchant with no list hits is very unlikely to be a mule.
    if f["payee_verified_merchant"] and not any(c == "R8_intel_hit" for _, c in sig["P"]):
        fam["P"] = round(fam["P"] * 0.3, 3)
    z = BIAS + sum(FAMILY_WEIGHT[k] * v for k, v in fam.items())
    best: dict[str, float] = {}
    for k, v in sig.items():
        for strength, code in v:
            if strength >= REASON_MIN_STRENGTH:
                best[code] = max(best.get(code, 0), strength * FAMILY_WEIGHT[k])
    reasons = [c for c, _ in sorted(best.items(), key=lambda kv: -kv[1])][:4]
    return {"p_scam": round(1 / (1 + math.exp(-z)), 4), "family_scores": fam,
            "reasons": reasons, "playbook": _playbook(f), "model_version": MODEL_VERSION}
