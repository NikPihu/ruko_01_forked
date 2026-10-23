"""sim_v1: a compact synthetic UPI world, calibrated to NPCI numbers and real (Xente) behaviour.

    PYTHONPATH=backend:ml:data python -m sim_v1.generate --world train --out data/sim_v1_out/train

Tables: users, accounts, payments (every payment, with labels and phone context), journeys.
This is the fast first version: it does not yet write the 7-table format the backend reads.

What it fixes from data/sim (data/eval/realism/FINDINGS.md):
  1. account age leak: honest accounts include new ones, mules include aged / rented ones
  2. too few positives: a 'train' world with 5% victims and an 'eval' world at realistic prevalence
  3. scam-only context: every phone signal also fires on legit payments, and is None without consent
  4. obvious amounts: task / trading scams climb a ladder from small payments; legit big P2P exists
  5. uniform users: activity is log-normal across users; P2M share and tickets match NPCI
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from sim_v1.config import HANDLES, PERSONAS, PLAYBOOKS, P2P_TXN_CAP, XENTE_HOURS, V1Config, load

HOURS = np.array(XENTE_HOURS) / sum(XENTE_HOURS)
DAY_HOURS = HOURS * (np.arange(24) >= 8) * (np.arange(24) <= 21)  # scammers keep office hours
DAY_HOURS /= DAY_HOURS.sum()


def lognormal_mix(rng, n, bulk_med, bulk_sig, tail_med, tail_sig, tail_w):
    tail = rng.random(n) < tail_w
    out = np.where(tail, rng.lognormal(np.log(tail_med), tail_sig, n), rng.lognormal(np.log(bulk_med), bulk_sig, n))
    return np.maximum(1.0, np.round(out))


class World:
    def __init__(self, cfg: V1Config):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)
        self.accounts: list[dict] = []
        self.rows: list[dict] = []
        self.handles = list(HANDLES)
        self.handle_p = np.array([HANDLES[h][2] for h in self.handles])
        self.handle_p /= self.handle_p.sum()

    # ---------- accounts ----------
    def account(self, kind: str, age_days: float, **kw) -> str:
        h = self.handles[self.rng.choice(len(self.handles), p=self.handle_p)]
        upi = f"{kind[0]}{len(self.accounts):06d}@{h}"
        self.accounts.append({"upi_id": upi, "handle": h, "bank": HANDLES[h][0], "holder_type": kind,
                              "created_at": self.cfg.start - timedelta(days=float(age_days)),
                              "is_mule": False, "mule_kind": None, **kw})
        return upi

    def honest_age(self) -> float:
        if self.rng.random() < self.cfg.new_account_share:
            return self.rng.uniform(3, 90)
        return self.rng.uniform(90, 3650)

    def ts(self, day: float, hours=HOURS):
        h = self.rng.choice(24, p=hours)
        return self.cfg.start + timedelta(days=int(day), hours=int(h), seconds=float(self.rng.uniform(0, 3600)))

    def pay(self, ts, frm, to, amount, kind, entry, flow, user_id=None, ctx=None, journey=None,
            playbook=None, stage=None):
        if ts > self.cfg.end:
            return
        self.rows.append({"ts": ts, "from_upi": frm, "to_upi": to, "amount": float(amount), "kind": kind,
                          "entry_method": entry, "flow": flow, "user_id": user_id,
                          "journey_id": journey, "playbook": playbook, "label_is_scam": journey is not None and flow == "scam",
                          "label_stage": stage, **(ctx or {"ctx_on_call": None, "ctx_remote_app": None, "ctx_lure_72h": None})})

    def context(self, user, p_call, p_remote, p_lure):
        """Phone signals for one payment. None (unknown) when the user gave no consent (CLAUDE.md rule 1)."""
        if not user["consent"]:
            return {"ctx_on_call": None, "ctx_remote_app": None, "ctx_lure_72h": None}
        r = self.rng.random(3)
        return {"ctx_on_call": bool(r[0] < p_call), "ctx_remote_app": bool(r[1] < p_remote or user["remote_app"]),
                "ctx_lure_72h": bool(r[2] < p_lure)}

    # ---------- build ----------
    def build(self) -> dict[str, pd.DataFrame]:
        cfg, rng = self.cfg, self.rng
        names = list(PERSONAS)
        shares = np.array([PERSONAS[p][0] for p in names])
        n = cfg.n_users

        merchants = [self.account("merchant", self.honest_age()) for _ in range(max(40, n // 6))]
        people = [self.account("person", self.honest_age()) for _ in range(n * 2)]
        cash_out = [self.account("person", rng.uniform(30, 400)) for _ in range(max(4, n // 300))]

        users = []
        for i in range(n):
            p = names[rng.choice(len(names), p=shares / shares.sum())]
            _, med, p2m, mult = PERSONAS[p]
            users.append({"user_id": f"u_{i:06d}", "upi_id": self.account("person", self.honest_age()), "persona": p,
                          "rate": float(med * np.exp(rng.normal(0, cfg.activity_sigma))), "p2m": p2m, "mult": mult,
                          "consent": bool(rng.random() < cfg.consent_share),
                          # some people really use AnyDesk / TeamViewer (IT staff, helpers of seniors)
                          "remote_app": bool(rng.random() < cfg.legit_remote_app * 3),
                          "contacts": list(rng.choice(people, 3 + rng.poisson(8), replace=False)),
                          "shops": list(rng.choice(merchants, 2 + rng.poisson(5), replace=False))})

        self.mules = self.make_mules(merchants)
        for u in users:
            self.normal_life(u, people, merchants)
        victims = rng.choice(n, int(round(n * cfg.victim_rate)), replace=False)
        journeys = [self.scam(users[i], j) for j, i in enumerate(victims)]
        self.mule_flows(cash_out)

        pay = pd.DataFrame(self.rows).sort_values("ts", kind="stable").reset_index(drop=True)
        pay.insert(0, "tx_id", [f"t_{i:07d}" for i in range(len(pay))])
        for c in ("ctx_on_call", "ctx_remote_app", "ctx_lure_72h"):
            pay[c] = pay[c].astype("boolean")
        acc = pd.DataFrame(self.accounts)
        mule_kind = {m["upi"]: m["kind"] for m in self.mules}
        acc["is_mule"] = acc.upi_id.isin(mule_kind)
        acc["mule_kind"] = acc.upi_id.map(mule_kind)
        u = pd.DataFrame(users).drop(columns=["contacts", "shops", "p2m", "mult"])
        return {"users": u, "accounts": acc, "payments": pay, "journeys": pd.DataFrame(journeys)}

    def normal_life(self, u, people, merchants):
        cfg, rng = self.cfg, self.rng
        k = rng.poisson(u["rate"] * cfg.n_days)
        days = rng.uniform(0, cfg.n_days, k)
        is_p2m = rng.random(k) < u["p2m"] + cfg.p2m_shift
        a_m = lognormal_mix(rng, k, cfg.p2m_bulk_median, cfg.p2m_bulk_sigma, cfg.p2m_tail_median,
                            cfg.p2m_tail_sigma, cfg.p2m_tail_weight)
        a_p = lognormal_mix(rng, k, cfg.p2p_bulk_median, cfg.p2p_bulk_sigma, cfg.p2p_tail_median,
                            cfg.p2p_tail_sigma, cfg.p2p_tail_weight)
        amount = np.minimum(np.where(is_p2m, a_m, a_p) * u["mult"], P2P_TXN_CAP)
        zipf = lambda m: (w := 1 / np.arange(1, m + 1)) / w.sum()
        for d, m, a in zip(days, is_p2m, amount):
            if m:
                to = (rng.choice(merchants) if rng.random() < cfg.new_merchant_p
                      else u["shops"][rng.choice(len(u["shops"]), p=zipf(len(u["shops"])))])
                entry = rng.choice(["qr", "typed", "contact"], p=[0.9, 0.06, 0.04])
            else:
                to = (rng.choice(people) if rng.random() < cfg.new_person_p
                      else u["contacts"][rng.choice(len(u["contacts"]), p=zipf(len(u["contacts"])))])
                entry = rng.choice(["contact", "typed", "qr"], p=[0.65, 0.25, 0.10])
            self.pay(self.ts(d), u["upi_id"], to, a, "P2M" if m else "P2P", entry, "normal", u["user_id"],
                     self.context(u, cfg.legit_on_call, cfg.legit_remote_app, cfg.legit_lure_72h))
        # hard negatives
        if rng.random() < cfg.rent_share:
            landlord = rng.choice(people)
            for month in range(0, cfg.n_days, 30):
                self.pay(self.ts(month + rng.uniform(0, 5)), u["upi_id"], landlord,
                         round(rng.lognormal(np.log(12000), 0.5), -2), "P2P", "typed" if month == 0 else "contact",
                         "rent", u["user_id"], self.context(u, cfg.legit_on_call, cfg.legit_remote_app, cfg.legit_lure_72h))
        for _ in range(rng.poisson(cfg.big_new_payee_rate * cfg.n_days / 30)):
            # deposit, tuition, contractor: large, new payee, often on a call to confirm the details
            self.pay(self.ts(rng.uniform(0, cfg.n_days)), u["upi_id"], rng.choice(people),
                     min(P2P_TXN_CAP, round(rng.lognormal(np.log(15000), 0.7), -2)), "P2P", "typed",
                     "big_new_payee", u["user_id"], self.context(u, 0.4, cfg.legit_remote_app, cfg.legit_lure_72h))

    def make_mules(self, merchants):
        cfg, rng = self.cfg, self.rng
        kinds, w = list(cfg.mule_kinds), np.array(list(cfg.mule_kinds.values()))
        mules = []
        for _ in range(max(8, cfg.n_users // 100)):
            kind = kinds[rng.choice(len(kinds), p=w / w.sum())]
            age = {"fresh": rng.uniform(5, 60), "aged_rented": rng.uniform(365, 2200),
                   "merchant_disguised": rng.uniform(30, 1100)}[kind]
            upi = self.account("merchant" if kind == "merchant_disguised" else "person", age)
            if kind == "merchant_disguised":
                merchants.append(upi)  # gets ordinary QR payments too (cover traffic)
            mules.append({"upi": upi, "kind": kind})
        return mules

    def scam(self, u, j):
        """One scam journey: a playbook-specific series of payments to 1-2 mules."""
        cfg, rng = self.cfg, self.rng
        pb = list(PLAYBOOKS)[rng.choice(len(PLAYBOOKS), p=np.array(list(PLAYBOOKS.values())) / sum(PLAYBOOKS.values()))]
        jid = f"j_{j:05d}"
        start = rng.uniform(0, cfg.n_days - 3)
        mules = [m["upi"] for m in rng.choice(self.mules, 1 + (rng.random() < 0.4), replace=False)]
        # (offset days, amount) per payment; ctx = (p_call, p_remote, p_lure); entry
        if pb == "digital_arrest":
            n = rng.integers(1, 5)
            plan = [(rng.uniform(0, 0.3), rng.lognormal(np.log(40000), 0.6)) for _ in range(n)]
            ctx, entry, kind = (0.85, 0.2, 0.3), "typed", "P2P"
        elif pb == "task_job":  # trust ladder: small paid tasks, then escalating "deposits"
            small = [(rng.uniform(0, 1.5), rng.uniform(100, 1000)) for _ in range(rng.integers(2, 5))]
            big, a = [], rng.uniform(1500, 4000)
            for k in range(rng.integers(1, 5)):
                big.append((rng.uniform(1.5, 6), a)); a *= rng.uniform(1.8, 3.5)
            plan, ctx, entry, kind = small + big, (0.1, 0.05, 0.7), rng.choice(["typed", "qr"]), "P2P"
        elif pb == "trading_group":
            a, plan = rng.uniform(3000, 10000), []
            for k in range(rng.integers(2, 7)):
                plan.append((rng.uniform(0, 20), a)); a *= rng.uniform(1.3, 2.5)
            ctx, entry, kind = (0.1, 0.05, 0.6), "typed", "P2P"
        elif pb == "fake_kyc_apk":
            plan = [(rng.uniform(0, 0.05), rng.lognormal(np.log(8000), 0.7)) for _ in range(rng.integers(1, 3))]
            ctx, entry, kind = (0.4, 0.7, 0.8), "typed", "P2P"
        elif pb == "refund_qr":
            plan = [(rng.uniform(0, 0.1), rng.uniform(500, 8000)) for _ in range(rng.integers(1, 3))]
            ctx, entry, kind = (0.6, 0.05, 0.3), "qr", "P2M"
        else:  # fake_customer_care
            plan = [(rng.uniform(0, 0.1), rng.lognormal(np.log(9000), 0.7)) for _ in range(rng.integers(1, 4))]
            ctx, entry, kind = (0.9, 0.5, 0.2), "typed", "P2P"
        plan.sort()
        paid = []
        for i, (off, amt) in enumerate(plan):
            ts = self.ts(start + off, DAY_HOURS)
            to = mules[i % len(mules)]
            amt = float(min(P2P_TXN_CAP, round(amt)))
            n0 = len(self.rows)
            self.pay(ts, u["upi_id"], to, amt, kind, entry, "scam", u["user_id"], self.context(u, *ctx),
                     jid, pb, "S4" if i == 0 else "S5")
            if len(self.rows) > n0:
                paid.append(amt)
        return {"journey_id": jid, "user_id": u["user_id"], "playbook": pb, "started_at": self.ts(start, DAY_HOURS),
                "mule_upi_ids": ",".join(mules), "n_payments": len(paid), "total_paid": float(sum(paid))}

    def mule_flows(self, cash_out):
        """Victims outside our users pay each mule; mules forward most of it to cash-out accounts."""
        cfg, rng = self.cfg, self.rng
        inflow = {}
        for m in self.mules:
            for _ in range(rng.poisson(cfg.mule_external_per_week * cfg.n_days / 7)):
                ts = self.ts(rng.uniform(0, cfg.n_days), DAY_HOURS)
                self.pay(ts, f"x{rng.integers(1e6):06d}@ybl", m["upi"], round(rng.lognormal(np.log(15000), 0.8)),
                         "P2P", "typed", "scam_external")
        mule_ids = {m["upi"] for m in self.mules}
        for r in list(self.rows):
            if r["to_upi"] in mule_ids and r["flow"] in ("scam", "scam_external"):
                inflow.setdefault(r["to_upi"], []).append(r)
        for mule, rows in inflow.items():
            for r in rows:
                if rng.random() < 0.9:
                    self.pay(r["ts"] + timedelta(hours=float(rng.exponential(6))), mule, rng.choice(cash_out),
                             round(r["amount"] * cfg.mule_pass_through), "P2P", "typed", "mule_forward")


def build(cfg: V1Config) -> dict[str, pd.DataFrame]:
    return World(cfg).build()


def write(tables: dict[str, pd.DataFrame], cfg: V1Config, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False)
    man = {"config": {**asdict(cfg), "end": cfg.end.isoformat()}, "rows": {k: len(v) for k, v in tables.items()}}
    (out / "manifest.json").write_text(json.dumps(man, indent=2, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", choices=["train", "eval"], default="train")
    ap.add_argument("--users", type=int, default=3000)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=Path("data/sim_v1_out"))
    a = ap.parse_args()
    cfg = load(world=a.world, n_users=a.users, n_days=a.days, seed=a.seed)
    t = build(cfg)
    write(t, cfg, a.out)
    p = t["payments"]
    print(f"{a.world}: {len(t['users'])} users, {len(p):,} payments, {len(t['journeys'])} journeys, "
          f"{int(p.label_is_scam.sum())} scam payments -> {a.out}")


if __name__ == "__main__":
    main()
