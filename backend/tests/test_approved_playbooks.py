"""playbooks-0.2: a playbook two analysts approved (blue team) labels the payment and raises its tier."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import yaml

from api import playbooks
from api.playbooks import PlaybookError, approved, families, load_approved, parse
from api.policy import Policy

APPROVED = {"name": "society_maintenance_clone", "why": "dictated payment to a listed account",
            "match": {"session_dictated": True, "payee_registry_listed": True}, "approved_by": ["asha", "ravi"]}


def first(rules, f):
    return next((name for name, _, rule in rules if rule(f)), None)


def test_comparisons_and_request_fields():
    rules = parse({"playbooks": [{"name": "qr_small", "why": "x",
                                  "match": {"entry_method": "qr", "amount_inr": {"gte": 1000, "lt": 10000}}}]})
    assert first(rules, {"entry_method": "qr", "amount_inr": 4000}) == "qr_small"
    assert first(rules, {"entry_method": "qr", "amount_inr": 10000}) is None
    assert first(rules, {"entry_method": "typed", "amount_inr": 4000}) is None
    assert first(rules, {"entry_method": "qr", "amount_inr": None}) is None      # unknown is never in range (rule 1)
    assert first(rules, {"entry_method": "qr"}) is None


@pytest.mark.parametrize("entry, error", [
    ({"match": {"amount_inr": {"gte": "1000"}}}, "comparison map"),
    ({"match": {"amount_inr": {"about": 5}}}, "comparison map"),
    ({"match": {"amount_inr": {"gte": True}}}, "comparison map"),
    ({"match": {"on_call": True}, "approved_by": ["asha"]}, "2 different analysts"),
    ({"match": {"on_call": True}, "approved_by": ["Asha", "asha "]}, "2 different analysts"),
    ({"match": {"on_call": True}, "approved_by": "asha, ravi"}, "2 different analysts"),
])
def test_bad_02_entries_are_refused(entry, error):
    with pytest.raises(PlaybookError, match=error):
        parse({"playbooks": [{"name": "a", "why": "x", **entry}]})


def test_families_come_from_the_conditions_only():
    assert families(APPROVED["match"]) == {"B", "P"}
    assert families({"entry_method": "qr", "amount_inr": {"gte": 1}, "session_dictated": True}) == {"B"}
    assert families({"stage": "S3", "on_call": True}) == {"C"}                    # stage is not evidence
    assert families({"any": [{"on_call": True, "lure_tag": "kyc"}, {"on_call": True}]}) == {"C"}
    doc = {"playbooks": [{"name": "refund_qr", "why": "x", "match": {"on_call": True}}, APPROVED]}
    assert approved(doc) == {"society_maintenance_clone": ["B", "P"]}


def test_load_approved_reads_the_file_and_falls_back_quietly(tmp_path):
    doc = yaml.safe_load(playbooks.PATH.read_text(encoding="utf-8"))
    assert load_approved(playbooks.PATH) == (approved(doc), False)               # the shipped file: none yet
    doc["playbooks"].append({**APPROVED, "match": {**APPROVED["match"], "entry_method": "qr"}})
    path = tmp_path / "playbooks.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert load_approved(path) == ({"society_maintenance_clone": ["B", "P"]}, True)
    assert load_approved(tmp_path / "missing.yaml") == ({}, False)


NOW = datetime(2026, 10, 24, 12, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def decide(fams, p=0.05, lit=(), amount=4000, trusted=False, user="u1", policy=None):
    s = {"p_scam": p, "family_scores": {k: (0.9 if k in lit else 0.1) for k in "CLPB"},
         "playbook": "society_maintenance_clone" if fams is not None else None, "playbook_families": fams}
    f = {"amount_inr": amount, "trusted_payee": trusted, "payee_registry_listed": False, "caller_registry_listed": False,
         "payee_fri_level": None, "caller_fri_level": None}
    return (policy or Policy()).decide(s, f, "S0", False, user, NOW)


def test_an_approved_playbook_raises_a_low_score_to_a_warning():
    d = decide(["B", "P"])
    assert d.tier == "T2" and "approved_playbook" in d.applied
    assert d.message_key == "t2_society_maintenance_clone"   # the app falls back to t2's generic words
    assert decide(None).tier == "T0"                          # nothing approved matched: model decides
    assert decide(["B"]).tier == "T0"                         # one family is not enough (rule 5)
    assert decide(["B", "P"], p=0.8, lit="CP").tier == "T3"   # never lowers what the model found


def test_caps_trust_and_budget_still_apply_after_it():
    assert decide(["B", "P"], amount=150).tier == "T1"        # small payments are never interrupted
    assert decide(["B", "P"], trusted=True).tier == "T0"      # "I know this person", no override
    pol = Policy()
    tiers = [decide(["B", "P"], user="u9", policy=pol).tier for _ in range(3)]
    assert tiers == ["T2", "T2", "T1"]                        # the alert budget, as for any T2


def test_a_new_name_never_makes_the_engine_fail_open():
    """threat.fraud_type is the contract's six names; a newer approved name stays out of it."""
    from types import SimpleNamespace

    from api.main import threat_of
    d = SimpleNamespace(tier="T2", lit_families=[])
    t = threat_of({"p_scam": 0.05, "playbook": "society_maintenance_clone"}, d)
    assert t.level == "medium" and t.fraud_type is None
    assert threat_of({"p_scam": 0.6, "playbook": "refund_qr"}, d).fraud_type == "refund_qr"
