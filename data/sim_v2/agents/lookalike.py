"""Honest situations that look like scams (config/lookalikes.yaml). Written as flow 'normal' (or
'gig_payout') with `scenario` = the look-alike's name, so they are never labelled scam."""
from __future__ import annotations

from datetime import timedelta

from sim_v2 import rails
from sim_v2.core.rng import draw
from sim_v2.world import World


def _payee(w: World, u: dict, to: str, key: tuple) -> str:
    loc, r = w.localities[u["locality"]], w.r("lookalike_payee", *key)
    if to == "new_person":
        return w.person(("lookalike", *key), u["region"])["upi_id"]
    if to == "new_shop":
        return r.choice(loc["shops"] + loc["kiranas"])
    return {"biller": lambda: r.choice(w.billers), "contact": lambda: r.choice(u["contacts"]),
            "collection": lambda: loc["collection"], "hospital": lambda: loc["hospital"][0]}[to]()


def lookalikes(w: World, u: dict) -> None:
    cfg, uid = w.cfg, u["user_id"]
    for name, spec in cfg.lookalikes.items():
        rate = spec["rate"].get(u["persona"], 0.0) if isinstance(spec["rate"], dict) else spec["rate"]
        r = w.r("lookalike", uid, name)
        for occ in range(r.poisson(rate * cfg.days / 30)):
            t = w.start + timedelta(days=r.uniform(0, cfg.days))
            t = t.replace(hour=int(r.choice(range(24), w.hour_p)), minute=r.integer(0, 59))
            tags = {"scenario": name}
            for e in spec.get("events", []):
                if e["type"] == "call":
                    kind = r.weighted(e["kind"])
                    known = e.get("in_contacts", False)
                    num = w.accounts[r.choice(u["contacts"])]["mobile"] if known else rails.number(w, r)
                    rails.call(w, t, uid, num, draw(r, e["minutes"]), in_contacts=known, kind=kind,
                               direction=e.get("direction", "incoming"), **tags)
                elif e["type"] == "remote_app":
                    rails.remote_app(w, r, t, uid, **tags)
                t += timedelta(minutes=r.uniform(0.5, 2))
            if "pay" in spec:
                p = spec["pay"]
                t += timedelta(minutes=draw(r, p.get("gap_min", 0)))
                for k in range(int(draw(r, p.get("repeat", 1)))):
                    to = _payee(w, u, p["to"], (uid, name, occ, k))
                    amount = draw(r, p["amount"])
                    n = int(draw(r, p.get("split", 1)))
                    for part in range(n):
                        a = amount / n
                        a = round(a, -2) if r.chance(p.get("round", 0.0)) else round(a)
                        if rails.pay(w, t, u["upi_id"], to, a, r.weighted(p["entry"]), "normal", **tags) and p["to"] == "collection":
                            w.collection_inflows.append((t, to, a, u["locality"]))
                        t += timedelta(minutes=r.uniform(1, 10))
            if "credit" in spec:
                c = spec["credit"]
                rails.pay(w, t, r.choice(w.platforms), u["upi_id"], round(draw(r, c["amount"])), "typed", c["flow"], **tags)


def collections_forward(w: World) -> None:
    """Community funds pay a vendor every Sunday: many payers in, money out (mule-like, but honest)."""
    by_week: dict = {}
    for t, acct, a, loc in w.collection_inflows:
        week = (t - w.start).days // 7
        by_week[(acct, loc, week)] = by_week.get((acct, loc, week), 0.0) + a
    for (acct, loc, week), total in sorted(by_week.items()):
        r = w.r("collection", acct, week)
        t = w.start + timedelta(days=week * 7 + 6, hours=r.uniform(10, 18))
        rails.pay(w, t, acct, w.localities[loc]["vendor"], round(total * r.uniform(0.6, 0.95)), "typed", "normal",
                  scenario="community_collection")
