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

from typing import Any, Callable, Optional

from api.rule_scorer import PLAYBOOK_RULES
from api.rule_scorer import signals as rule_signals
from features.build import FAMILY

FAMILY_NAME = {"C": "Context (calls, screen control)", "L": "Lure (scam messages, task-scam episode)",
               "P": "Payee (bank, lists, payment graph)", "B": "Behaviour (this payment vs the user's habits)"}

# Which inputs speak for each reason, so a reason can be traced to the values that caused it.
REASON_INPUTS = {
    "R1_live_unknown_call": ["on_call", "caller_unknown", "voip_call", "foreign_caller", "outgoing_to_unknown",
                             "call_on_speaker", "video_call"],
    "R2_remote_control": ["remote_control", "untrusted_accessibility", "sideloaded_last_24h"],
    "R3_mule_like_payee": ["payee_account_age_days", "payee_uniq_payers_6h", "payee_uniq_payers_7d",
                           "payee_repeat_ratio", "payee_pass_through_24h", "payee_median_hold_min",
                           "payee_mulehunter", "payee_holder_type", "payee_verified_merchant",
                           "payee_new_and_spreading"],
    "R4_unusual_amount": ["amount_inr", "amount_to_max_90d", "amount_to_median_90d"],
    "R5_lure_message": ["lure_max_conf_72h", "lure_tag"],
    "R6_new_payee_typed": ["first_time_payee", "entry_typed", "payee_in_contacts"],
    "R7_tranche_pattern": ["attempts_72h", "new_payee_sum_to_max_90d", "payee_in_run", "payee_micro_anchor",
                           "outflow_24h_to_max_90d"],
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


def explain(payment: dict, details: Optional[dict], policy_cfg: Optional[dict] = None) -> dict:
    d = details or {}
    f = d.get("features") or {}
    # A scorer may report its own signals; otherwise the rules' view of the same inputs is shown.
    signals = d.get("signals") or []
    signal_source = "scorer" if signals else "rules"
    if not signals and f:
        try:
            signals = rule_signals(f)
        except (KeyError, TypeError):
            signals = []
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
        "summary": summary(payment["tier"], f, fams, lit, d.get("policy_steps") or [], chosen,
                           d.get("p_scam"), policy_cfg),
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
        "signal_source": signal_source,
        "scorer_version": payment.get("scorer_version"),
        "policy_version": payment.get("policy_version"),
        "evidence_id": payment.get("evidence_id"),
        "fail_open": payment.get("fail_open"),
    }


# ---------- "Why this decision" in words, for the analyst (console summary) ----------

def _inr(x: float) -> str:
    return f"₹{x:,.0f}"


def _times(x: float) -> str:
    return f"{x:.1f}×" if x < 10 else f"{x:.0f}×"


FRI_WORDS = ["none", "medium", "high", "very high"]

# Each input in words with its value. None = not worth a line. Unknown inputs fall back to "name = value".
INPUT_WORDS: dict[str, Callable[[Any], Optional[str]]] = {
    "on_call": lambda v: "on a call while paying",
    "caller_unknown": lambda v: "the caller is not in contacts",
    "voip_call": lambda v: "the call is an internet (VoIP) call",
    "video_call": lambda v: "it is a video call (camera in use by another app)",
    "foreign_caller": lambda v: "the caller's number is from outside India",
    "outgoing_to_unknown": lambda v: "the user had called an unknown number",
    "call_on_speaker": lambda v: "the call is on speaker",
    "remote_control": lambda v: "a screen-sharing or remote-control app is active",
    "untrusted_accessibility": lambda v: "an untrusted app has accessibility access (can read the screen)",
    "sideloaded_last_24h": lambda v: "an app from outside the Play Store was installed in the last 24 h",
    "lure_max_conf_72h": lambda v: f"a scam-script message in the last 72 h (confidence {v:.2f})",
    "lure_tag": lambda v: None if v == "normal" else f"message type: {str(v).replace('_', ' ')}",
    "episode_state": lambda v: {1: "task-scam watcher: WATCHING (a small credit from a stranger)",
                                2: "task-scam watcher: ACTIVE (rewards in, bigger payments out)"}.get(v),
    "episode_bait_credits": lambda v: f"{v} small 'reward' credits from strangers",
    "episode_new_payees": lambda v: f"{v} new payees during the episode",
    "episode_out_to_in": lambda v: f"paid out {_times(v)} what came in",
    "episode_escalation_steps": lambda v: f"{v} payments, each bigger than the last",
    "episode_age_days": lambda v: f"episode started {v:.0f} days ago",
    "payee_registry_listed": lambda v: "the payee is on the I4C fraud registry",
    "caller_registry_listed": lambda v: "the caller is on the I4C fraud registry",
    "payee_fri_level": lambda v: f"DoT fraud risk of the payee's number: {FRI_WORDS[int(v)]}",
    "caller_fri_level": lambda v: f"DoT fraud risk of the caller: {FRI_WORDS[int(v)]}",
    "payee_mulehunter": lambda v: f"bank's MuleHunter score {v:.2f}",
    "payee_account_age_days": lambda v: f"payee account is {v:.0f} days old",
    "payee_uniq_payers_6h": lambda v: f"{v:.0f} different people paid it in the last 6 h",
    "payee_uniq_payers_7d": lambda v: f"{v:.0f} different people paid it in 7 days",
    "payee_repeat_ratio": lambda v: f"{v:.0%} of its payers come back (low means one-off victims)",
    "payee_pass_through_24h": lambda v: f"{v:.0%} of money in is sent on within 24 h",
    "payee_median_hold_min": lambda v: f"money stays a median of {v:.0f} min before it moves on",
    "payee_holder_type": lambda v: ("the UPI ID belongs to a personal account (not a business)" if v == "person"
                                    else f"the UPI ID belongs to a {v} account"),
    "payee_verified_merchant": lambda v: "the payee is a verified merchant",
    "story_mismatch": lambda v: "the user said 'government / company', but the payee is a person",
    "vpa_invalid": lambda v: "the UPI ID does not resolve",
    "payee_crowd": lambda v: "many RUKO users were paid by or paid this account",
    "payee_money_loop": lambda v: "money loops back to accounts that paid 'rewards'",
    "payee_forwards_to_cashout": lambda v: "it forwards money to a known cash-out account",
    "payee_approved_suspect": lambda v: "two analysts approved it as a mule",
    "payee_automated": lambda v: "bot-scale: the same amount to or from many people at a steady rhythm",
    "payee_new_and_spreading": lambda v: "new to RUKO in the last 2 days and already paid by several different people",
    "amount_inr": lambda v: f"amount {_inr(v)}",
    "amount_to_max_90d": lambda v: f"{_times(v)} the user's biggest payment in 90 days" if v >= 1 else None,
    "amount_to_median_90d": lambda v: f"{_times(v)} the user's usual payment" if v >= 1.5 else None,
    "first_time_payee": lambda v: "first payment to this payee",
    "entry_typed": lambda v: "UPI ID entered in the box (not scanned or picked from a contact)",
    "payee_in_contacts": lambda v: "the payee is a saved contact",
    "attempts_72h": lambda v: f"{v} payment tries in 72 h" if v >= 2 else None,
    "payee_in_run": lambda v: "part of a run of payments to new payees",
    "payee_micro_anchor": lambda v: "a small recent payment to this payee preceded this larger one (anchor pattern)",
    "outflow_24h_to_max_90d": lambda v: f"payments to new payees in the last 24 h add up to {_times(v)} the user's biggest-ever payment" if v >= 1.0 else None,
    "new_payee_sum_to_max_90d": lambda v: f"new payees got {_times(v)} the biggest usual payment in 72 h" if v >= 1 else None,
    "trusted_payee": lambda v: "the user said they know this payee",
    "session_dictated": lambda v: "the amount was typed slowly, digit by digit, as if dictated",
    "session_pasted_after_switch": lambda v: "the UPI ID was pasted right after switching from another app",
    "session_app_switches": lambda v: f"left the Pay screen {v} times" if v >= 2 else None,
    "session_hesitation": lambda v: "long pauses on the Pay screen",
    "session_abandoned_30m": lambda v: f"{v} abandoned tries in 30 min",
    "device_c": lambda v: f"the phone's own model: context {v:.2f}",
    "device_l": lambda v: f"the phone's own model: lure {v:.2f}",
    "device_b": lambda v: f"the phone's own model: behaviour {v:.2f}",
}
TIER_ACTION = {"T0": "no interruption", "T1": "a tip on the PIN screen", "T2": "an explain card (read, then slide to pay)",
               "T3": "a pause with a trusted-person call", "T4": "a hold for analyst review"}
STEP_WORDS = {
    "corroboration_gate": "fewer kinds of evidence were lit than needed, so RUKO did not interrupt",
    "trusted_payee": "the user had said they know this payee, so the alert was lowered",
    "alert_budget": "the user already had several alerts this month, so it was softened to a tip",
    "evidence_overlay": "RUKO's own cross-user evidence (e.g. a new account many people are paying) lit a family and raised the tier",
}


def input_words(name: str, value: Any) -> Optional[str]:
    if not _shown(value):
        return None
    fn = INPUT_WORDS.get(name)
    if fn is None:
        return f"{name} = {value}"
    try:
        return fn(value)
    except (TypeError, ValueError, IndexError):
        return f"{name} = {value}"


def summary(tier: str, f: dict, fams: dict, lit: list[str], steps: list[str], playbook: Optional[str],
            p_scam: Optional[float], policy_cfg: Optional[dict]) -> dict:
    """The decision in plain words: which kinds of evidence were lit, with the real values behind
    each, and how the policy turned that into the tier. Analyst only (it has numbers)."""
    cfg = policy_cfg or {}
    need = cfg.get("corroboration_min_families", 2)
    families = []
    for k in sorted(fams, key=lambda k: (k not in lit, -fams[k])):
        facts = [w for name, fam in FAMILY.items() if fam == k and (w := input_words(name, f.get(name)))]
        families.append({"family": k, "name": FAMILY_NAME.get(k, k), "score": fams[k], "lit": k in lit,
                         "facts": facts})
    n = len(lit)
    if tier == "T0" and n < need:
        headline = f"No interruption: only {n} of 4 kinds of evidence lit ({need} needed)."
    else:
        headline = f"{TIER_ACTION.get(tier, tier).capitalize()}, because {n} of 4 kinds of evidence were lit ({need} needed)."
    how = []
    rule = (cfg.get("tiers") or {}).get(tier)
    if rule:
        bits = [f"a scam score of at least {rule['min_p']:.2f}" + (f" (it was {p_scam:.2f})" if p_scam is not None else ""),
                f"at least {rule['min_families']} kinds of evidence lit"]
        if rule.get("requires_intel_hit"):
            bits.append("the payee or caller on a fraud list")
        how.append(f"{tier} needs " + ", ".join(bits) + ".")
    for st in steps:
        if st.startswith("amount_cap_"):
            how.append(f"Amounts under ₹{st[len('amount_cap_'):]} are capped at a tip.")
        elif st in STEP_WORDS:
            how.append(STEP_WORDS[st][0].upper() + STEP_WORDS[st][1:] + ".")
    return {"headline": headline, "lit_needed": need, "families": families, "how": how, "scam_type": playbook}
