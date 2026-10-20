"""One feature builder for every decision. `None` always means unknown, never 0 / false.

Families (corroboration counts families, not sources):
    C context    calls, remote control, sideloaded apps        (phone)
    L lure       scam-script messages                          (phone)
    P payee      bank features, MuleHunter, registry, FRI, NPCI name/type  (payee side)
    B behaviour  amount vs history, new payee, typed, tranches (payer side)
    S stage      journey stage (not a family; used for context)
"""
from __future__ import annotations

from features.user_baseline import UserBaseline
from api.intel import IntelResult
from schema.events import DecideRequest
from features.tracker import TrackerState

FRI_LEVEL = {"NONE": 0, "MEDIUM": 1, "HIGH": 2, "VERY_HIGH": 3}

FAMILY = {
    "on_call": "C", "caller_unknown": "C", "voip_call": "C", "foreign_caller": "C",
    "outgoing_to_unknown": "C", "remote_control": "C", "untrusted_accessibility": "C",
    "sideloaded_last_24h": "C",
    "lure_max_conf_72h": "L", "lure_tag": "L",
    "payee_holder_type": "P", "payee_verified_merchant": "P", "payee_account_age_days": "P",
    "payee_uniq_payers_6h": "P", "payee_uniq_payers_7d": "P", "payee_repeat_ratio": "P",
    "payee_pass_through_24h": "P", "payee_median_hold_min": "P", "payee_mulehunter": "P",
    "payee_registry_listed": "P", "payee_fri_level": "P", "caller_registry_listed": "P",
    "caller_fri_level": "P", "story_mismatch": "P", "vpa_invalid": "P",
    "amount_inr": "B", "amount_to_max_90d": "B", "amount_to_median_90d": "B",
    "first_time_payee": "B", "entry_typed": "B", "attempts_72h": "B",
    "new_payee_sum_to_max_90d": "B", "trusted_payee": "B",
    "stage": "S", "minutes_since_first_contact": "S",
}


def build_features(req: DecideRequest, st: TrackerState, intel: IntelResult,
                   base: UserBaseline, trusted: bool) -> dict:
    ctx = req.context
    call = ctx.call if ctx else None
    dev = ctx.device if ctx else None
    f: dict = {}

    # C — context
    f["on_call"] = st.on_call
    f["caller_unknown"] = None if call is None or call.caller_in_contacts is None else not call.caller_in_contacts
    f["voip_call"] = None if call is None or call.kind is None else call.kind == "voip"
    num = call.caller_number if call else None
    f["foreign_caller"] = None if not num else not num.startswith("+91")
    f["outgoing_to_unknown"] = None if call is None or call.direction is None else (
        call.direction == "outgoing" and call.caller_in_contacts is False)
    if dev is None:
        f["remote_control"] = f["untrusted_accessibility"] = f["sideloaded_last_24h"] = None
    else:
        recent = dev.remote_app_installed_min_ago
        f["remote_control"] = (None if dev.remote_access_active is None and recent is None
                               else bool(dev.remote_access_active) or (recent is not None and recent <= 120))
        f["untrusted_accessibility"] = dev.untrusted_accessibility
        f["sideloaded_last_24h"] = dev.sideloaded_last_24h

    # L — lure
    lures = [l for l in (ctx.lures if ctx else []) if l.tag != "normal" and l.min_ago <= 72 * 60]
    top = max(lures, key=lambda l: l.conf, default=None)
    f["lure_max_conf_72h"] = None if ctx is None else (top.conf if top else 0.0)
    f["lure_tag"] = top.tag if top else None

    # P — payee (what NPCI, the payee's bank and the lists said)
    npci, bank = intel.npci or {}, (intel.bank or {}).get("features") or {}
    f["vpa_invalid"] = intel.vpa_invalid
    f["payee_holder_type"] = npci.get("holder_type")
    f["payee_verified_merchant"] = npci.get("verified_merchant")
    f["payee_account_age_days"] = bank.get("account_age_days")
    f["payee_uniq_payers_6h"] = bank.get("uniq_payers_6h")
    f["payee_uniq_payers_7d"] = bank.get("uniq_payers_7d")
    f["payee_repeat_ratio"] = bank.get("repeat_payer_ratio_30d")
    f["payee_pass_through_24h"] = bank.get("pass_through_24h")
    f["payee_median_hold_min"] = bank.get("median_hold_min")
    f["payee_mulehunter"] = ((intel.bank or {}).get("mulehunter") or {}).get("score")
    f["payee_registry_listed"] = (intel.payee_registry or {}).get("listed")
    f["payee_fri_level"] = FRI_LEVEL.get((intel.payee_fri or {}).get("risk"))
    f["caller_registry_listed"] = (intel.caller_registry or {}).get("listed")
    f["caller_fri_level"] = FRI_LEVEL.get((intel.caller_fri or {}).get("risk"))
    # "Government" or "company" should never be a personal account.
    f["story_mismatch"] = (None if req.payer_says is None or f["payee_holder_type"] is None
                           else req.payer_says in ("government", "company") and f["payee_holder_type"] == "person")

    # B — behaviour (the payer's own history)
    f["amount_inr"] = req.amount_inr
    f["amount_to_max_90d"] = round(req.amount_inr / base.max_90d, 3) if base.max_90d else None
    f["amount_to_median_90d"] = round(req.amount_inr / base.median_90d, 3) if base.median_90d else None
    f["first_time_payee"] = req.payee_upi_id.lower() not in base.known_payees
    f["entry_typed"] = req.entry_method == "typed"
    f["attempts_72h"] = st.attempts_72h
    f["new_payee_sum_to_max_90d"] = round(st.new_payee_sum_72h / base.max_90d, 3) if base.max_90d else None
    f["trusted_payee"] = trusted

    # S — stage
    f["stage"] = int(st.stage[1])
    f["minutes_since_first_contact"] = st.minutes_since_first_contact
    return f
