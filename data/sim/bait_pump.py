"""Pump a task-scam bait account live before the demo (docs/task-scam-watcher.md §9.8).

    PYTHONPATH=backend:ml:data python -m sim.bait_pump --api http://127.0.0.1:8000 --users 40

One bait account sends Rs 150 "rewards" to 40 RUKO users. Their phones report it through
POST /v1/episode, so the payment graph sees one sender fanning out to many people. A few of them go
on to pay the demo mule (escalating), and the demo mule forwards to the very account that sent the
rewards: a money loop. Neither MuleHunter nor the I4C registry knows the bait account yet.

Then `--check` sends the demo user's own episode and a payment to the demo mule and prints what RUKO
says: expect T2 or T3 with R10_bait_then_pay and R11_ring_link. Run sim.mule_pump first.
"""
from __future__ import annotations

import argparse
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd

from .accounts import DEMO_MEENA, DEMO_MULE_UPI

RULES_VERSION = "episode-0.2"


def summary(state: str, bait: int, outs: list[float]) -> dict:
    steps = 0
    for i in range(len(outs) - 1, 0, -1):
        if outs[i] >= 1.5 * outs[i - 1]:
            steps += 1
        else:
            break
    return {"state": state, "age_days": 1.0, "bait_credits": bait, "bait_inr": 150.0 * bait, "outs": len(outs),
            "outs_inr": float(sum(outs)), "new_payees": len(outs), "escalation_steps": steps,
            "last_out_inr": outs[-1] if outs else None,
            "out_to_in_ratio": round(sum(outs) / (150.0 * bait), 2) if bait else None,
            "payee_seen_in_episode": None, "rules_version": RULES_VERSION}


def event(user: str, trigger: str, state: str, accounts: list[dict], outs: list[float], now: datetime) -> dict:
    return {"event_id": str(uuid.uuid4()), "episode_id": f"ep_{user}", "user_id": user, "ts": now.isoformat(),
            "trigger": trigger, "rules_version": RULES_VERSION, "summary": summary(state, 1, outs),
            "accounts": accounts}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default="http://127.0.0.1:8000", help="the RUKO engine")
    p.add_argument("--intel", default="http://127.0.0.1:8001", help="the mock world")
    p.add_argument("--data", type=Path, default=Path("data"))
    p.add_argument("--users", type=int, default=40)
    p.add_argument("--payers", type=int, default=5, help="how many of them go on to pay the demo mule")
    p.add_argument("--seed", type=int, default=13)
    p.add_argument("--check", action="store_true", help="then send the demo user's episode and payment")
    a = p.parse_args()
    rng = random.Random(a.seed)
    users = pd.read_parquet(a.data / "users.parquet")
    victims = users[users.user_id != DEMO_MEENA].sample(a.users, random_state=a.seed)

    with httpx.Client(base_url=a.intel, timeout=15) as world, httpx.Client(base_url=a.api, timeout=30) as api:
        now = datetime.fromisoformat(world.get("/sim/state").json()["now"])
        # The ring: the demo mule forwards to a cash-out account, and that same account sends the rewards.
        bank = world.get(f"/npci/resolve/{DEMO_MULE_UPI}").json()["bank_code"]
        world.post("/sim/settings", json={"visibility": "dpip"})  # the loop needs the banks' flows
        flows = world.get(f"/banks/{bank}/payee-flows/{DEMO_MULE_UPI}")
        if flows.status_code != 200 or not flows.json()["outbound"]:
            raise SystemExit("the demo mule has no outbound flows; run `python -m sim.mule_pump` first")
        sender = flows.json()["outbound"][0]["upi_id"]

        for i, v in enumerate(victims.itertuples()):
            t = now - timedelta(hours=rng.uniform(2, 48))
            world.post("/npci/pay", json={"from_upi": sender, "to_upi": v.upi_id, "amount": 150, "ts": t.isoformat()})
            bait = [{"upi_id": sender, "role": "bait_sender", "n": 1, "inr": 150,
                     "first_seen_min_ago": round((now - t).total_seconds() / 60, 1)}]
            api.post("/v1/episode", json=event(v.user_id, "watching", "watching", bait, [], now)).raise_for_status()
            if i < a.payers:  # escalates and pays the demo mule
                outs = [1000.0, 2500.0, 6000.0]
                acc = bait + [{"upi_id": DEMO_MULE_UPI, "role": "payee", "n": 3, "inr": sum(outs),
                               "first_seen_min_ago": 60, "via": "other_app", "step": 1}]
                api.post("/v1/episode", json=event(v.user_id, "active", "active", acc, outs, now)).raise_for_status()

        sig = api.get(f"/v1/graph/account/{sender}").json()["signals"]
        print(f"bait account {sender} sent Rs 150 to {a.users} RUKO users: "
              f"fan-out {sig['bait_sender_fanout_7d']}, crowd {sig['crowd']}")

        if a.check:
            outs = [1000.0, 2500.0, 6000.0]
            mine = [{"upi_id": sender, "role": "bait_sender", "n": 1, "inr": 150, "first_seen_min_ago": 600},
                    {"upi_id": DEMO_MULE_UPI, "role": "payee", "n": 1, "inr": 6000, "first_seen_min_ago": 30,
                     "via": "this_app", "step": 3}]
            ep = api.post("/v1/episode", json={**event(DEMO_MEENA, "active", "active", mine, outs, now)}).json()
            print(f"demo user's episode: risk {ep['episode_risk']}, reasons {ep['reasons']}")
            body = {"request_id": str(uuid.uuid4()), "user_id": DEMO_MEENA, "payee_upi_id": DEMO_MULE_UPI,
                    "amount_inr": 14_000, "entry_method": "typed", "payer_says": "company", "ts": now.isoformat(),
                    "context": {"call": None, "device": None, "lures": [], "episode": summary("active", 1, outs)}}
            r = api.post("/v1/decide", json=body).json()
            print(f"demo payment of Rs 14,000 to {DEMO_MULE_UPI}: {r['tier']} {r['reasons']} ({r['message_key']})")
            mule = api.get(f"/v1/graph/account/{DEMO_MULE_UPI}").json()["signals"]
            print(f"money loop: {mule['money_loop']}  {mule['loop_path'] or ''}")
            print(f"console: {a.api}/console/graph")


if __name__ == "__main__":
    main()
