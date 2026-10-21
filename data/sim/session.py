"""How each RUKO user behaved on the Pay screen (contract c2-0.5 `context.session`).

One `pay_session` context event per payment a RUKO user makes, at the payment's own time, holding
the same numbers the phone sends (field meanings: contracts/README.md):
    coached call scams   (digital_arrest, fake_customer_care, refund_qr) amount read out digit by
                         digit, app left for the call, often the mule's ID pasted from WhatsApp
    chat scams           (task_job, trading_group) the payee pasted from Telegram / WhatsApp
    fake_kyc_apk         mixed (the scammer may also be typing through the remote app)
    normal life          calm, with a personal typing speed (older users are slower on average,
                         but there are slow typists in every age band)
Hard negatives: a family member's or a biller's UPI ID pasted right after leaving the app, long
hesitation over a big hospital bill, a payment started, abandoned and done later.

Draws only from its own random stream, so the rest of the world stays byte-identical.
"""
from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict

from .world import World

COACHED_CALL = {"digital_arrest", "fake_customer_care", "refund_qr"}
CHAT = {"task_job", "trading_group"}
TYPICAL_GAP_S = {"18-29": 0.35, "30-44": 0.45, "45-59": 0.6, "60+": 0.85}
BASELINE_MIN, BASELINE_KEEP = 3, 10       # same as the phone: ratio only after 3 past payments
CALM_SHARE_OF_SCAM = 0.15                 # some victims are not coached on the Pay screen itself


def build_sessions(w: World) -> None:
    rng = random.Random(w.cfg.seed + 2000)
    by_upi = {u["upi_id"]: u for u in w.users}
    playbook = {j["journey_id"]: j["playbook"] for j in w.journeys}
    hospitals = set(w.hospitals)
    speed = {u["user_id"]: TYPICAL_GAP_S[u["age_band"]] * rng.lognormvariate(0, 0.45) for u in w.users}
    history: dict[str, list[float]] = defaultdict(list)   # past median gaps, as the phone keeps them
    abandoned_at: dict[str, float] = {}

    for row in sorted(w.ledger, key=lambda r: r["ts"]):
        u = by_upi.get(row["from_upi"])
        if u is None:
            continue
        uid, ts = u["user_id"], row["ts"].timestamp()
        pb = playbook.get(row["journey_id"]) if row["label_is_scam"] else None
        kind = ("coached" if pb in COACHED_CALL else "chat" if pb in CHAT else "mixed" if pb
                else "normal")
        if kind != "normal" and rng.random() < CALM_SHARE_OF_SCAM:
            kind = "normal"
        s = _session(rng, kind, speed[uid], row, hospitals)

        past = history[uid]
        s["amount_gap_vs_usual"] = (round(s["amount_median_gap_s"] / statistics.median(past), 1)
                                    if len(past) >= BASELINE_MIN else None)
        last = abandoned_at.get(uid)
        s["abandoned_flows_30m"] = 1 if last is not None and ts - last <= 1800 else 0
        # A payment that was started and abandoned a little earlier (scam: told to "try again").
        if rng.random() < (0.35 if kind in ("coached", "mixed") else 0.03):
            s["abandoned_flows_30m"] += 1
        abandoned_at.pop(uid, None)
        if rng.random() < (0.2 if kind != "normal" else 0.02):
            abandoned_at[uid] = ts + 60   # a follow-up attempt soon after this one sees it

        w.event(row["ts"], uid, "pay_session", s, row["journey_id"], row["label_stage"])
        # Like the phone: every completed payment updates the baseline (it can't tell scams apart).
        past.append(s["amount_median_gap_s"])
        del past[:-BASELINE_KEEP]


def _session(rng: random.Random, kind: str, usual: float, row: dict, hospitals: set[str]) -> dict:
    digits = len(str(int(row["amount"])))
    typed_payee = row["entry_method"] == "typed"
    if kind == "coached":
        gap = usual * rng.uniform(2.5, 7.0) if rng.random() < 0.8 else usual * rng.uniform(1.0, 2.0)
        switches = rng.choice((1, 2, 2, 3, 4)) if rng.random() < 0.75 else 0
        pasted = typed_payee and rng.random() < 0.5
        screen = rng.uniform(60, 420)
    elif kind == "chat":
        gap = usual * rng.uniform(0.8, 1.6) if rng.random() < 0.9 else usual * rng.uniform(2.5, 4.0)
        switches = rng.choice((1, 1, 2, 3))
        pasted = typed_payee and rng.random() < 0.85
        screen = rng.uniform(30, 150)
    elif kind == "mixed":
        gap = usual * rng.uniform(1.0, 5.0)
        switches = rng.choice((0, 1, 2))
        pasted = typed_payee and rng.random() < 0.4
        screen = rng.uniform(40, 240)
    else:
        gap = usual * rng.lognormvariate(0, 0.2)
        switches = rng.choices((0, 1, 2), weights=(85, 12, 3))[0]
        # Hard negative: a family member's or biller's ID pasted from WhatsApp / a bill SMS.
        pasted = typed_payee and rng.random() < 0.15
        screen = rng.lognormvariate(math.log(20), 0.5)
        if row["to_upi"] in hospitals:   # hard negative: hesitating over a big hospital bill
            screen = rng.uniform(120, 400)
    gap = max(gap, 0.1)  # the phone rounds to 0.1 s
    if pasted and switches == 0 and rng.random() < 0.6:
        switches = 1   # copied it from another app
    away = sum(rng.uniform(3, 60) for _ in range(switches))
    return {
        "amount_digits": digits,
        "amount_median_gap_s": round(gap, 1),
        "amount_max_gap_s": round(gap * rng.uniform(1.3, 2.6), 1) if digits > 1 else round(gap, 1),
        "amount_edits": rng.choices((0, 1, 2), weights=(80, 15, 5))[0],
        "payee_pasted": pasted if typed_payee else False,
        "pasted_within_s_of_return": round(rng.uniform(2, 15), 1) if pasted and switches else None,
        "app_switches": switches,
        "away_s": round(away, 1),
        "pay_screen_s": round(screen, 1),
    }
