"""A citizen's ordinary life for the whole window: payments, rent, bills, calls, spam, app installs.

Drawn from the user's own streams ("routine", user), ("calls", user), ..., so a user's life does not
change when the world gets bigger or smaller.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from sim_v2 import rails
from sim_v2.world import World

SPAM_TAGS = {"kyc": 0.35, "trading_tip": 0.25, "task_job": 0.2, "refund": 0.15, "arrest_threat": 0.05}


def _mix(g, n, p):
    tail = g.random(n) < p["tail_weight"]
    return np.where(tail, g.lognormal(np.log(p["tail_median"]), p["tail_sigma"], n),
                    g.lognormal(np.log(p["bulk_median"]), p["bulk_sigma"], n))


def _times(w: World, g, days: np.ndarray):
    hours = g.choice(24, size=len(days), p=np.array(w.hour_p) / sum(w.hour_p))
    secs = days * 86400 + hours * 3600 + g.uniform(0, 3600, len(days))
    return [w.start + timedelta(seconds=float(s)) for s in secs]


def _round(g, amounts: np.ndarray, share: float) -> np.ndarray:
    big = amounts >= 500
    r = g.random(len(amounts)) < share
    return np.where(r & big, np.round(amounts, -2), np.where(r, np.round(amounts, -1), np.round(amounts)))


def _round1(r, a: float, share: float) -> float:
    """People round some amounts: to ₹100 when ≥ ₹500, else to ₹10."""
    if r.chance(share):
        return float(round(a, -2) if a >= 500 else round(a, -1)) or 10.0
    return float(round(a)) or 1.0


def routine(w: World, u: dict) -> None:
    cfg, uid, me = w.cfg, u["user_id"], u["upi_id"]
    r = w.r("routine", uid)
    g = r.g
    persona = cfg.get("population.personas")[u["persona"]]
    wf = np.array(cfg.get("routine.weekday_factor"))
    day_idx = np.arange(cfg.days)
    weekday = np.array([(w.start + timedelta(days=int(d))).weekday() for d in day_idx])
    counts = g.poisson(u["rate"] * wf[weekday])
    days = np.repeat(day_idx, counts).astype(float)
    n = len(days)
    if n:
        ts = _times(w, g, days)
        p2m = g.random(n) < persona["p2m"] + cfg.get("amounts.p2m_shift")
        amt = np.where(p2m, _mix(g, n, cfg.get("amounts.p2m")), _mix(g, n, cfg.get("amounts.p2p"))) * persona["mult"]
        amt = np.minimum(np.maximum(amt, 1), cfg.get("amounts.p2p_cap"))
        rs = cfg.get("amounts.round_share")
        ent_m, ent_p = cfg.get("routine.entry_p2m"), cfg.get("routine.entry_p2p")
        zipf = lambda k: (x := 1 / np.arange(1, k + 1)) / x.sum()
        loc = w.localities[u["locality"]]
        zs, zc = zipf(len(u["shops"])), zipf(len(u["contacts"]))   # favourite shops / people get most payments
        new_n = 0
        for k in range(n):
            if p2m[k]:
                if r.chance(cfg.get("routine.new_shop_p")):
                    to = r.choice(loc["shops"] + loc["kiranas"] + loc["pharmacy"])
                else:
                    to = r.choice(u["shops"], zs)
                entry = r.weighted(ent_m)
                a = _round1(r, float(amt[k]), rs["p2m"])
            else:
                if r.chance(cfg.get("routine.new_person_p")):
                    to = w.person(("new_person", uid, new_n), u["region"])["upi_id"]
                    new_n += 1
                    entry = r.weighted({"typed": 0.6, "qr": 0.25, "contact": 0.15})
                else:
                    to = r.choice(u["contacts"], zc)
                    entry = r.weighted(ent_p)
                a = _round1(r, float(amt[k]), rs["p2p_contact"] if entry == "contact" else rs["p2p_typed"])
            rails.pay(w, ts[k], me, to, a, entry, "normal")
            if p2m[k] and r.chance(cfg.get("routine.cashback_p")):   # merchant / app cashback credit
                rails.pay(w, ts[k] + timedelta(minutes=r.uniform(1, 60)), r.choice(w.billers[:2]), me,
                          max(1, round(a * r.uniform(0.01, 0.1))), "qr", "cashback")
    # rent and bills: monthly, on the user's own day
    for d in range(cfg.days):
        day = w.start + timedelta(days=d)
        at = day.replace(hour=r.integer(8, 21), minute=r.integer(0, 59))
        if u["landlord"] and day.day == u["rent_day"]:
            rent = round(r.loguniform(*cfg.get("routine.rent_inr")["log"]), -2)
            rails.pay(w, at, me, u["landlord"], rent, r.weighted({"contact": 0.6, "typed": 0.4}), "normal", scenario="rent")
        if u["pays_bill"] and day.day == u["bill_day"]:
            rails.pay(w, at, me, r.choice(w.billers), round(r.loguniform(150, 4000)), r.weighted({"qr": 0.5, "typed": 0.5}),
                      "normal", scenario="bill")


def calls_and_phone(w: World, u: dict) -> None:
    """Ordinary calls, spam lures, app installs: the background every scam signal must stand out from."""
    cfg, uid = w.cfg, u["user_id"]
    r = w.r("calls", uid)
    g = r.g
    days = np.repeat(np.arange(cfg.days), g.poisson(cfg.get("telecom.calls_per_day"), cfg.days)).astype(float)
    mix = cfg.get("telecom.call_mix")
    for ts in _times(w, g, days):
        kind = r.weighted(mix)
        mins = r.loguniform(*cfg.get("telecom.call_minutes")["log"])
        if kind == "known":
            num, contact, ck = w.accounts[r.choice(u["contacts"])]["mobile"], True, "sim"
        elif kind == "voip_known":
            num, contact, ck = w.accounts[r.choice(u["contacts"])]["mobile"], True, "voip"
        elif kind == "foreign_spam":
            num, contact, ck = rails.number(w, r, foreign=True), False, "voip"
        else:   # delivery, bank, spam callers
            num, contact, ck = rails.number(w, r), False, "sim"
        rails.call(w, ts, uid, num, mins, in_contacts=contact, kind=ck, direction=r.weighted({"incoming": 0.6, "outgoing": 0.4}))
    s = w.r("sms", uid)
    for ts in _times(w, s.g, np.repeat(np.arange(cfg.days), s.g.poisson(cfg.get("sms.spam_lures_per_day"), cfg.days)).astype(float)):
        rails.lure(w, ts, uid, s.weighted(SPAM_TAGS), s.uniform(*cfg.get("sms.spam_conf")))
    for ts in _times(w, s.g, np.repeat(np.arange(cfg.days), s.g.poisson(cfg.get("sms.notification_lures_per_day"), cfg.days)).astype(float)):
        rails.lure(w, ts, uid, "trading_tip", s.uniform(0.3, 0.8), notification=True)
    d = w.r("device", uid)
    n_inst = d.poisson(cfg.get("device.app_installs_per_30d") * cfg.days / 30)
    for ts in _times(w, d.g, d.g.uniform(0, cfg.days, n_inst).astype(int).astype(float)):
        side = d.chance(cfg.get("device.sideload_share"))
        rails.event(w, ts, uid, "app_installed", {"pkg": f"com.app{d.integer(0, 9999)}", "is_remote_access": False, "sideloaded": side})
    if u["age_band"] == "60+" and d.chance(cfg.get("device.senior_accessibility")):
        ts = w.start + timedelta(days=d.uniform(0, cfg.days))
        rails.event(w, ts, uid, "accessibility_enabled", {"pkg": "com.google.android.marvin.talkback"})
