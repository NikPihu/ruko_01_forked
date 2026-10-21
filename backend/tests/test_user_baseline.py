"""The user's "usual" is only what the bank knew before the payment being judged."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from features.user_baseline import Baselines
from sim.config import SimConfig
from sim.generate import build_world, write_world

IST = timezone(timedelta(hours=5, minutes=30))
T0 = datetime(2026, 11, 1, 10, 0, tzinfo=IST)


@pytest.fixture()
def small(tmp_path):
    pd.DataFrame({"user_id": ["u1"], "upi_id": ["meena@ybl"]}).to_parquet(tmp_path / "users.parquet")
    rows = [
        (T0 - timedelta(days=100), "meena@ybl", "old.landlord@ybl", 50_000),  # outside 90 days
        (T0, "meena@ybl", "kirana@ybl", 100),
        (T0 + timedelta(days=1), "meena@ybl", "kirana@ybl", 200),
        (T0 + timedelta(days=2), "meena@ybl", "mule@okaxis", 95_000),         # the payment judged below
        (T0 + timedelta(days=3), "meena@ybl", "friend@ybl", 300),              # after it
        (T0, "someone.else@ybl", "x@ybl", 1),                                  # not a RUKO user
    ]
    pd.DataFrame(rows, columns=["ts", "from_upi", "to_upi", "amount"]).to_parquet(tmp_path / "ledger.parquet")
    return Baselines.from_data(tmp_path)


def test_the_payment_being_judged_is_not_part_of_the_usual(small):
    b = small.get("u1", at=T0 + timedelta(days=2))
    assert b.max_90d == 200 and b.median_90d == 150
    assert "mule@okaxis" not in b.known_payees


def test_later_payments_never_count(small):
    assert "friend@ybl" not in small.get("u1", at=T0 + timedelta(days=2)).known_payees


def test_after_the_payment_it_is_history(small):
    b = small.get("u1", at=T0 + timedelta(days=2, minutes=1))
    assert b.max_90d == 95_000 and "mule@okaxis" in b.known_payees


def test_amounts_use_90_days_but_known_payees_go_back_further(small):
    b = small.get("u1", at=T0 + timedelta(hours=1))
    assert b.max_90d == 100                      # the Rs 50,000 rent was 100 days ago
    assert "old.landlord@ybl" in b.known_payees  # but she has paid that landlord before


def test_first_ever_payment_and_unknown_user_have_no_usual(small):
    assert small.get("u1", at=T0 - timedelta(days=200)).max_90d is None
    empty = small.get("nobody", at=T0)
    assert empty.max_90d is None and empty.known_payees == set()


def test_whole_history_when_no_time_is_given(small):
    assert small.get("u1").max_90d == 95_000


def test_simulated_scam_payments_are_judged_on_the_honest_past(tmp_path):
    cfg = SimConfig(seed=5, n_users=300, n_days=20, scam_rate=0.05)
    write_world(build_world(cfg), cfg, tmp_path)
    base = Baselines.from_data(tmp_path)
    users = pd.read_parquet(tmp_path / "users.parquet")
    led = pd.read_parquet(tmp_path / "ledger.parquet")
    led = led.merge(users[["user_id", "upi_id"]], left_on="from_upi", right_on="upi_id")
    scam = led[led.label_is_scam].sort_values("ts")
    assert len(scam) > 0
    checked = 0
    for jid, g in scam.groupby("journey_id"):
        first = g.iloc[0]
        b = base.get(first.user_id, at=first.ts.to_pydatetime())
        earlier = led[(led.user_id == first.user_id) & (led.ts < first.ts)]
        assert first.to_upi not in b.known_payees or first.to_upi in set(earlier.to_upi)
        assert b.max_90d == (earlier.amount.max() if len(earlier) else None)
        checked += 1
    assert checked >= 3
