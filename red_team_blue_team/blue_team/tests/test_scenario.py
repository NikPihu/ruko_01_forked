import pandas as pd
import yaml

from blue_team import scenario


def test_summary_counts_interruptions_per_scam_type(tmp_path):
    rows = ([{"journey_id": "j1", "playbook": "new_a", "is_scam": True, "judged": True, "tier": t, "named": n, "fail_open": False}
             for t, n in (("T0", None), ("T2", "new_a"), ("T0", None))]
            + [{"journey_id": "j2", "playbook": "digital_arrest", "is_scam": True, "judged": True, "tier": "T3",
                "named": "digital_arrest", "fail_open": False}]
            + [{"journey_id": None, "playbook": None, "is_scam": False, "judged": j, "tier": t, "named": None, "fail_open": False}
               for j, t in ((True, "T0"), (True, "T2"), (False, "T3"), (True, "T0"))])
    p = tmp_path / "payments.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    s = scenario.summarise(p)
    assert s["types"]["new_a"] == {"payments": 3, "journeys": 1, "interrupted": 1, "warned": 1,
                                   "named_as": {"new_a": 1}, "fail_open": 0, "missed_because": {}}
    assert s["honest_payments"] == 3 and s["honest_interrupted_per_1000"] == 333.33   # the warm-up row is not judged
    text = scenario.report(s, {**s, "types": {**s["types"], "new_a": {**s["types"]["new_a"], "interrupted": 3}}}, ["new_a"])
    assert "NEW" in text and "1/3 -> 3/3" in text and text.index("new_a") < text.index("digital_arrest")


def test_the_rerun_file_holds_every_approved_card_the_format_can_express(tmp_path):
    from api.playbooks import load_approved
    ok = {"name": "society_clone", "title": "Society maintenance clone", "approved_by": ["asha", "ravi"],
          "match": [{"priority": 100, "rule": {"all": [{"feature": "session_dictated", "op": "is", "value": True},
                                                       {"feature": "payee_registry_listed", "op": "is", "value": True}]}}]}
    bad = {**ok, "name": "not_range",
           "match": [{"priority": 100, "rule": {"not": {"feature": "amount_inr", "op": "<", "value": 1000}}}]}
    path, skipped = scenario.playbooks_file([ok, bad], tmp_path)
    assert [s.split(":")[0] for s in skipped] == ["not_range"]
    names = [p["name"] for p in yaml.safe_load(path.read_text(encoding="utf-8"))["playbooks"]]
    assert names[-1] == "society_clone"
    assert load_approved(path)[0] == {"society_clone": ["B", "P"]}     # the engine will raise its payments


def test_a_second_demo_step_is_refused_while_one_runs():
    import pytest
    with scenario._Lock():
        assert scenario.busy()
        with pytest.raises(scenario.Busy):
            scenario.start(["x"], ["y"])          # would otherwise delete the running world
    assert not scenario.busy()


def test_why_a_scam_payment_was_not_stopped():
    w = scenario.why_missed
    assert w({"approved_families": "B"}).startswith("an approved playbook named it, but its conditions are one family")
    assert w({"approved_families": "B+P", "policy_steps": "approved_playbook|amount_cap_200"}) == "a small payment (amount cap)"
    assert w({"approved_families": "B+P", "policy_steps": "approved_playbook|trusted_payee"}) == "the user marked the payee as trusted"
    assert w({"inner_name": "refund_qr"}) == "named refund_qr, but the model scored it low"
    assert w({"inner_name": float("nan")}) == "no playbook matched and the model scored it low"
    assert w({"fail_open": True}) == "the engine failed open (no answer in time)"
