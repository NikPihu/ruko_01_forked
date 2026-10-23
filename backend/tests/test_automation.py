"""A2: bot-scale fingerprints. Scripts and AI chatbots move money at machine scale."""
from datetime import datetime, timedelta, timezone

from graph.store import GraphStore, user_node

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=IST)


def pay(g, user, payee, inr, ts):
    g.add_payment(user, payee, inr, ts)


def test_script_paying_same_amount_at_steady_rhythm_is_automated():
    g = GraphStore()
    for i in range(12):  # 12 people, Rs 1,500 each, one every 4 minutes
        pay(g, f"victim{i}", "bot.mule@ybl", 1500, NOW - timedelta(minutes=4 * (12 - i)))
    a = g.automation("bot.mule@ybl", NOW)
    assert a["automated"] is True and a["side"] == "receives" and a["users"] == 12
    assert "every 4 min" in a["why"] and g.account_signals("bot.mule@ybl", NOW)["automated"] is True


def test_bait_sender_with_identical_rewards_is_automated():
    g = GraphStore()
    for i in range(10):
        u = user_node(f"user{i}")
        g._edge("task.rewards@ybl", u, 150, NOW - timedelta(minutes=6 * (10 - i)), "episode")
    assert g.automation("task.rewards@ybl", NOW)["side"] == "sends"
    assert g.automation("task.rewards@ybl", NOW)["automated"] is True


def test_shop_with_varied_amounts_is_not_automated():
    g = GraphStore()
    for i, amt in enumerate([80, 450, 120, 2300, 60, 900, 310, 45, 1500, 220]):
        pay(g, f"buyer{i}", "kirana@okaxis", amt, NOW - timedelta(minutes=4 * (10 - i)))
    assert g.automation("kirana@okaxis", NOW)["automated"] is False


def test_same_amount_but_human_timing_is_not_automated():
    """A school collecting the same fee from parents, at irregular times, is not a bot."""
    g = GraphStore()
    gaps = [3, 50, 7, 180, 12, 95, 2, 240, 30]
    t = NOW - timedelta(minutes=sum(gaps) + 5)
    for i in range(10):
        pay(g, f"parent{i}", "school.fees@sbi", 2000, t)
        if i < len(gaps):
            t += timedelta(minutes=gaps[i])
    assert g.automation("school.fees@sbi", NOW)["automated"] is False


def test_too_few_people_is_unknown():
    g = GraphStore()
    for i in range(3):
        pay(g, f"p{i}", "small@ybl", 500, NOW - timedelta(minutes=5 * i))
    assert g.automation("small@ybl", NOW)["automated"] is None


def test_automated_payee_adds_payee_evidence_only():
    from api.rule_scorer import _signals
    from features.build import FAMILY
    assert FAMILY["payee_automated"] == "P"
    f = {k: None for k in FAMILY} | {"payee_automated": True, "attempts_72h": 0, "amount_inr": 500.0,
                                      "first_time_payee": False, "entry_typed": False}
    sig = _signals(f)
    assert (0.7, "R11_ring_link") in sig["P"] and not sig["C"] and not sig["L"]
