"""ReplayGraphStore must answer exactly like GraphStore: the same edges and payments expire, and
paid_before() agrees, after any mix of payments, outcomes, bank flows and protected edges."""
import random
from datetime import datetime, timedelta, timezone

from dataset.graph import ReplayGraphStore
from graph.store import GraphStore

IST = timezone(timedelta(hours=5, minutes=30))
T0 = datetime(2026, 9, 1, tzinfo=IST)


def snapshot(g: GraphStore) -> tuple:
    return (sorted(g.edges), {k: sorted(v) for k, v in g.out.items() if v}, {k: sorted(v) for k, v in g.inn.items() if v},
            sorted(g.payments), {k: list(v) for k, v in g.payments_into.items() if v})


def test_same_answers_as_the_original():
    rng = random.Random(5)
    original, fast = GraphStore(), ReplayGraphStore()
    users = [f"u{i}" for i in range(30)]
    accounts = [f"acct{i}@ybl" for i in range(40)]
    now, ids = T0, []
    for step in range(4000):
        now += timedelta(hours=rng.uniform(0, 6))
        op = rng.random()
        if op < 0.55:
            # Mostly in order, sometimes a late-arriving older timestamp.
            ts = now - timedelta(days=rng.uniform(0, 40)) if rng.random() < 0.1 else now
            rid = f"r{step}"
            args = (rng.choice(users), rng.choice(accounts), rng.uniform(100, 5000), ts)
            original.add_payment(*args, request_id=rid)
            fast.add_payment(*args, request_id=rid)
            ids.append((rid, args))
        elif op < 0.75 and ids:
            # An outcome: usually for a checked payment, sometimes one the server never saw.
            rid, (user, payee, inr, _) = rng.choice(ids)
            if rng.random() < 0.1:
                rid, user, payee = f"x{step}", rng.choice(users), rng.choice(accounts)
            status = "completed" if rng.random() < 0.85 else "cancelled"
            assert original.record_outcome(rid, user, payee, inr, status, now) == \
                fast.record_outcome(rid, user, payee, inr, status, now)
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
        u, a = rng.choice(users), rng.choice(accounts)
        assert original.paid_before(u, a, now) == fast.paid_before(u, a, now), f"paid_before differs at {step}"
    assert len(original.edges) > 0 and len(original.payments) > 0
    assert any(original.paid_before(u, a, now) for u in users for a in accounts)
