"""How mule accounts behave on the ledger: grooming, cover traffic, and fast forwarding out."""
from __future__ import annotations

from datetime import timedelta

from .accounts import DEMO_MULE_UPI
from .config import P2P_TXN_CAP
from .world import World

# Minutes between a mule receiving money and forwarding it on.
FORWARD_DELAY_MIN = {
    "plain": (3, 30),
    "merchant_disguised": (10, 60),
    "warm_up": (5, 40),
    "slow_forward": (180, 720),
}
FORWARDED_FLOWS = {"scam", "scam_external", "mule_warmup"}


def build_mule_grooming(w: World) -> None:
    """Warm-up inflows and fake shop customers. Run before scams so they precede scam money."""
    cfg, rng = w.cfg, w.rng
    for m in w.mules:
        start = max(m["created_at"], cfg.start)
        if m["mule_kind"] == "warm_up":
            feeders = rng.sample(w.cash_out, k=min(len(w.cash_out), rng.randint(3, 5)))
            day = start
            while day < min(m["_active_from"], cfg.end):
                for _ in range(rng.randint(1, 3)):
                    w.pay(w.day_time(day), rng.choice(feeders)["upi_id"], m["upi_id"],
                          rng.randint(100, 1500), "typed", "mule_warmup")
                day += timedelta(days=1)
        elif m["mule_kind"] == "merchant_disguised":
            # Small real-looking customer payments to pass as a shop.
            day = start
            while day < cfg.end:
                for _ in range(rng.randint(3, 10)):
                    payer = rng.choice(w.users)["upi_id"]
                    w.pay(w.day_time(day), payer, m["upi_id"], rng.randint(50, 500), "qr", "mule_cover")
                day += timedelta(days=1)


def build_external_victims(w: World) -> None:
    """Victims outside our app paying the same mules -- the network-wide fan-in a real mule sees."""
    cfg, rng = w.cfg, w.rng
    for m in w.mules:
        lo, hi = cfg.external_victims_per_day
        # The demo mule is "hot": many strangers paying it in its first days.
        rate = 6.0 if m["upi_id"] == DEMO_MULE_UPI else rng.uniform(lo, hi)
        day = max(m["_active_from"], cfg.start)
        while day < cfg.end:
            n = int(rate) + (rng.random() < rate % 1)
            for _ in range(n):
                payer = rng.choice(w.external)["upi_id"]
                row = w.pay(day + w.uniform_td(0, 1440), payer, m["upi_id"],
                            min(w.lognormal_amount(15_000, 0.8, 1_000, 300_000), P2P_TXN_CAP),
                            "typed", "scam_external", is_scam=True)
                if row:
                    w.external_scam_rows.append(row)
            day += timedelta(days=1)


def build_mule_forwarding(w: World) -> None:
    """Every scam or grooming inflow into a first-layer mule is mostly forwarded to cash-out accounts."""
    rng = w.rng
    mule_kind = {m["upi_id"]: m["mule_kind"] for m in w.mules}
    inflows = [r for r in w.ledger if r["to_upi"] in mule_kind and r["flow"] in FORWARDED_FLOWS]
    for r in inflows:
        lo, hi = FORWARD_DELAY_MIN[mule_kind[r["to_upi"]]]
        ts = r["ts"] + w.uniform_td(lo, hi)
        total = r["amount"] * rng.uniform(0.8, 0.95)
        targets = rng.sample(w.cash_out, k=min(len(w.cash_out), rng.choice((1, 1, 2))))
        for i, t in enumerate(targets):
            share = total / len(targets)
            w.pay(ts + timedelta(minutes=i * rng.uniform(1, 5)), r["to_upi"], t["upi_id"],
                  round(share), "typed", "mule_forward", journey_id=r["journey_id"])
