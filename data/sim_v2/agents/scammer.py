"""Scam crews and their mules.

A crew runs one playbook for a group of localities (1,000 users by default). It owns phone numbers,
two long-lived cash-out accounts and a few *mule slots*. Each slot holds one mule at a time; a mule
works for a few days (assumptions: crews.mule_lifetime_days) and is then dropped for a new one, so
most scam money reaches accounts that no list knows yet (ml/PLAN.md §12).

Mules also receive money from victims outside our users (fan-in), and forward most of every inflow
to the crew's cash-out accounts after a hold.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sim_v2 import rails
from sim_v2.core.rng import draw
from sim_v2.world import World


@dataclass
class Crew:
    crew_id: str
    playbook: str
    group: int
    region: str
    numbers: list = field(default_factory=list)      # (number, is_foreign)
    cash_out: list = field(default_factory=list)
    slots: list = field(default_factory=list)        # per slot: [(active_from, active_to, upi, kind)]

    def mule(self, slot: int, ts: datetime) -> str:
        sched = self.slots[slot % len(self.slots)]
        for a, b, upi, _ in sched:
            if a <= ts < b:
                return upi
        return min(sched, key=lambda m: abs((m[0] - ts).total_seconds()))[2]


def mule_account(w: World, key: tuple, kind: str, active_from: datetime, region: str) -> str:
    r = w.r("mule", *key)
    lo, hi = w.cfg.get("crews.mule_age_days")[kind]
    created = active_from - timedelta(days=r.uniform(lo, hi))
    age_days = (w.start - created).total_seconds() / 86400
    if kind == "merchant_disguised":
        acct = w.merchant(("mule",) + key, "kirana", "5411", region, False, age_days=age_days)
    else:
        acct = w.person(("mule",) + key, region, age_days=age_days)
    acct["created_at"] = acct["kyc_at"] = created
    acct["is_mule"], acct["mule_kind"] = True, kind
    return acct["upi_id"]


def setup_crews(w: World) -> None:
    cfg = w.cfg
    n_groups = math.ceil(len(w.localities) / cfg.localities_per_crew)
    for g in range(n_groups):
        region = w.localities[g * cfg.localities_per_crew]["region"]
        for pb_name, pb in cfg.playbooks.items():
            cid = f"crew_{pb_name}_{g}"
            r = w.r("crew", cid)
            crew = Crew(cid, pb_name, g, region)
            for k in range(3):
                foreign = r.chance(cfg.get("crews.numbers")["foreign_voip"])
                crew.numbers.append((rails.number(w, r, foreign), foreign))
            crew.cash_out = [mule_account(w, (cid, "cashout", k), "cash_out", w.start - timedelta(days=5), region)
                             for k in range(2)]
            kinds = pb.get("mule_kinds") or cfg.get("crews.mule_kinds")
            for s in range(pb.get("mules", {}).get("slots", cfg.get("crews.mule_slots"))):
                sched, t, n = [], w.start - timedelta(days=r.uniform(8, 15)), 0
                while t < w.end:
                    life = timedelta(days=draw(r, cfg.get("crews.mule_lifetime_days")))
                    kind = r.weighted(kinds)
                    upi = mule_account(w, (cid, s, n), kind, t, region)
                    sched.append((t, t + life, upi, kind))
                    t, n = t + life, n + 1
                crew.slots.append(sched)
            w.crews[cid] = crew
    demo_mule(w)


def demo_mule(w: World) -> None:
    """The scripted fresh mule (CLAUDE.md demo identities): 4 days old, many outside payers, forwards out."""
    d = w.cfg.demo["demo_mule"]
    created = w.end - timedelta(days=d["created_days_before_end"])
    r = w.r("demo_mule")
    w.add_account(d["upi_id"], holder_name="Secure Settlement Desk", holder_type="person", created_at=created,
                  region="Pune", mobile=w.mobile(r), is_mule=True, mule_kind=d["kind"])
    cash = mule_account(w, ("demo_mule", "cashout"), "cash_out", created, "Pune")
    w.demo_cash_out = cash
    t = created + timedelta(hours=2)
    k = 0
    while t < w.end:
        t += timedelta(hours=r.g.exponential(24 / d["external_payers_per_day"]))
        payer = w.person(("demo_ext", k), "Pune")["upi_id"]
        amount = round(r.loguniform(3000, 40000), -2)
        if rails.pay(w, t, payer, d["upi_id"], amount, "typed", "scam_external", is_scam=True):
            w.mule_inflows.append((t, d["upi_id"], amount, f"demo_ext:{k}", None, cash, "plain"))
        k += 1


def external_victims(w: World) -> None:
    """Victims outside our users pay each mule while it is active; merchant-disguised mules also get cover."""
    cfg = w.cfg
    for crew in w.crews.values():
        for s, sched in enumerate(crew.slots):
            for n, (a, b, upi, kind) in enumerate(sched):
                if kind == "cash_out":
                    continue
                r = w.r("external", crew.crew_id, s, n)
                rate = r.uniform(*cfg.get("crews.external_victims_per_day"))
                t, k = a, 0
                while True:
                    t += timedelta(days=r.g.exponential(1 / rate))
                    if t >= b:
                        break
                    payer = w.person(("ext", crew.crew_id, s, n, k), crew.region)["upi_id"]
                    amount = r.loguniform(*cfg.get("crews.external_amount")["log"])
                    amount = round(amount, -2) if r.chance(0.5) else round(amount)
                    if rails.pay(w, t, payer, upi, amount, r.weighted({"typed": 0.8, "qr": 0.2}), "scam_external", is_scam=True):
                        w.mule_inflows.append((t, upi, amount, f"ext:{crew.crew_id}:{s}:{n}:{k}", None,
                                               r.choice(crew.cash_out), kind))
                        w.external_reports.append((t, upi, crew))
                    k += 1
                if kind == "merchant_disguised":
                    days = (b - a).total_seconds() / 86400
                    for c in range(r.poisson(r.uniform(*cfg.get("crews.cover_payments_per_day")) * days)):
                        ts = a + timedelta(days=r.uniform(0, days))
                        payer = w.person(("cover", crew.crew_id, s, n, c), crew.region)["upi_id"]
                        rails.pay(w, ts, payer, upi, round(r.loguniform(20, 400)), "qr", "mule_cover")


def forward_all(w: World) -> None:
    """Every mule inflow is forwarded (most of it) to a cash-out account after a hold."""
    cfg = w.cfg
    holds = cfg.get("crews.hold_minutes")
    for ts, mule, amount, key, journey_id, cash_out, kind in w.mule_inflows:
        r = w.r("forward", key)
        if not r.chance(0.9):
            continue   # some money sits (frozen, or withdrawn by ATM card)
        hold = draw(r, holds["slow_forward" if kind == "slow_forward" else "plain"])
        rails.pay(w, ts + timedelta(minutes=hold), mule, cash_out, amount * r.uniform(*cfg.get("crews.pass_through")),
                  "typed", "mule_forward", journey_id=journey_id)
