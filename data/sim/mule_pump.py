"""Pump a mule live before the demo: many strangers pay it small amounts, it forwards most out.

    PYTHONPATH=backend:ml:data python -m sim.mule_pump --vpa secure.settlement.desk@okaxis --payers 40

Payments go through the mock NPCI (/npci/pay), so the bank features (fan-in in 6 h,
pass-through) light up in real time while the lists still know nothing about this mule.
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--url", default="http://127.0.0.1:8001")
    p.add_argument("--data", type=Path, default=Path("data"))
    p.add_argument("--vpa", default="secure.settlement.desk@okaxis")
    p.add_argument("--payers", type=int, default=40)
    p.add_argument("--minutes", type=float, default=120, help="spread the pump over this long")
    p.add_argument("--forward", type=float, default=0.9, help="share forwarded out")
    p.add_argument("--seed", type=int, default=11)
    a = p.parse_args()

    rng = random.Random(a.seed)
    acc = pd.read_parquet(a.data / "accounts.parquet")
    payers = acc[(acc.holder_type == "person") & ~acc.is_mule].upi_id.tolist()
    cash_out = acc[acc.mule_kind == "cash_out"].upi_id.tolist()

    with httpx.Client(base_url=a.url, timeout=10) as c:
        now = datetime.fromisoformat(c.get("/sim/state").json()["now"])
        t = now - timedelta(minutes=a.minutes)
        total = 0.0
        for payer in rng.sample(payers, a.payers):
            t += timedelta(minutes=a.minutes / a.payers * rng.uniform(0.5, 1.0))
            amount = rng.randint(500, 4000)
            # Back-dated inside the last `minutes`; the clock never moves backwards.
            c.post("/npci/pay", json={"from_upi": payer, "to_upi": a.vpa, "amount": amount,
                                      "ts": t.isoformat()}).raise_for_status()
            total += amount
            if rng.random() < 0.3:  # forward in bursts, minutes after money lands
                out = total * a.forward
                c.post("/npci/pay", json={"from_upi": a.vpa, "to_upi": rng.choice(cash_out),
                                          "amount": round(out), "ts": (t + timedelta(minutes=2)).isoformat()})
                total -= out
        if total > 0:
            c.post("/npci/pay", json={"from_upi": a.vpa, "to_upi": rng.choice(cash_out),
                                      "amount": round(total * a.forward)})
        bank = c.get(f"/npci/resolve/{a.vpa}").json()["bank_code"]
        risk = c.get(f"/banks/{bank}/payee-risk/{a.vpa}").json()
    f = risk["features"]
    print(f"pumped {a.payers} payers into {a.vpa}: uniq_payers_6h={f['uniq_payers_6h']} "
          f"pass_through_24h={f['pass_through_24h']} repeat={f['repeat_payer_ratio_30d']} "
          f"mulehunter={risk['mulehunter']['score']}")


if __name__ == "__main__":
    main()
