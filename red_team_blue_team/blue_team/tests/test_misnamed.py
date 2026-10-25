from blue_team import investigator, playbook_db, review
from bt_helpers import features, real_digital_arrest, voice_clone_named_arrest
import random


def misnamed(ws):
    return [c for c in ws.clusters.clusters if c.kind == "misnamed"]


def test_held_digital_arrests_split_and_the_family_calls_are_flagged(ws):
    groups = misnamed(ws)
    assert groups and all(c.nearest_playbook == "digital_arrest" for c in groups)
    flagged = {i.split("_")[0] for c in groups for i in c.case_ids}
    assert "rep4" in flagged                                   # the voice-clone family calls
    fam = next(c for c in groups if all(i.startswith("rep4") for i in c.case_ids))
    assert fam.baseline_ids and all(not i.startswith("rep4") for i in fam.baseline_ids[:3]) or fam.baseline_ids


def test_overview_and_task_say_what_ruko_called_it(ws):
    c = next(c for c in misnamed(ws) if all(i.startswith("rep4") for i in c.case_ids))
    ov = ws.overview(c.cluster_id)
    assert ov["ruko_named_it"] == "digital_arrest" and "digital_arrest" in ov["lift_is_against"]
    assert "named them 'digital_arrest'" in investigator.task_for(ws, c.cluster_id)


def test_a_fix_may_take_its_own_payments_but_not_the_real_arrests(ws):
    c = next(c for c in misnamed(ws) if all(i.startswith("rep4") for i in c.case_ids))
    fix = {"all": [{"token": "CALL_ON"}, {"token": "SAYS_FAMILY"}, {"token": "SESSION_DICTATED"}]}
    bt = ws.test_matcher(fix, c.cluster_id)
    assert bt["cluster_case_recall"] == 1.0 and bt["known_playbook_payments_also_matched"] == 0.0
    greedy = ws.test_matcher({"token": "SESSION_DICTATED"}, c.cluster_id)   # would take the real arrests too
    assert greedy["known_playbook_payments_also_matched"] > 0.3


def test_an_approved_fix_runs_just_before_the_playbook_it_corrects(tmp_db, tmp_path):
    # just below digital_arrest's first rule in the engine's file (its place moves when entries are added)
    first = min(pr for pb in playbook_db.load(("known",), tmp_db) if pb.name == "digital_arrest" for pr, _ in pb.rules)
    before = playbook_db.priority_before("digital_arrest", tmp_db)
    assert before == first - 1
    card = {"name": "relative_voice_clone", "title": "t", "status": "review", "summary": "s", "steps": ["a", "b"],
            "misnamed_as": "digital_arrest", "evidence": {"cases": 8, "cluster_id": "m"}, "gate_failures": [],
            "match": [{"priority": before, "rule": {"all": [{"token": "CALL_ON"}, {"token": "SAYS_FAMILY"}]}}],
            "mule_accounts": [], "label_tx_ids": [], "reviews": []}
    card["match"][0]["rule"] = __import__("blue_team.matcher", fromlist=["x"]).normalize(card["match"][0]["rule"])
    playbook_db.write(card, "review", tmp_db)
    review.decide("relative_voice_clone", "asha", "approve", root=tmp_db, exports=tmp_path / "x")
    out = review.decide("relative_voice_clone", "ravi", "approve", root=tmp_db, exports=tmp_path / "x")
    assert out["priority"] == before
    pbs = playbook_db.load(root=tmp_db)
    r = random.Random(3)
    assert playbook_db.name_scam(voice_clone_named_arrest(r), pbs) == "relative_voice_clone"
    assert playbook_db.name_scam(real_digital_arrest(r), pbs) == "digital_arrest"
    assert playbook_db.name_scam(features(lure_tag="arrest_threat"), pbs) == "digital_arrest"


def test_named_main_tie_break_does_not_depend_on_set_order():
    import pandas as pd
    from blue_team import breach
    rows = pd.DataFrame({"tx_id": ["a", "b"], "ts": pd.to_datetime(["2026-10-01", "2026-10-02"], utc=True),
                         "user_id": ["u", "u"], "payee_upi": ["m@ybl", "m@ybl"], "amount": [1000.0, 2000.0],
                         "weight": [1.0, 1.0], "tier": ["T3", "T3"], "named": ["refund_qr", "digital_arrest"], "p_scam": [0.9, 0.9]})
    comp = pd.DataFrame({"report_id": ["r1"], "user_id": ["u"], "filed_at": [pd.Timestamp("2026-10-05", tz="UTC")],
                         "source": ["1930"], "accounts": [["m@ybl"]]})
    c = breach.cases(breach.Scored(rows, [features(), features()], "t"), comp)
    assert c["named_main"].iloc[0] == "digital_arrest"          # one each: alphabetical, every run


def test_compare_hides_the_circular_rule_match_for_a_misnamed_group(ws):
    c = next(c for c in misnamed(ws) if all(i.startswith("rep4") for i in c.case_ids))
    cmp = ws.compare(c.cluster_id, "digital_arrest")
    assert str(cmp["playbook_rules_name_this_cluster"]).startswith("not shown")
    assert "officer" in cmp["playbook_summary"].lower() or cmp["playbook_steps"]
    assert cmp["reference_cases"] == 8                  # the 8 real digital arrests, not the group itself


def test_maps_place_every_clustered_complaint(ws):
    m = ws.clusters.maps
    breach_ids = set(ws.clusters.breaches["case_id"])
    assert {p["case_id"] for p in m["breach"]} == breach_ids
    assert all(0 <= p["x"] <= 1 and 0 <= p["y"] <= 1 for p in m["breach"])
    groups = {c.cluster_id for c in ws.clusters.clusters if c.kind != "misnamed"}
    assert {p["group"] for p in m["breach"]} - {None} == groups
    da = next(x for x in m["misnamed"] if x["playbook"] == "digital_arrest")
    flagged = {c.cluster_id for c in misnamed(ws)}
    assert flagged <= {p["group"] for p in da["points"]}
