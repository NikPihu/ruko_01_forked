"""Features of the on-device model (contract c2-0.5 inputs plus private readings). Never sent.

This module is also the spec for the Android side: every feature's meaning and null rule is here.
`None` means the phone could not measure it (group switched off, no permission, too little
history). It never means "safe" (CLAUDE.md rule 1).

The device model runs only when at least one Scam Shield group is on. Its three families keep the
engine's rule 5 (one source of evidence never lights two families):
    C  calls and remote control
    L  lure messages and the whole task-scam episode (one phone summary -> one family)
    B  the user's own spending (all UPI apps) and behaviour on the Pay screen
"""
from __future__ import annotations

import math

from features.episode import STATE_CODE

COLD_START_PAYMENTS = 10  # fewer own payments in 90 days -> personal comparisons are unknown
LURE_TAG_FEATURE = {"arrest_threat": "dev_lure_arrest", "kyc": "dev_lure_kyc", "task_job": "dev_lure_task",
                    "trading_tip": "dev_lure_trading", "refund": "dev_lure_refund"}
# contracts/README.md `session` fields -> device features (same numbers the phone sends).
SESSION_FEATURE = {"amount_digits": "dev_sess_digits", "amount_median_gap_s": "dev_sess_median_gap_s",
                   "amount_max_gap_s": "dev_sess_max_gap_s", "amount_gap_vs_usual": "dev_sess_gap_vs_usual",
                   "amount_edits": "dev_sess_edits", "payee_pasted": "dev_sess_pasted",
                   "pasted_within_s_of_return": "dev_sess_paste_after_return_s",
                   "app_switches": "dev_sess_app_switches", "away_s": "dev_sess_away_s",
                   "pay_screen_s": "dev_sess_pay_screen_s", "abandoned_flows_30m": "dev_sess_abandoned_30m"}

FAMILIES: dict[str, list[str]] = {
    "C": ["dev_call_active", "dev_call_voip", "dev_call_unknown", "dev_call_incoming", "dev_call_minutes",
          "dev_call_ended_min_ago", "dev_call_foreign", "dev_remote_installed", "dev_remote_min_ago",
          "dev_screen_recorded", "dev_accessibility", "dev_sideloaded_24h"],
    "L": ["dev_lure_max", *LURE_TAG_FEATURE.values(), "dev_lure_count_72h", "dev_lure_min_ago",
          "dev_ep_state", "dev_ep_age_days", "dev_ep_bait_credits", "dev_ep_bait_inr", "dev_ep_outs",
          "dev_ep_new_payees", "dev_ep_escalation", "dev_ep_out_to_in", "dev_ep_payee_seen"],
    "B": ["dev_amount_log10", "dev_entry_typed", "dev_entry_qr", "dev_first_time_payee", "dev_hist_n",
          "dev_amount_to_p95", "dev_amount_to_max", "dev_amount_to_median", "dev_out_1h", "dev_out_24h",
          "dev_hour_share", *SESSION_FEATURE.values()],
}
ALL = [f for fam in FAMILIES.values() for f in fam]


def _b(x) -> float | None:
    return None if x is None else float(bool(x))


def _n(x) -> float | None:
    return None if x is None else float(x)


def device_features(raw: dict, history: dict, amount: float, entry: str, payee: str, t: float,
                    any_shield: bool, escalation_factor: float = 1.5) -> dict:
    """raw: PhoneView.context_at readings; history: PhoneView.own_history; t: epoch seconds."""
    if not any_shield:
        return dict.fromkeys(ALL)
    f: dict = {}

    # C: calls (null when call signals are off) and remote control (null when app checks are off)
    call = raw["call"]
    f["dev_call_active"] = None if call is None else _b(call["active"])
    f["dev_call_voip"] = None if call is None or call["kind"] is None else _b(call["kind"] == "voip")
    f["dev_call_unknown"] = None if call is None or call["in_contacts"] is None else _b(not call["in_contacts"])
    f["dev_call_incoming"] = (None if call is None or call["direction"] is None
                              else _b(call["direction"] == "incoming"))
    f["dev_call_minutes"] = None if call is None else call["started_min_ago"]
    f["dev_call_ended_min_ago"] = None if call is None else call["ended_min_ago"]
    f["dev_call_foreign"] = None if call is None else _b(call["foreign"])
    dev = raw["device"]
    f["dev_remote_installed"] = None if dev is None else _b(dev["remote_installed"])
    f["dev_remote_min_ago"] = None if dev is None else dev["remote_min_ago"]
    f["dev_screen_recorded"] = None if dev is None else _b(dev["screen_recorded"])
    f["dev_accessibility"] = None if dev is None else _b(dev["accessibility"])
    f["dev_sideloaded_24h"] = None if dev is None else _b(dev["sideloaded_24h"])

    # L: every scam-tag SMS in 72 h at any confidence (null without SMS checks), and the episode
    hits = raw["lure_hits"]
    if hits is None:
        for k in ("dev_lure_max", *LURE_TAG_FEATURE.values(), "dev_lure_count_72h", "dev_lure_min_ago"):
            f[k] = None
    else:
        f["dev_lure_max"] = max((c for _, c, _ in hits), default=0.0)
        for tag, name in LURE_TAG_FEATURE.items():
            f[name] = max((c for tg, c, _ in hits if tg == tag), default=0.0)
        f["dev_lure_count_72h"] = float(len(hits))
        f["dev_lure_min_ago"] = min((ago for _, _, ago in hits), default=None)
    ep = raw["episode"]
    if ep is None:
        for k in FAMILIES["L"][FAMILIES["L"].index("dev_ep_state"):]:
            f[k] = None
    else:
        f["dev_ep_state"] = float(STATE_CODE[ep["state"]])
        f["dev_ep_age_days"] = _n(ep["age_days"])
        f["dev_ep_bait_credits"] = _n(ep["bait_credits"])
        f["dev_ep_bait_inr"] = _n(ep["bait_inr"])
        f["dev_ep_outs"] = _n(ep["outs"])
        f["dev_ep_new_payees"] = _n(ep["new_payees"])
        steps, last = ep["escalation_steps"], ep["last_out_inr"]
        # Does this payment continue the run? (same rule as features.build)
        f["dev_ep_escalation"] = (None if steps is None else
                                  float(steps + 1 if last and amount >= escalation_factor * last else 0))
        f["dev_ep_out_to_in"] = _n(ep["out_to_in_ratio"])
        f["dev_ep_payee_seen"] = _b(ep["payee_seen_in_episode"])

    # B: this payment against the user's own history, and the Pay screen
    n = len(history["amounts"])
    warm = n >= COLD_START_PAYMENTS
    f["dev_amount_log10"] = math.log10(amount)
    f["dev_entry_typed"] = _b(entry == "typed")
    f["dev_entry_qr"] = _b(entry == "qr")
    f["dev_first_time_payee"] = _b(payee not in history["payees"])
    f["dev_hist_n"] = float(n)
    f["dev_amount_to_p95"] = round(amount / history["p95"], 3) if warm and history["p95"] else None
    f["dev_amount_to_max"] = round(amount / history["max"], 3) if warm and history["max"] else None
    f["dev_amount_to_median"] = round(amount / history["median"], 3) if warm and history["median"] else None
    f["dev_out_1h"] = float(sum(1 for x in history["ts"] if x >= t - 3600))
    f["dev_out_24h"] = float(sum(1 for x in history["ts"] if x >= t - 86400))
    f["dev_hour_share"] = _hour_share(history["ts"], t) if warm else None
    ses = raw["session"]
    for key, name in SESSION_FEATURE.items():
        v = None if ses is None else ses.get(key)
        f[name] = _b(v) if isinstance(v, bool) else _n(v)
    return f


IST_OFFSET_S = 5.5 * 3600


def _hour_share(past: list[float], t: float) -> float:
    """Share of the user's past payments made within 90 minutes (clock time, IST) of this one."""
    def clock(x: float) -> float:
        return ((x + IST_OFFSET_S) % 86400) / 3600

    now = clock(t)
    near = sum(1 for x in past if min(abs(clock(x) - now), 24 - abs(clock(x) - now)) <= 1.5)
    return round(near / len(past), 3)
