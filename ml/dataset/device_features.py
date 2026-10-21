"""Features of the on-device model. Computed on the phone, never sent.

This module is also the spec for the Android side: every feature's meaning and null rule is here.
`None` means the phone could not measure it (group switched off, no permission, too little
history). It never means "safe".

The device model runs only when at least one Scam Shield group is on. Its three families:
    C  calls and remote control
    L  lure messages and small "reward" credits
    B  the user's own spending (all UPI apps, via this app's history and bank SMS) and
       behaviour on the pay screen
"""
from __future__ import annotations

import math

COLD_START_PAYMENTS = 10  # fewer own payments in 90 days -> personal comparisons are unknown
LURE_TAG_FEATURE = {"arrest_threat": "dev_lure_arrest", "kyc": "dev_lure_kyc", "task_job": "dev_lure_task",
                    "trading_tip": "dev_lure_trading", "refund": "dev_lure_refund"}

FAMILIES: dict[str, list[str]] = {
    "C": ["dev_call_active", "dev_call_voip", "dev_call_unknown", "dev_call_incoming", "dev_call_minutes",
          "dev_call_ended_min_ago", "dev_call_foreign", "dev_remote_installed", "dev_remote_min_ago",
          "dev_screen_recorded", "dev_accessibility", "dev_sideloaded_24h"],
    "L": ["dev_lure_max", *LURE_TAG_FEATURE.values(), "dev_lure_count_72h", "dev_lure_min_ago",
          "dev_bait_72h", "dev_bait_inr_72h", "dev_bait_30d", "dev_sent_to_received_72h"],
    "B": ["dev_amount_log10", "dev_entry_typed", "dev_entry_qr", "dev_first_time_payee", "dev_hist_n",
          "dev_amount_to_p95", "dev_amount_to_max", "dev_amount_to_median", "dev_out_1h", "dev_out_24h",
          "dev_new_payees_72h", "dev_escalation_steps", "dev_hour_share",
          "dev_sess_seconds", "dev_sess_pasted", "dev_sess_edits", "dev_sess_backgrounded",
          "dev_sess_cancelled_10m"],
}
ALL = [f for fam in FAMILIES.values() for f in fam]


def _b(x) -> float | None:
    return None if x is None else float(bool(x))


def device_features(raw: dict, history: dict, amount: float, entry: str, payee: str, t: float,
                    session: dict, any_shield: bool, escalation_factor: float = 1.5) -> dict:
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

    # L: every scam-tag message in 72 h, at any confidence (null when SMS checks are off)
    hits = raw["lure_hits"]
    money = raw["money"]
    if hits is None:
        for k in ("dev_lure_max", *LURE_TAG_FEATURE.values(), "dev_lure_count_72h", "dev_lure_min_ago"):
            f[k] = None
    else:
        f["dev_lure_max"] = max((c for _, c, _ in hits), default=0.0)
        for tag, name in LURE_TAG_FEATURE.items():
            f[name] = max((c for tg, c, _ in hits if tg == tag), default=0.0)
        f["dev_lure_count_72h"] = float(len(hits))
        f["dev_lure_min_ago"] = min((ago for _, _, ago in hits), default=None)
    sms_money = money is not None and money["bait_credits"] is not None
    f["dev_bait_72h"] = float(money["bait_credits"]) if sms_money else None
    f["dev_bait_inr_72h"] = float(money["bait_inr"]) if sms_money else None
    f["dev_bait_30d"] = float(money["bait_30d"]) if sms_money else None
    f["dev_sent_to_received_72h"] = (round((money["debits_inr"] + amount) / money["credits_inr"], 3)
                                     if sms_money and money["credits_inr"] else None)

    # B: this payment against the user's own history, and the pay screen
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
    f["dev_new_payees_72h"] = None if money is None else float(money["new_payees"])
    if money is None:
        f["dev_escalation_steps"] = None
    else:
        steps = money["escalation_steps"]
        last = money["last_debit_inr"]
        # Does this payment continue the run? (same rule as features.build)
        f["dev_escalation_steps"] = float(steps + 1 if last and amount >= escalation_factor * last else 0)
    f["dev_hour_share"] = _hour_share(history["ts"], t) if warm else None
    f["dev_sess_seconds"] = session["seconds"]
    f["dev_sess_pasted"] = _b(session["pasted"])
    f["dev_sess_edits"] = float(session["edits"])
    f["dev_sess_backgrounded"] = _b(session["backgrounded"])
    f["dev_sess_cancelled_10m"] = float(session["cancelled_10m"])
    return f


IST_OFFSET_S = 5.5 * 3600


def _hour_share(past: list[float], t: float) -> float:
    """Share of the user's past payments made within 90 minutes (clock time, IST) of this one."""
    def clock(x: float) -> float:
        return ((x + IST_OFFSET_S) % 86400) / 3600

    now = clock(t)
    near = sum(1 for x in past if min(abs(clock(x) - now), 24 - abs(clock(x) - now)) <= 1.5)
    return round(near / len(past), 3)
