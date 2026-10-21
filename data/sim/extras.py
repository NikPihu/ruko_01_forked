"""Task-scam watcher additions (docs/task-scam-watcher.md §7): hard negatives for the episode.

Everything here draws from `w.aux`, a separate random stream, so the core world (and the demo
identities, mules and journeys) stays exactly as it was before these additions.

Hard negatives, each one a pattern the episode watcher must not turn into an alert:
    cashback      small merchant credits to many users (the bank SMS says "cashback": ignored)
    repay         a friend paying back a small loan (sender was paid before: not bait)
    gig_payout    regular small payouts from one known platform (bait-like, but no escalating outs)
    travel        one day of payments to several new shops in another city (new payees, no bait)
"""
from __future__ import annotations

from datetime import timedelta

from .world import World

SMS_CONSENT_SHARE = 0.6     # users who allowed SMS checks (the watcher can see credits)
GIG_WORKER_SHARE = 0.05
TRAVELLER_SHARE = 0.02


def build_hard_negatives(w: World) -> None:
    cfg, rng = w.cfg, w.aux
    gig_payer = w.billers[-1]   # stands in for a gig platform's payout account (a verified merchant)
    cashback_payers = w.billers[:2] + w.pharmacies[:2]
    all_kirana = [(region, k) for region, ks in w.kirana_by_region.items() for k in ks]
    gig_workers = {u["user_id"] for u in w.users if rng.random() < GIG_WORKER_SHARE}
    travel_day = {u["user_id"]: rng.randrange(cfg.n_days) for u in w.users if rng.random() < TRAVELLER_SHARE}

    for d in range(cfg.n_days):
        day = cfg.start + timedelta(days=d)
        for u in w.users:
            me = u["upi_id"]
            if rng.random() < 0.10:
                w.pay(w.day_time(day), rng.choice(cashback_payers), me, rng.randint(5, 50), "qr", "cashback")
            if rng.random() < 0.02 and u["family"]:
                friend = rng.choice(u["family"])
                amount = rng.randint(200, 500)
                ts = w.day_time(day)
                w.pay(ts, me, friend, amount, "contact", "normal")
                w.pay(ts + timedelta(days=rng.uniform(1, 3)), friend, me, amount, "typed", "repay")
            if u["user_id"] in gig_workers and d % 7 == 0:
                w.pay(w.day_time(day), gig_payer, me, rng.randint(200, 500), "typed", "gig_payout")
            if travel_day.get(u["user_id"]) == d:
                away = [k for region, k in all_kirana if region != u["region"]] or [k for _, k in all_kirana]
                ts = w.day_time(day).replace(hour=9)
                for shop in rng.sample(away, min(len(away), rng.randint(4, 6))):
                    ts += timedelta(minutes=rng.uniform(30, 150))
                    w.pay(ts, me, shop, w.lognormal_amount(400 * u["scale"], 0.9, 50, 8000), "qr", "normal")
