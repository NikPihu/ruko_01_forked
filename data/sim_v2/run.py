"""Build one world: population -> crews -> everyday life -> scams -> mules -> reports -> tables.

    tables = build(load(users=500, days=14))
"""
from __future__ import annotations

import math
import time
from datetime import timedelta

from sim_v2 import export
from sim_v2.agents import citizen, lists, lookalike, scammer
from sim_v2.core.config import Config
from sim_v2.playbook import Journey
from sim_v2.world import World

PACK_EVERY = 500   # users per batch before rows are packed into Arrow (keeps memory flat at 20k users)


def target(w: World, u: dict):
    """Is this user approached by a crew in the window? One keyed draw per user (stable across sizes)."""
    cfg = w.cfg
    if u["never_scammed"]:
        return None
    pbs = cfg.playbooks
    pref = {n: pb["weight"] * pb["targets"].get(u["persona"], 1.0) for n, pb in pbs.items()}
    personas = cfg.get("population.personas")
    mean = sum(p["share"] * sum(pb["weight"] * pb["targets"].get(k, 1.0) for pb in pbs.values())
               for k, p in personas.items())
    p_user = min(0.95, cfg.victim_rate * (cfg.days / 60) * sum(pref.values()) / mean)
    r = w.r("target", u["user_id"])
    if not r.chance(p_user):
        return None
    pb = r.weighted(pref)
    lo, hi = pbs[pb]["start_hours"]
    day = r.uniform(0, max(0.5, cfg.days - 1.5))
    start = (w.start + timedelta(days=day)).replace(hour=r.integer(lo, hi), minute=r.integer(0, 59), second=0)
    return pb, start


def build(cfg: Config, log=print) -> dict:
    t0 = time.perf_counter()
    w = World(cfg)
    w.build_population()
    scammer.setup_crews(w)
    log(f"  population: {len(w.users):,} users, {len(w.localities)} localities, {len(w.crews)} crews "
        f"({time.perf_counter() - t0:.1f}s)")
    for k, u in enumerate(w.users):
        citizen.routine(w, u)
        citizen.calls_and_phone(w, u)
        lookalike.lookalikes(w, u)
        if k % PACK_EVERY == PACK_EVERY - 1:
            w.ledger.pack(), w.events.pack()
    log(f"  everyday life + look-alikes ({time.perf_counter() - t0:.1f}s)")
    group_of = lambda u: u["locality"] // cfg.localities_per_crew
    for u in w.users:
        hit = target(w, u)
        if hit:
            pb, start = hit
            j = Journey(w, f"j_{u['user_id'][2:]}", u, pb, start, w.crews[f"crew_{pb}_{group_of(u)}"]).run()
            w.journeys.append(j)
    demo_journeys(w)
    log(f"  scams: {len(w.journeys)} journeys ({time.perf_counter() - t0:.1f}s)")
    scammer.external_victims(w)
    scammer.forward_all(w)
    lookalike.collections_forward(w)
    for j in w.journeys:
        lists.journey_reports(w, j)
    lists.other_reports(w)
    tables = export.assemble(w)
    log(f"  done in {time.perf_counter() - t0:.1f}s")
    return tables


def demo_journeys(w: World) -> None:
    """Three digital-arrest victims in locality 0 paid the demo mule in the last two days (scripted)."""
    d, cfg = w.cfg.demo["demo_journeys"], w.cfg
    taken = {j["user_id"] for j in w.journeys}
    # first 100 users of locality 0: present in every world of 100+ users, so the pick never shifts
    pool = [u for u in w.users[:101] if not u["never_scammed"] and u["user_id"] not in taken]
    pool.sort(key=lambda u: w.r("demo_pick", u["user_id"]).random())
    crew = w.crews[f"crew_{d['playbook']}_0"]
    for k, u in enumerate(pool[: d["count"]]):
        r = w.r("demo_journey", k)
        start = cfg.end - timedelta(hours=r.uniform(*d["hours_before_end"]))
        j = Journey(w, f"j_demo_{k}", u, d["playbook"], start, crew, is_demo=True,
                    forced_mule=cfg.demo["demo_mule"]["upi_id"]).run()
        w.journeys.append(j)
