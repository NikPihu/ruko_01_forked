"""The explainable layer: why one payment got its tier, at two levels.

- The USER sees only the top reasons (at most 3) and the scam type, in words (rule 4: never a score).
  That is the /v1/decide response itself; `user_view` below repeats it so the analyst sees exactly
  what the user saw.
- The ANALYST sees everything: the overall and family scores, every signal with its strength, the
  inputs behind each reason, every playbook rule checked and which matched, the policy steps that
  set the final tier, and which outside sources answered.

Built on read from what the transaction database stored for the payment, so it costs the payment
path nothing. Works for any scorer: the rules report each signal's strength; a model that reports
none still gets families, scores, inputs, playbooks and policy steps.
"""
from __future__ import annotations

from typing import Optional

from api.rule_scorer import PLAYBOOK_RULES

FAMILY_NAME = {"C": "Context (calls, screen control)", "L": "Lure (scam messages, task-scam episode)",
               "P": "Payee (bank, lists, payment graph)", "B": "Behaviour (this payment vs the user's habits)"}

# Which inputs speak for each reason, so a reason can be traced to the values that caused it.
REASON_INPUTS = {
    "R1_live_unknown_call": ["on_call", "caller_unknown", "voip_call", "foreign_caller", "outgoing_to_unknown",
                             "call_on_speaker", "video_call"],
    "R2_remote_control": ["remote_control", "untrusted_accessibility", "sideloaded_last_24h"],
    "R3_mule_like_payee": ["payee_account_age_days", "payee_uniq_payers_6h", "payee_uniq_payers_7d",
                           "payee_repeat_ratio", "payee_pass_through_24h", "payee_median_hold_min",
                           "payee_mulehunter", "payee_holder_type", "payee_verified_merchant"],
    "R4_unusual_amount": ["amount_inr", "amount_to_max_90d", "amount_to_median_90d"],
    "R5_lure_message": ["lure_max_conf_72h", "lure_tag"],
    "R6_new_payee_typed": ["first_time_payee", "entry_typed", "payee_in_contacts"],
    "R7_tranche_pattern": ["attempts_72h", "new_payee_sum_to_max_90d", "payee_in_run"],
    "R8_intel_hit": ["payee_registry_listed", "caller_registry_listed", "payee_fri_level", "caller_fri_level"],
    "R9_story_mismatch": ["story_mismatch", "payee_holder_type"],
    "R10_bait_then_pay": ["episode_state", "episode_age_days", "episode_bait_credits", "episode_new_payees",
                          "episode_out_to_in", "episode_escalation_steps"],
    "R11_ring_link": ["payee_money_loop", "payee_crowd", "payee_forwards_to_cashout", "payee_approved_suspect",
                      "payee_automated"],
    "R12_coached_session": ["session_dictated", "session_pasted_after_switch", "session_app_switches",
                            "session_abandoned_30m", "session_hesitation"],
}
REASON_TEXT = {
    "R1_live_unknown_call": "on a call with someone not in contacts",
    "R2_remote_control": "an app can see or control the screen",
    "R3_mule_like_payee": "the payee account behaves like a mule",
    "R4_unusual_amount": "much larger than the user's usual payments",
    "R5_lure_message": "a recent message matches a scam script",
    "R6_new_payee_typed": "a new payee, typed by hand",
    "R7_tranche_pattern": "several payments to new payees in a short time",
    "R8_intel_hit": "the account or caller is on a fraud list",
    "R9_story_mismatch": "the payee is not who the user said they are paying",
    "R10_bait_then_pay": "small 'rewards' in, then bigger payments out (task scam)",
    "R11_ring_link": "the payee is linked to a scam ring in the payment graph",
    "R12_coached_session": "the Pay screen was used as if someone was guiding the user",
}
USER_MAX_REASONS = 3
SOURCES = ("npci", "bank", "payee_registry", "caller_registry", "payee_fri", "caller_fri")


def band(strength: float) -> str:
    return "large" if strength >= 0.7 else "medium" if strength >= 0.45 else "small"


def _shown(v) -> bool:
    """An input worth showing: it was measured and points somewhere (not null, not False/0)."""
    return v is not None and v is not False and v != 0


def explain(payment: dict, details: Optional[dict]) -> dict:
    d = details or {}
    f = d.get("features") or {}
    signals = d.get("signals") or []
    fams = d.get("family_scores") or {}
    lit = d.get("lit_families") or []

    by_reason: dict[str, list[dict]] = {}
    for s in signals:
        by_reason.setdefault(s["reason"], []).append(s)
    reasons_all = sorted(set(by_reason) | set(payment.get("reasons") or []),
                         key=lambda r: -max((s["strength"] for s in by_reason.get(r, [])), default=0))
    reasons = []
    for code in reasons_all:
        sigs = by_reason.get(code, [])
        strength = max((s["strength"] for s in sigs), default=None)
        reasons.append({
            "code": code, "text": REASON_TEXT.get(code, code),
            "family": sigs[0]["family"] if sigs else None,
            "strength": strength, "band": band(strength) if strength is not None else None,
            "signals": len(sigs), "shown_to_user": code in (payment.get("reasons") or [])[:USER_MAX_REASONS],
            "inputs": {k: f[k] for k in REASON_INPUTS.get(code, []) if k in f and _shown(f[k])},
        })

    chosen = payment.get("playbook")
    playbooks, picked = [], False
    for name, why, rule in PLAYBOOK_RULES:
        try:
            met = bool(rule(f)) if f else False
        except (KeyError, TypeError):  # a model's features may not carry every rule input
            met = False
        is_choice = met and not picked and name == chosen   # the first matching rule names the playbook
        picked = picked or met
        playbooks.append({"playbook": name, "rule": why, "matched": met, "chosen": is_choice})

    intel = d.get("intel_status") or {}
    return {
        "payment_id": payment["payment_id"],
        "user_view": {"tier": payment["tier"], "reasons": (payment.get("reasons") or [])[:USER_MAX_REASONS],
                      "message_key": payment.get("message_key"), "playbook": chosen,
                      "pause_minutes": payment.get("pause_minutes")},
        "scores": {"p_scam": d.get("p_scam"), "families": fams, "lit_families": lit,
                   "family_names": {k: FAMILY_NAME[k] for k in fams if k in FAMILY_NAME}},
        "reasons": reasons,
        "playbooks": playbooks,
        "policy_steps": d.get("policy_steps") or [],
        "sources": {k: intel.get(k) for k in SOURCES if k in intel},
        "stage_path": d.get("stage_path") or [],
        "scorer_version": payment.get("scorer_version"),
        "policy_version": payment.get("policy_version"),
        "evidence_id": payment.get("evidence_id"),
        "fail_open": payment.get("fail_open"),
    }
