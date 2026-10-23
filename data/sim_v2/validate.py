"""Checks a world (python -m sim_v2 validate --data DIR). Each check prints PASS / FAIL and why."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

CONTRACT = ["handles", "accounts", "users", "ledger", "context_events", "journeys", "reports"]
FLOWS = {"normal", "scam", "scam_bait", "scam_external", "mule_forward", "mule_cover", "cashback", "gig_payout"}
EVENTS = {"call_started", "call_ended", "sms_lure", "notification_lure", "app_installed", "remote_session_notice",
          "accessibility_enabled", "pay_session"}


def _check(results: list, name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  -> ' + detail) if detail else ''}")


def schema(results: list, d: Path) -> None:
    """Every column data/sim writes must exist here, in the same order, with the same type."""
    from sim.config import SimConfig
    from sim.generate import build_world
    ref = build_world(SimConfig(seed=1, n_users=300, n_days=10, scam_rate=0.05))
    for name in CONTRACT:
        mine = pd.read_parquet(d / f"{name}.parquet")
        want = list(ref[name].columns)
        have = list(mine.columns[: len(want)])
        bad = [c for c in want if c in mine and str(ref[name][c].dtype) != str(mine[c].dtype)
               and not (ref[name][c].isna().all() or mine[c].isna().all())]
        _check(results, f"schema {name}: data/sim columns first, same order and types", have == want and not bad,
               "" if have == want and not bad else f"want {want} have {have} type diffs {bad}")


def content(results: list, d: Path) -> None:
    led, ev, acc, users, jr, rep = (pd.read_parquet(d / f"{n}.parquet") for n in
                                    ("ledger", "context_events", "accounts", "users", "journeys", "reports"))
    _check(results, "ledger sorted by time", led.ts.is_monotonic_increasing)
    _check(results, "upi ids unique and lowercase", acc.upi_id.is_unique and (acc.upi_id == acc.upi_id.str.lower()).all())
    known = set(acc.upi_id)
    missing = (~led.from_upi.isin(known) | ~led.to_upi.isin(known)).sum()
    _check(results, "every ledger UPI id is an account", missing == 0, f"{missing} rows")
    _check(results, "flow vocabulary", set(led.flow) <= FLOWS, str(set(led.flow) - FLOWS))
    _check(results, "event vocabulary", set(ev.event_type) <= EVENTS, str(set(ev.event_type) - EVENTS))
    s = led[led.flow == "scam"]
    _check(results, "scam rows: labelled, stage S4/S5, journey set",
           bool(s.label_is_scam.all() and s.label_stage.isin(["S4", "S5"]).all() and s.journey_id.notna().all()))
    _check(results, "normal rows never labelled scam", not led[led.flow == "normal"].label_is_scam.any())
    _check(results, "scam payments under the P2P cap", bool((s.amount <= 100_000).all()))
    user_upi = set(users.upi_id)
    sess = (ev.event_type == "pay_session").sum()
    _check(results, "one pay_session per user payment", sess == led.from_upi.isin(user_upi).sum(),
           f"{sess} sessions vs {led.from_upi.isin(user_upi).sum()} payments")
    _check(results, "listed_at after filed_at", bool((rep.listed_at > rep.filed_at).all()))
    _check(results, "false reports never hit mules",
           not rep[rep.is_false].identifier.isin(set(acc.upi_id[acc.is_mule])).any())
    demo = {"u_demo_meena": users.user_id.eq("u_demo_meena").any(),
            "shreeganesh.kirana@okaxis": "shreeganesh.kirana@okaxis" in known,
            "secure.settlement.desk@okaxis": "secure.settlement.desk@okaxis" in known}
    _check(results, "demo actors present", all(demo.values()), str(demo))
    meena = users.loc[users.user_id == "u_demo_meena", "user_id"]
    _check(results, "Meena is never a victim", not jr.user_id.isin(meena).any())
    honest_new = (acc[~acc.is_mule].created_at > acc.created_at.max() - pd.Timedelta(days=90)).mean()
    mule_old = (acc[acc.is_mule].created_at < acc.created_at.max() - pd.Timedelta(days=365)).mean()
    share = acc.is_mule.mean()
    if len(users) >= 1000:   # crews serve groups of 1,000 users, so smaller worlds carry a whole crew's mules
        _check(results, "mule accounts are about 2% of accounts (1.5% to 3%)", 0.015 <= share <= 0.03, f"{share:.2%}")
    else:
        print(f"  INFO  mule share {share:.2%} (checked only from 1,000 users: crews are sized for 1,000-user groups)")
    _check(results, "account age is not a giveaway (some honest accounts new, some mules old)",
           honest_new > 0.02 and mule_old > 0.1, f"honest < 90 d: {honest_new:.0%}, mules > 1 y: {mule_old:.0%}")


def _hash(tables: dict) -> str:
    h = hashlib.sha256()
    for name in sorted(tables):
        h.update(pd.util.hash_pandas_object(tables[name].astype(str), index=False).values.tobytes())
    return h.hexdigest()[:16]


def determinism(results: list) -> None:
    from sim_v2.core.config import load
    from sim_v2.run import build
    quiet = lambda *_: None
    a = build(load(users=200, days=7), log=quiet)
    b = build(load(users=200, days=7), log=quiet)
    _check(results, "same seed -> identical world", _hash(a) == _hash(b))
    c = build(load(users=200, days=7, seed=8), log=quiet)
    _check(results, "different seed -> a different variation", _hash(a) != _hash(c))
    big = build(load(users=600, days=7), log=quiet)
    small_users = set(a["users"].upi_id)
    cols = ["ts", "from_upi", "to_upi", "amount", "entry_method", "flow", "scenario"]
    pick = lambda t: (t["ledger"][t["ledger"].from_upi.isin(small_users) & t["ledger"].flow.eq("normal")][cols]
                      .sort_values(cols).reset_index(drop=True))
    same = pick(a).equals(pick(big))
    _check(results, "subset stability: 200-user world = the same 200 people inside a 600-user world", same)
    cols = ["user_id", "playbook", "started_at", "n_payments", "total_paid", "outcome"]
    ja = a["journeys"].set_index("journey_id")[cols]
    jb = big["journeys"].set_index("journey_id").reindex(ja.index)[cols]
    _check(results, "subset stability: the same scam journeys start for those people", ja.equals(jb))


def run(d: Path) -> bool:
    results: list = []
    print(f"validate {d}")
    print("schema (vs data/sim):")
    schema(results, d)
    print("content:")
    content(results, d)
    print("determinism (builds small worlds, about 20 s):")
    determinism(results)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return all(results)
