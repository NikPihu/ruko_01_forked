"""A case as a sequence of tokens: what the server saw at each payment, plus the time between payments.

Every token is defined with the same matcher format playbooks use (blue_team/matcher.py), so a token
and a playbook rule can never disagree about what a feature means, and the offline drafter can turn
a cluster's typical tokens straight into a matcher. Only engine features and request fields are
used: never SMS text, never ground truth.

    PAY CALL_ON CALLER_UNKNOWN SAYS_FAMILY AMT_10K_50K NEW_PAYEE  GAP_UNDER_1H  PAY CALL_ON ...
"""
from __future__ import annotations

from blue_team import matcher

UNKNOWN_CALLER = {"any": [{"feature": "caller_unknown", "op": "is", "value": True},
                          {"all": [{"feature": "voip_call", "op": "is", "value": True},
                                   {"feature": "caller_unknown", "op": "is_null"}]}]}


def _is(feature: str) -> dict:
    return {"feature": feature, "op": "is", "value": True}


def _eq(feature: str, value) -> dict:
    return {"feature": feature, "op": "eq", "value": value}


def _range(feature: str, lo: float | None, hi: float | None) -> dict:
    parts = ([{"feature": feature, "op": ">=", "value": lo}] if lo is not None else []) + \
            ([{"feature": feature, "op": "<", "value": hi}] if hi is not None else [])
    return parts[0] if len(parts) == 1 else {"all": parts}


TOKENS: dict[str, dict] = {
    # C: the call and who controls the phone
    "CALL_ON": _is("on_call"),
    "CALL_VOIP": _is("voip_call"),
    "CALLER_UNKNOWN": UNKNOWN_CALLER,
    "CALL_OUT_TO_UNKNOWN": _is("outgoing_to_unknown"),
    "CALLER_FOREIGN": _is("foreign_caller"),
    "CALL_SPEAKER": _is("call_on_speaker"),
    "CALLER_LISTED": _is("caller_registry_listed"),
    "REMOTE_CONTROL": _is("remote_control"),
    "ACCESSIBILITY": _is("untrusted_accessibility"),
    "SIDELOAD": _is("sideloaded_last_24h"),
    # L: lures and the task-scam episode
    **{f"LURE_{t.upper()}": _eq("lure_tag", t) for t in ("arrest_threat", "kyc", "task_job", "trading_tip", "refund")},
    "EPISODE_WATCHING": _eq("episode_state", 1),
    "EPISODE_ACTIVE": _eq("episode_state", 2),
    "BAIT_CREDITS": {"feature": "episode_bait_credits", "op": ">=", "value": 1},
    # B: the payment against the payer's habits and the Pay screen
    **{f"ENTRY_{e.upper()}": _eq("entry_method", e) for e in ("typed", "qr", "contact", "collect")},
    **{f"SAYS_{s.upper()}": _eq("payer_says", s) for s in ("government", "company", "family", "shop", "investment", "other")},
    "AMT_UNDER_1K": _range("amount_inr", None, 1000),
    "AMT_1K_10K": _range("amount_inr", 1000, 10000),
    "AMT_10K_50K": _range("amount_inr", 10000, 50000),
    "AMT_50K_PLUS": _range("amount_inr", 50000, None),
    "AMT_UNUSUAL": {"feature": "amount_to_max_90d", "op": ">=", "value": 1.5},
    "NEW_PAYEE": _is("first_time_payee"),
    "PAYEE_IN_CONTACTS": _is("payee_in_contacts"),
    "REPEAT_ATTEMPTS": {"feature": "attempts_72h", "op": ">=", "value": 2},
    "PAYEE_IN_RUN": _is("payee_in_run"),
    "SESSION_DICTATED": _is("session_dictated"),
    "SESSION_PASTE_AFTER_SWITCH": _is("session_pasted_after_switch"),
    "SESSION_HESITATION": _is("session_hesitation"),
    "SESSION_ABANDONED": {"feature": "session_abandoned_30m", "op": ">=", "value": 1},
    # P: the payee as banks, lists and the payment graph see it
    "PAYEE_PERSON": _eq("payee_holder_type", "person"),
    "PAYEE_VERIFIED_MERCHANT": _is("payee_verified_merchant"),
    "PAYEE_YOUNG_ACCOUNT": {"feature": "payee_account_age_days", "op": "<", "value": 30},
    "PAYEE_PASS_THROUGH": {"feature": "payee_pass_through_24h", "op": ">=", "value": 0.5},
    "PAYEE_LISTED": _is("payee_registry_listed"),
    "PAYEE_MULEHUNTER": {"feature": "payee_mulehunter", "op": ">=", "value": 0.5},
    "PAYEE_FORWARDS_TO_CASHOUT": _is("payee_forwards_to_cashout"),
    "PAYEE_MONEY_LOOP": _is("payee_money_loop"),
    "STORY_MISMATCH": _is("story_mismatch"),
}
GAPS = ((10 * 60, "GAP_UNDER_10M"), (3600, "GAP_UNDER_1H"), (86400, "GAP_UNDER_1D"), (float("inf"), "GAP_OVER_1D"))


def payment_tokens(f: dict) -> list[str]:
    return [name for name, rule in TOKENS.items() if matcher.matches(rule, f)]


def gap_token(seconds: float) -> str:
    return next(name for limit, name in GAPS if seconds < limit)


def case_document(payments: list[tuple[float, dict]]) -> str:
    """One case (payments in time order as (ts, features)) as a text of tokens for TF-IDF."""
    out, last = [], None
    for ts, f in payments:
        if last is not None:
            out.append(gap_token(ts - last))
        out += ["PAY", *payment_tokens(f)]
        last = ts
    return " ".join(out)
