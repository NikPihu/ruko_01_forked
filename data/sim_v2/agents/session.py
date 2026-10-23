"""How each user behaved on the Pay screen: one `pay_session` event per payment (contract c2-0.5).

Ported from data/sim/session.py (same keys, same coached / chat / mixed / normal behaviour), but
drawn from each user's own stream so it is stable when the world is resized.
"""
from __future__ import annotations

import math
import statistics

from sim_v2.core.tables import attrs

COACHED_CALL = {"digital_arrest", "fake_customer_care", "refund_qr"}
CHAT = {"task_job", "trading_group"}
BASELINE_MIN, BASELINE_KEEP = 3, 10


def sessions(w, ledger_rows: list[dict], users: dict, playbook_of: dict, hospitals: set) -> list[tuple]:
    """ledger_rows: this user's payments in time order. Returns context_events rows."""
    out = []
    by_user: dict[str, list] = {}
    for row in ledger_rows:
        u = users.get(row["from_upi"])
        if u is not None:
            by_user.setdefault(u["user_id"], []).append(row)
    typical = w.cfg.get("session.typical_gap_s")
    calm = w.cfg.get("session.calm_share_of_scam")
    for uid, rows in by_user.items():
        u = users[rows[0]["from_upi"]]
        r = w.r("session", uid)
        speed = typical[u["age_band"]] * r.lognormal(1, 0.45)
        past, abandoned_at = [], None
        for row in rows:
            pb = playbook_of.get(row["journey_id"]) if row["label_is_scam"] else None
            kind = "coached" if pb in COACHED_CALL else "chat" if pb in CHAT else "mixed" if pb else "normal"
            if kind != "normal" and r.chance(calm):
                kind = "normal"
            s = _session(r, kind, speed, row, hospitals)
            s["amount_gap_vs_usual"] = (round(s["amount_median_gap_s"] / statistics.median(past), 1)
                                        if len(past) >= BASELINE_MIN else None)
            ts = row["ts"].timestamp()
            s["abandoned_flows_30m"] = 1 if abandoned_at is not None and ts - abandoned_at <= 1800 else 0
            if r.chance(0.35 if kind in ("coached", "mixed") else 0.03):
                s["abandoned_flows_30m"] += 1
            abandoned_at = ts + 60 if r.chance(0.2 if kind != "normal" else 0.02) else None
            out.append((row["ts"], uid, "pay_session", attrs(s), row["journey_id"], row["journey_id"] is not None,
                        row["label_stage"], row["scenario"], row["cause_id"]))
            past.append(s["amount_median_gap_s"])
            del past[:-BASELINE_KEEP]
    return out


def _session(r, kind: str, usual: float, row: dict, hospitals: set) -> dict:
    digits = len(str(int(row["amount"])))
    typed_payee = row["entry_method"] == "typed"
    if kind == "coached":
        gap = usual * r.uniform(2.5, 7.0) if r.chance(0.8) else usual * r.uniform(1.0, 2.0)
        switches = r.choice((1, 2, 2, 3, 4)) if r.chance(0.75) else 0
        pasted, screen = typed_payee and r.chance(0.5), r.uniform(60, 420)
    elif kind == "chat":
        gap = usual * r.uniform(0.8, 1.6) if r.chance(0.9) else usual * r.uniform(2.5, 4.0)
        switches = r.choice((1, 1, 2, 3))
        pasted, screen = typed_payee and r.chance(0.85), r.uniform(30, 150)
    elif kind == "mixed":
        gap = usual * r.uniform(1.0, 5.0)
        switches = r.choice((0, 1, 2))
        pasted, screen = typed_payee and r.chance(0.4), r.uniform(40, 240)
    else:
        gap = usual * r.lognormal(1, 0.2)
        switches = r.weighted({0: 85, 1: 12, 2: 3})
        pasted = typed_payee and r.chance(0.15)        # a family member's or biller's ID pasted
        screen = r.lognormal(20, 0.5)
        if row["to_upi"] in hospitals:                  # hesitating over a big hospital bill
            screen = r.uniform(120, 400)
    gap = max(gap, 0.1)
    if pasted and switches == 0 and r.chance(0.6):
        switches = 1
    away = sum(r.uniform(3, 60) for _ in range(switches))
    return {"amount_digits": digits, "amount_median_gap_s": round(gap, 1),
            "amount_max_gap_s": round(gap * r.uniform(1.3, 2.6), 1) if digits > 1 else round(gap, 1),
            "amount_edits": r.weighted({0: 80, 1: 15, 2: 5}), "payee_pasted": bool(pasted) if typed_payee else False,
            "pasted_within_s_of_return": round(r.uniform(2, 15), 1) if pasted and switches else None,
            "app_switches": int(switches), "away_s": round(away, 1), "pay_screen_s": round(screen, 1)}
