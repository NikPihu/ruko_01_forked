"""ReplayGraphStore.expire must drop exactly the edges GraphStore.expire drops."""
import random
from datetime import datetime, timedelta, timezone

from dataset.graph import ReplayGraphStore
from graph.store import GraphStore

IST = timezone(timedelta(hours=5, minutes=30))
T0 = datetime(2026, 9, 1, tzinfo=IST)


def snapshot(g: GraphStore) -> tuple:
    return (sorted(g.edges), {k: sorted(v) for k, v in g.out.items() if v}, {k: sorted(v) for k, v in g.inn.items() if v})


def test_same_edges_expire_as_the_original():
    rng = random.Random(5)
    original, fast = GraphStore(), ReplayGraphStore()
    users = [f"u{i}" for i in range(30)]
    accounts = [f"acct{i}@ybl" for i in range(40)]
    now = T0
    for step in range(3000):
        now += timedelta(hours=rng.uniform(0, 6))
        op = rng.random()
        if op < 0.7:
            # Mostly in order, sometimes a late-arriving older timestamp.
            ts = now - timedelta(days=rng.uniform(0, 40)) if rng.random() < 0.1 else now
            args = (rng.choice(users), rng.choice(accounts), rng.uniform(100, 5000), ts)
            original.add_payment(*args)
            fast.add_payment(*args)
        elif op < 0.85:
            flows = {"as_of": (now - timedelta(days=rng.uniform(0, 35))).isoformat(),
                     "outbound": [{"upi_id": rng.choice(accounts), "n": 2, "inr": 900.0, "median_hold_min": 12.0}
                                  for _ in range(rng.randint(0, 3))]}
            acct = rng.choice(accounts)
            original.add_bank_flows(acct, flows)
            fast.add_bank_flows(acct, flows)
        elif op < 0.9:
            nodes = rng.sample(accounts, 3)
            original.protect(nodes)
            fast.protect(nodes)
        original.expire(now)
        fast.expire(now)
        assert snapshot(original) == snapshot(fast), f"diverged at step {step}"
    assert len(original.edges) > 0
