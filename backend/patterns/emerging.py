"""Emerging patterns: scam workflows RUKO has no name for yet (A4).

Offline and analyst-only, never in the payment decision (rule 13). From the transaction database
it takes recent flagged and near-miss payments that matched NO known playbook, gives each a
signature in plain signals (which families lit, how the user was reached, what control the
scammer had, how the Pay screen was used, the amount band) and groups payments with the same
signature. A group from enough different people that is still growing is an emerging pattern:
a new scam workflow, described in words for an analyst to name (a draft playbook for the data
folder) or dismiss. Thresholds: policy.yaml `emerging:`.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from store.db import TxnStore

_DEFAULTS = {"window_days": 7, "min_payments": 5, "min_users": 3, "near_miss_families": 1}
_POLICY = Path(__file__).resolve().parents[1] / "api" / "policy.yaml"
T = {**_DEFAULTS, **((yaml.safe_load(_POLICY.read_text()) or {}).get("emerging") or {})}

FAMILY_WORD = {"C": "context", "L": "lure", "P": "payee", "B": "behaviour"}
AMOUNT_BANDS = ((2_000, "under ₹2k"), (20_000, "₹2k–20k"), (100_000, "₹20k–1L"), (float("inf"), "over ₹1L"))


def amount_band(inr: float) -> str:
    return next(label for top, label in AMOUNT_BANDS if inr < top)


def signature(payment: dict, f: dict, lit: list[str]) -> dict:
    """The plain signals that describe how this payment happened. Unknown stays unknown (None)."""
    call = None
    if f.get("on_call"):
        call = ("video call" if f.get("video_call") else "VoIP call" if f.get("voip_call") else "phone call")
        if f.get("outgoing_to_unknown"):
            call = "user called an unknown number"
        elif f.get("caller_unknown") is not False:
            call = f"{call} from an unknown caller"
    control = ("screen control" if f.get("remote_control") else
               "app from outside the store" if f.get("sideloaded_last_24h") else None)
    pay_screen = [w for k, w in (("session_dictated", "amount dictated"),
                                 ("session_pasted_after_switch", "UPI ID pasted after switching apps")) if f.get(k)]
    return {
        "families": sorted(lit),
        "call": call,
        "lure": f.get("lure_tag"),
        "control": control,
        "pay_screen": pay_screen,
        "entry": payment.get("entry_method"),
        "new_payee": bool(f.get("first_time_payee")),
        "amount": amount_band(payment["amount_inr"]),
    }


def describe(sig: dict) -> str:
    steps = [s for s in (sig["call"], f"a '{sig['lure']}' message" if sig["lure"] else None, sig["control"],
                         *sig["pay_screen"], "a new payee" if sig["new_payee"] else None) if s]
    lit = ", ".join(FAMILY_WORD[f] for f in sig["families"]) or "no family"
    return f"{' → '.join(steps) or 'no phone signals'}, {sig['amount']} (evidence: {lit})"


def pattern_id(sig: dict) -> str:
    return "pat_" + hashlib.sha256(json.dumps(sig, sort_keys=True).encode()).hexdigest()[:10]


def find(store: TxnStore, now: datetime, reviews: dict[str, dict] | None = None) -> list[dict]:
    """Emerging patterns in the window before `now`, most people first. `reviews`: pattern_id ->
    {"status": "named" | "dismissed", ...} from analysts; dismissed patterns are left out."""
    reviews = reviews or {}
    since = (now - timedelta(days=T["window_days"])).isoformat()
    groups: dict[str, dict] = {}
    for p in store.transactions(since=since, until=now.isoformat(), limit=1000):
        if p["playbook"] or p["fail_open"]:
            continue  # a known scam type, or no decision to learn from
        d = store.details(p["payment_id"]) or {}
        lit = d.get("lit_families") or []
        if p["tier"] == "T0" and len(lit) < T["near_miss_families"]:
            continue  # nothing suspicious about it
        sig = signature(p, d.get("features") or {}, lit)
        pid = pattern_id(sig)
        g = groups.setdefault(pid, {"pattern_id": pid, "signature": sig, "payments": [], "users": set(),
                                    "payees": set(), "tiers": defaultdict(int)})
        g["payments"].append(p)
        g["users"].add(p["user_hash"])
        g["payees"].add(p["payee_upi"])
        g["tiers"][p["tier"]] += 1

    half = now - timedelta(days=T["window_days"] / 2)
    out = []
    for pid, g in groups.items():
        if len(g["payments"]) < T["min_payments"] or len(g["users"]) < T["min_users"]:
            continue
        if reviews.get(pid, {}).get("status") == "dismissed":
            continue
        ts = sorted(datetime.fromisoformat(p["ts"]) for p in g["payments"])
        recent = sum(t >= half for t in ts)
        growing = recent >= len(ts) - recent
        out.append({
            "pattern_id": pid,
            "description": describe(g["signature"]),
            "signature": g["signature"],
            "payments": len(g["payments"]), "people": len(g["users"]), "payees": len(g["payees"]),
            "money_inr": round(sum(p["amount_inr"] for p in g["payments"]), 2),
            "tiers": dict(g["tiers"]),
            "first_seen": ts[0].isoformat(), "last_seen": ts[-1].isoformat(),
            "growing": growing,
            "examples": [p["payment_id"] for p in sorted(g["payments"], key=lambda p: p["ts"])[-5:]],
            "review": reviews.get(pid),
            "summary": (f"{len(g['payments'])} payments from {len(g['users'])} people since "
                        f"{ts[0]:%d %b}: {describe(g['signature'])}. Matches no known scam type."),
        })
    return sorted(out, key=lambda x: (-x["people"], -x["payments"]))


def draft_playbook(pattern: dict, name: str) -> str:
    """A draft for the data folder's playbook files, for the data owner to finish and add."""
    sig = pattern["signature"]
    doc = {
        "name": name,
        "title": pattern["description"],
        "confidence": "guess",
        "sources": [f"RUKO emerging pattern {pattern['pattern_id']}: {pattern['people']} people, "
                    f"{pattern['payments']} payments, first seen {pattern['first_seen'][:10]}"],
        "signals": {k: v for k, v in sig.items() if v not in (None, [], False)},
    }
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
