"""The redesigned console's new data (docs/design/red-blue-console/README.md): scam groups, per-condition
rule numbers, the two closest known playbooks, the per-attack detail and the generator endpoint."""
import json

from fastapi.testclient import TestClient

from blue_team import groups, inbox, webapp
from test_webapp import queued
from test_workspace_and_agents import GOOD

SCRIPT_TASK = {"steps": [{"events": [{"type": "notification_lure", "tag": "task_job"}]}]}
SCRIPT_NONE = {"steps": [{"events": [{"type": "call", "direction": "in"}]}]}


def pb(name, script):
    return {"name": name, "title": name.replace("_", " "), "techniques": ["cool_off"], "playbook": script}


def verdict(name, through, judged=10, normal=None):
    return {"playbook": name, "breakthrough": through, "scam_payments_judged": judged,
            "scam_called_normal": normal if normal is not None else (judged if through else 1),
            "miss_rate": (normal if normal is not None else (judged if through else 1)) / judged}


def test_a_new_scam_cluster_starts_its_own_group_else_the_nearest_known_or_the_lure():
    rows = {"rows": [
        {"playbook": "a", "complaints": 5, "groups": [{"group": "c01", "complaints": 4, "verdict": "new_scam", "playbook": "shop_prepay"},
                                                      {"group": "c02", "complaints": 1, "verdict": "variant_of_known", "playbook": "x"}]},
        {"playbook": "b", "complaints": 3, "groups": [{"group": "c02", "complaints": 3, "verdict": "variant_of_known", "playbook": "x"}]},
        {"playbook": "c", "complaints": 0, "groups": []}]}
    clusters = [{"cluster_id": "c01", "nearest_playbook": "refund_qr"}, {"cluster_id": "c02", "nearest_playbook": "digital_arrest"}]
    cards = {"review": [{"name": "shop_prepay", "title": "Online shop, pay first", "approvals": ["asha"], "needed": 2}],
             "approved": [], "rejected": []}
    out = groups.build([pb("a", SCRIPT_NONE), pb("b", SCRIPT_NONE), pb("c", SCRIPT_TASK), pb("d", SCRIPT_NONE)],
                       {"a": verdict("a", True), "b": verdict("b", False), "c": verdict("c", True)}, rows, clusters, cards,
                       {"digital_arrest": "Digital arrest", "task_job": "Task & job"})
    by = {g["group"]: g for g in out}
    assert by["shop_prepay"]["kind"] == "new" and by["shop_prepay"]["title"] == "Online shop, pay first"
    assert by["shop_prepay"]["playbook_state"] == "1 of 2" and out[0]["group"] == "shop_prepay"      # new groups first
    assert by["digital_arrest"]["members"][0]["playbook"] == "b" and by["digital_arrest"]["title"] == "Digital arrest"
    assert "not grouped yet" in by["task_job"]["members"][0]["why"]
    assert by[groups.UNGROUPED]["judged"] == 0 and by[groups.UNGROUPED]["status"] == "not judged" and out[-1]["group"] == groups.UNGROUPED
    assert by["shop_prepay"]["called_normal_share"] == 1.0 and by["digital_arrest"]["status"] == "mostly caught"


def test_the_backtest_reports_each_condition_and_the_two_closest_known_playbooks(ws, new_cluster):
    bt = ws.test_matcher(GOOD, new_cluster)
    cond = bt["conditions"]
    assert cond["mode"] == "all" and len(cond["parts"]) == len(GOOD["all"])
    for p in cond["parts"]:
        assert 0 <= p["case_share"] <= 1 and p["legit_per_1000"] >= 0 and p["in_words"]
        assert p["case_share"] >= bt["cluster_case_recall"]          # one condition alone names at least as many
    near = ws.nearest_signals(new_cluster)
    assert 1 <= len(near["playbooks"]) <= 2 and near["known_similarity"] > 0
    assert all(len(s["there"]) == len(near["playbooks"]) and 0 <= s["here"] <= 1 for s in near["signals"])
    sims = [p["similarity"] for p in near["playbooks"]]
    assert sims == sorted(sims, reverse=True)


def test_card_summary_and_detail_carry_what_the_playbook_page_needs(tmp_db, tmp_path):
    queued(tmp_db, backtest={"cluster_case_recall": 0.84, "legit_payments_named_per_1000": 0.3, "families": ["B", "C"]})
    c = TestClient(webapp.create_app(root=tmp_db, exports=tmp_path / "e", runs=tmp_path / "r"))
    s = c.get("/api/cards").json()["review"][0]
    assert s["catches"] == 0.84 and s["legit_per_1000"] == 0.3 and s["warns"] is True
    d = c.get("/api/cards/relative_voice_clone").json()
    assert {"min_cluster_recall", "max_legit_per_1000", "known_similarity"} <= set(d["limits"])


def test_attack_detail_reads_the_runners_results(tmp_db, tmp_path, monkeypatch):
    out = tmp_path / "runner" / "courier"
    out.mkdir(parents=True)
    (out / "results.csv").write_text(
        "journey_pay_index,judged,is_scam,threat_score,called_normal,reasons\n"
        "0,True,True,12,True,\n0,True,True,85,False,R1_live_unknown_call|R3_mule_like_payee\n"
        "1,True,True,40,True,\n,True,False,5,True,\n", encoding="utf-8")
    box = tmp_path / "inbox"
    (box / "verdicts").mkdir(parents=True)
    (box / "verdicts" / "courier.json").write_text(json.dumps({**verdict("courier", True, 3, 2), "runner_out": str(out)}))
    monkeypatch.setattr(inbox, "INBOX", box)
    c = TestClient(webapp.create_app(root=tmp_db, exports=tmp_path / "e", runs=tmp_path / "r"))
    d = c.get("/api/redteam/playbooks/courier/detail").json()
    assert sum(d["histogram"]) == 3 and d["histogram"][2] == 1 and d["histogram"][17] == 1
    assert d["by_step"] == [{"step": 0, "payments": 2, "called_normal": 1}, {"step": 1, "payments": 1, "called_normal": 1}]
    assert d["reasons"] == {"R1_live_unknown_call": 1, "R3_mule_like_payee": 1}
    assert c.get("/api/redteam/playbooks/nope/detail").status_code == 404
    g = c.get("/api/groups").json()
    assert g["graded"] is False and isinstance(g["groups"], list)
    assert c.post("/api/redteam/generate", json={"count": 0}).status_code == 400
