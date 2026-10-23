"""Demo agents: scripted people who use the real RUKO API, so a demo shows every scam type live.

    PYTHONPATH=backend;ml;data python -m demo.agents --api http://127.0.0.1:8000 --intel http://127.0.0.1:8001 --all

Each scenario is a person (a simulated RUKO user) doing what a victim, or an honest user, does:
phone early warnings (POST /v1/watch), task-scam episode events (POST /v1/episode), the payment
check (POST /v1/decide), what they did on the alert (POST /v1/feedback) and the outcome
(POST /v1/payment/outcome). The console and the transaction database fill up as it runs, and each
scenario prints what RUKO did against what should happen.

Agents only TEST the system; they never decide anything (rule 13). They read the simulated world
(data/*.parquet) to pick users and accounts, like sim.mule_pump does; the engine never does.

The hidden scenario ("relative emergency": a fake call that your son is in hospital, the UPI ID
pasted from a message) is a scam type with no playbook: it should appear on the console's
Emerging patterns page, and its mule, paid by many people the same amount in a burst, as bot-scale.
"""
from __future__ import annotations

import argparse
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol

import pandas as pd

DEMO_MULE = "secure.settlement.desk@okaxis"
KIRANA = "shreeganesh.kirana@okaxis"
UNKNOWN = "+919812345670"
RANK = {"T0": 0, "T1": 1, "T2": 2, "T3": 3, "T4": 4}


class Client(Protocol):  # httpx.Client or starlette's TestClient
    def post(self, url: str, json: dict): ...
    def get(self, url: str): ...


@dataclass
class World:
    users: list[str]          # simulated RUKO user ids, honest ones first
    persons: list[str]        # ordinary person UPI IDs (to pump a mule with)
    fresh_mule: str           # a mule no demo user has paid yet (for the hidden scenario)
    cash_out: str | None


def load_world(data: Path) -> World:
    users = pd.read_parquet(data / "users.parquet")
    acc = pd.read_parquet(data / "accounts.parquet")
    persons = acc[(acc.holder_type == "person") & ~acc.is_mule].upi_id.tolist()
    mules = acc[acc.is_mule & (acc.mule_kind == "plain") & (acc.upi_id != DEMO_MULE)].upi_id.tolist()
    cash = acc[acc.mule_kind == "cash_out"].upi_id.tolist()
    ids = [u for u in users.user_id.tolist() if u != "u_demo_meena"]
    return World(users=ids, persons=persons, fresh_mule=mules[0], cash_out=cash[0] if cash else None)


def _ts(now: datetime, minutes: float = 0) -> str:
    return (now + timedelta(minutes=minutes)).isoformat()


def _decide(c: Client, user: str, payee: str, amount: float, context: dict | None, now: datetime,
            entry: str = "typed", says: str | None = None) -> dict:
    body = {"request_id": str(uuid.uuid4()), "user_id": user, "payee_upi_id": payee, "amount_inr": amount,
            "entry_method": entry, "ts": now.isoformat(), "context": context}
    if says:
        body["payer_says"] = says
    r = c.post("/v1/decide", json=body).json()
    r["_request"] = body
    return r


def _after(c: Client, r: dict, now: datetime, action: str | None, paid: bool) -> None:
    """What the person did next: an alert action (feedback) and the outcome."""
    req = r["_request"]
    if action and r.get("tier") not in (None, "T0"):
        c.post("/v1/feedback", json={"feedback_id": str(uuid.uuid4()), "request_id": req["request_id"],
                                     "user_id": req["user_id"], "action": action, "why": None,
                                     "dwell_ms": 12_000, "ts": _ts(now, 1)})
    c.post("/v1/payment/outcome", json={"request_id": req["request_id"], "user_id": req["user_id"],
                                        "payee_upi_id": req["payee_upi_id"], "amount_inr": req["amount_inr"],
                                        "status": "completed" if paid else "cancelled", "ts": _ts(now, 2)})


def _watch(c: Client, user: str, kind: str, now: datetime, **kw) -> None:
    c.post("/v1/watch", json={"event_id": str(uuid.uuid4()), "user_id": user, "kind": kind, "ts": now.isoformat(), **kw})


# ---------- the scenarios: (name, what should happen, runner) ----------

def digital_arrest(c, w, now, user):
    _watch(c, user, "lure_seen", now, lure_tag="arrest_threat", lure_conf=0.92, source="sms", ai_written=True)
    ctx = {"call": {"active": True, "kind": "voip", "caller_in_contacts": None, "started_min_ago": 38, "speaker_on": True},
           "device": {"remote_access_active": True, "remote_app_installed_min_ago": 20},
           "lures": [{"tag": "arrest_threat", "conf": 0.92, "min_ago": 50}]}
    r = _decide(c, user, DEMO_MULE, 95_000, ctx, now, says="government")
    _after(c, r, now, "waited", paid=False)
    return [r]


def deepfake_video(c, w, now, user):
    ctx = {"call": {"active": True, "kind": "voip", "caller_in_contacts": None, "started_min_ago": 25, "video": True},
           "lures": [], "session": {"amount_digits": 5, "amount_gap_vs_usual": 4.2, "payee_pasted": True,
                                    "pasted_within_s_of_return": 7.0, "app_switches": 3}}
    r = _decide(c, user, DEMO_MULE, 60_000, ctx, now)
    _after(c, r, now, "called_trusted", paid=False)
    return [r]


def fake_kyc(c, w, now, user):
    _watch(c, user, "lure_seen", now, lure_tag="kyc", lure_conf=0.88, source="notification", ai_written=True)
    _watch(c, user, "sideload", now)
    ctx = {"device": {"sideloaded_last_24h": True, "untrusted_accessibility": True},
           "lures": [{"tag": "kyc", "conf": 0.88, "min_ago": 30}]}
    r = _decide(c, user, DEMO_MULE, 25_000, ctx, now)
    _after(c, r, now, "cancelled_from_alert", paid=False)
    return [r]


def trading_group(c, w, now, user):
    ctx = {"lures": [{"tag": "trading_tip", "conf": 0.9, "min_ago": 600}]}
    r = _decide(c, user, DEMO_MULE, 40_000, ctx, now, says="investment")
    _after(c, r, now, "slid_to_pay", paid=True)
    return [r]


def task_job(c, w, now, user):
    ep = {"state": "active", "age_days": 3.0, "bait_credits": 3, "bait_inr": 450, "outs": 3, "outs_inr": 9_500,
          "new_payees": 3, "escalation_steps": 2, "last_out_inr": 6_000, "out_to_in_ratio": 21.1,
          "payee_seen_in_episode": False, "rules_version": "episode-0.2"}
    r = _decide(c, user, DEMO_MULE, 14_000, {"lures": [], "episode": ep}, now)
    _after(c, r, now, "waited", paid=False)
    return [r]


def refund_qr(c, w, now, user):
    ctx = {"call": {"active": True, "kind": "sim", "caller_number": UNKNOWN, "caller_in_contacts": False,
                    "started_min_ago": 8}, "lures": []}
    r = _decide(c, user, DEMO_MULE, 8_000, ctx, now, entry="qr")
    _after(c, r, now, "cancelled_from_alert", paid=False)
    return [r]


def fake_customer_care(c, w, now, user):
    ctx = {"call": {"active": True, "kind": "sim", "direction": "outgoing", "caller_in_contacts": False,
                    "started_min_ago": 22}, "device": {"remote_access_active": True}, "lures": []}
    r = _decide(c, user, DEMO_MULE, 15_000, ctx, now)
    _after(c, r, now, "called_1930", paid=False)
    return [r]


def honest_users(c, w, now, user):
    out = [_decide(c, user, KIRANA, 180, None, now, entry="qr")]
    family = {"call": {"active": True, "kind": "sim", "caller_in_contacts": True, "started_min_ago": 4}, "lures": []}
    out.append(_decide(c, user, w.persons[3], 2_000, family, now, entry="contact"))
    for r in out:
        _after(c, r, now, None, paid=True)
    return out


def relative_emergency(c, w, now, user, victims: int = 9):
    """Hidden scam type (no playbook): an unknown caller says a relative is in hospital; the UPI ID
    is pasted from a message. Many victims pay the same fresh mule the same amount in a burst."""
    ctx = {"call": {"active": True, "kind": "sim", "caller_number": "+919800011122", "caller_in_contacts": False,
                    "started_min_ago": 6}, "lures": [],
           "session": {"amount_digits": 5, "amount_gap_vs_usual": 1.1, "payee_pasted": True,
                       "pasted_within_s_of_return": 5.0, "app_switches": 1}}
    start = w.users.index(user)
    out = []
    for i, u in enumerate(w.users[start:start + victims]):
        r = _decide(c, u, w.fresh_mule, 25_000, ctx, now + timedelta(seconds=5 * i))
        _after(c, r, now, "slid_to_pay", paid=True)
        out.append(r)
    return out


@dataclass
class Scenario:
    name: str
    expect: str                      # in words
    min_tier: str                    # every decision at least this...
    max_tier: str                    # ...and at most this
    playbook: str | None             # expected playbook, "none" for no playbook, None for "any"
    run: Callable


SCENARIOS = [
    Scenario("digital_arrest", "pause (T3+), digital arrest", "T3", "T4", "digital_arrest", digital_arrest),
    Scenario("deepfake_video", "interrupt (T2+), digital arrest via video call", "T2", "T4", "digital_arrest", deepfake_video),
    Scenario("fake_kyc", "interrupt (T2+), fake KYC app", "T2", "T4", "fake_kyc_apk", fake_kyc),
    Scenario("trading_group", "interrupt (T2+), trading group", "T2", "T4", "trading_group", trading_group),
    Scenario("task_job", "interrupt (T2+), task scam", "T2", "T4", "task_job", task_job),
    Scenario("refund_qr", "interrupt (T2+), refund QR", "T2", "T4", "refund_qr", refund_qr),
    Scenario("fake_customer_care", "interrupt (T2+), fake customer care", "T2", "T4", "fake_customer_care", fake_customer_care),
    Scenario("honest_users", "no interruption (T0/T1)", "T0", "T1", None, honest_users),
    Scenario("relative_emergency", "flagged (T1+) with NO known playbook -> Emerging patterns; mule bot-scale",
             "T1", "T4", "none", relative_emergency),
]


def pump_mule(intel: Client, w: World, payee: str = DEMO_MULE, payers: int = 40) -> None:
    """Make the demo mule look like a mule at its bank (many strangers, money forwarded fast)."""
    for p in w.persons[:payers]:
        intel.post("/npci/pay", json={"from_upi": p, "to_upi": payee, "amount": 1500})
    if w.cash_out:
        intel.post("/npci/pay", json={"from_upi": payee, "to_upi": w.cash_out, "amount": 54_000})


def run(c: Client, w: World, now: datetime, names: list[str] | None = None) -> list[dict]:
    rows, next_user = [], 0
    for s in SCENARIOS:
        if names and s.name not in names:
            continue
        user = w.users[next_user]
        next_user += 12 if s.name == "relative_emergency" else 1
        answers = s.run(c, w, now, user)
        tiers = [a.get("tier", "ERR") for a in answers]
        books = [a.get("playbook") for a in answers]
        ok_tier = all(t in RANK and RANK[s.min_tier] <= RANK[t] <= RANK[s.max_tier] for t in tiers)
        ok_book = (s.playbook is None or (s.playbook == "none" and all(b is None for b in books))
                   or all(b == s.playbook for b in books))
        rows.append({"scenario": s.name, "expect": s.expect, "decisions": len(answers), "tiers": tiers,
                     "playbooks": sorted({b for b in books if b}), "ok": ok_tier and ok_book,
                     "reasons": answers[0].get("reasons", [])})
    return rows


def main() -> None:
    import httpx

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default="http://127.0.0.1:8000")
    p.add_argument("--intel", default="http://127.0.0.1:8001")
    p.add_argument("--data", type=Path, default=Path("data"))
    p.add_argument("--all", action="store_true", help="every scenario (default)")
    p.add_argument("--scenario", action="append", help="run only these (repeatable)")
    p.add_argument("--no-pump", action="store_true")
    a = p.parse_args()
    w = load_world(a.data)
    with httpx.Client(base_url=a.api, timeout=30) as c, httpx.Client(base_url=a.intel, timeout=30) as intel:
        now = datetime.fromisoformat(intel.get("/sim/state").json()["now"])
        if not a.no_pump:
            pump_mule(intel, w)
        rows = run(c, w, now, a.scenario)
    width = max(len(r["scenario"]) for r in rows)
    for r in rows:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['scenario']:<{width}}  {','.join(r['tiers']):<28} "
              f"{','.join(r['playbooks']) or '-':<20} expected: {r['expect']}")
    print(f"{sum(r['ok'] for r in rows)}/{len(rows)} scenarios as expected. Open the console: Transactions, "
          f"Emerging patterns, Scam rings.")


if __name__ == "__main__":
    main()
