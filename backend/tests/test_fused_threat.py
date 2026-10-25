"""The fused threat (api/threat.py) and the policy's fused mode (api/policy.py, plan v3 step 5)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from api import threat
from api.policy import Policy

FZ = threat.Fusion("m-1", iso_x=[0.2, 0.5, 0.9], iso_y=[0.01, 0.2, 0.8])
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def feats(**kw) -> dict:
    f = {"payee_registry_listed": False, "caller_registry_listed": False, "payee_fri_level": None,
         "caller_fri_level": None, "amount_inr": 5000.0, "trusted_payee": False}
    return {**f, **kw}


def test_no_match_is_the_model_alone_and_either_strong_is_enough():
    assert FZ.threat(0.3, 0.0)[0] == 0.3
    assert FZ.threat(0.0, 0.9)[0] == 0.8
    both, parts = FZ.threat(0.5, 0.9)
    assert both > 0.8 and both > 0.5 and parts == {"lgbm": 0.5, "playbook": 0.8, "similarity": 0.9}


def test_monotonic_in_both_parts():
    sims, ps = [0.0, 0.3, 0.5, 0.7, 0.95], [0.0, 0.1, 0.4, 0.9]
    for p in ps:
        row = [FZ.threat(p, s)[0] for s in sims]
        assert row == sorted(row)
    for s in sims:
        col = [FZ.threat(p, s)[0] for p in ps]
        assert col == sorted(col)


def test_a_logistic_form_never_counts_less_than_either_part():
    lg = threat.Fusion("m-1", FZ.iso_x, FZ.iso_y, form="logistic", coef=(0.1, 0.1, 0.0), intercept=-8.0)
    assert lg.threat(0.6, 0.9)[0] >= 0.8 and lg.threat(0.6, 0.0)[0] >= 0.6


def test_the_file_belongs_to_one_model(tmp_path):
    p = tmp_path / "fusion.json"
    p.write_text(json.dumps({"model_version": "m-1", "playbook_iso": {"x": [0.5], "y": [0.3]}}))
    assert threat.load("m-1", p) is not None
    assert threat.load("m-2", p) is None
    assert threat.load("m-1", tmp_path / "missing.json") is None
    p.write_text("{broken")
    assert threat.load("m-1", p) is None


def s(threat_v: float | None, p: float = 0.1, fams: dict | None = None) -> dict:
    out = {"p_scam": p, "family_scores": fams or {"C": 0.9, "L": 0.0, "P": 0.0, "B": 0.0}, "playbook": "digital_arrest"}
    return out if threat_v is None else {**out, "threat": threat_v}


def test_tiers_follow_the_threat_without_the_two_families_gate():
    pol = Policy()
    bars = pol.cfg["fused"]["tiers"]
    d = pol.decide(s(bars["T3"] + 0.01), feats(), "S2", False, "u1", NOW)
    assert d.tier == "T3" and "fused_threat" in d.applied and d.lit_families == ["C"]
    assert pol.decide(s(bars["T1"] - 0.01), feats(), "S2", False, "u2", NOW).tier == "T0"
    # one strong family and no fused threat (rules fallback): the gate still holds
    assert pol.decide(s(None, p=0.95), feats(), "S2", False, "u3", NOW).tier == "T0"


def test_t4_still_needs_an_intel_hit_and_the_guardrails_still_apply():
    pol = Policy()
    top = s(0.999)
    assert pol.decide(top, feats(), "S4", False, "u1", NOW).tier == "T3"
    assert pol.decide(top, feats(payee_registry_listed=True), "S4", False, "u2", NOW).tier == "T4"
    assert pol.decide(top, feats(amount_inr=150.0), "S4", False, "u3", NOW).tier == "T1"          # under Rs 200
    assert pol.decide(top, feats(trusted_payee=True), "S1", False, "u4", NOW).tier == "T0"         # "I know them"
    assert pol.decide(top, feats(trusted_payee=True), "S3", True, "u5", NOW).tier == "T3"          # ...not under control


def test_the_alert_budget_reads_the_threat():
    pol = Policy()
    bars = pol.cfg["fused"]["tiers"]
    mid = s(bars["T2"] + 0.01)
    tiers = [pol.decide(mid, feats(), "S1", False, "same", NOW).tier for _ in range(4)]
    assert tiers[:2] == ["T2", "T2"] and tiers[2:] == ["T1", "T1"]
