"""policy strong_corroboration: three near-certain families pause the payment whatever p_scam says."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from api.policy import Policy

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone(timedelta(hours=5, minutes=30)))
# What lgbm-0.2+pg1 gave the Meena demo (call + remote access + arrest-threat SMS + ₹95,000): every
# family lit, three near certain, but p_scam only 0.662 (T2) because a strong lure lowers its combiner.
MEENA = {"C": 1.0, "L": 0.936, "P": 0.563, "B": 0.991}


def decide(families, p=0.662, amount=95_000, trusted=False, user="u1", policy=None):
    s = {"p_scam": p, "family_scores": families, "playbook": "digital_arrest", "playbook_families": None}
    f = {"amount_inr": amount, "trusted_payee": trusted, "payee_registry_listed": False, "caller_registry_listed": False,
         "payee_fri_level": None, "caller_fri_level": None}
    return (policy or Policy()).decide(s, f, "S4", False, user, NOW)


def test_three_near_certain_families_pause_a_low_scored_scam():
    d = decide(MEENA)
    assert d.tier == "T3" and "strong_corroboration" in d.applied
    assert d.message_key == "t3_digital_arrest" and d.pause_minutes == 30


def test_two_near_certain_families_are_not_enough():
    d = decide({"C": 1.0, "L": 0.89, "P": 0.6, "B": 0.99})
    assert d.tier == "T2" and "strong_corroboration" not in d.applied


def test_it_never_lowers_a_tier_and_caps_and_trust_still_apply():
    assert decide(MEENA, p=0.2).tier == "T3"               # the model's score does not matter
    assert decide(MEENA, amount=150).tier == "T1"          # small payments are never interrupted
    assert decide(MEENA, trusted=True).tier == "T0"        # "I know this person", no override held


def test_the_numbers_come_from_config():
    pol = Policy()
    pol.cfg["strong_corroboration"]["min_family_score"] = 0.995
    assert decide(MEENA, policy=pol).tier == "T2"
    del pol.cfg["strong_corroboration"]
    assert decide(MEENA, policy=pol).tier == "T2"          # an old policy file without the section
