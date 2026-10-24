from fastapi.testclient import TestClient

from blue_team import playbook_db, webapp


def queued(tmp_db, name="relative_voice_clone", **kw):
    card = {"name": name, "title": "Voice-clone relative", "status": "review", "summary": "s", "steps": ["call", "pay"],
            "advice_en": "Call your relative back.", "advice_hi": "अपने रिश्तेदार को वापस कॉल करें।",
            "match": [{"priority": 100, "rule": {"all": [{"feature": "on_call", "op": "is", "value": True},
                                                          {"feature": "payer_says", "op": "eq", "value": "family"}]}}],
            "evidence": {"cases": 8, "cluster_id": "c00", "run_id": "none"}, "gate_failures": [],
            "analyst": {"verdict": "new_scam"}, "mule_accounts": [{"upi_id": "m@ybl", "cases": 3}],
            "label_tx_ids": ["tx1"], "reviews": [], "rule_in_words": "(on_call is True AND payer_says eq family)"}
    card.update(kw)
    playbook_db.write(card, "review", tmp_db)


def client(tmp_db, tmp_path):
    return TestClient(webapp.create_app(root=tmp_db, exports=tmp_path / "exports", runs=tmp_path / "runs"))


def test_page_and_list(tmp_db, tmp_path):
    queued(tmp_db)
    c = client(tmp_db, tmp_path)
    assert "Blue Team Console" in c.get("/").text
    lst = c.get("/api/cards").json()
    assert [s["name"] for s in lst["review"]] == ["relative_voice_clone"] and lst["approved"] == []


def test_detail_shows_engine_blockers_and_hides_labels(tmp_db, tmp_path):
    queued(tmp_db)
    d = client(tmp_db, tmp_path).get("/api/cards/relative_voice_clone").json()
    assert "label_tx_ids" not in d["card"] and d["engine"]["ready"] is True
    assert d["engine"]["effect"] == "warns" and d["engine"]["families"] == ["B", "C"]   # on_call + payer_says
    assert any("fraud_type stays empty" in n for n in d["engine"]["notes"])
    queued(tmp_db, name="qr_only", match=[{"priority": 100, "rule": {"all": [
        {"feature": "entry_method", "op": "eq", "value": "qr"}, {"feature": "amount_inr", "op": "<", "value": 1000}]}}])
    assert client(tmp_db, tmp_path).get("/api/cards/qr_only").json()["engine"]["effect"] == "names only"
    queued(tmp_db, name="not_range", match=[{"priority": 100, "rule": {"not": {"feature": "amount_inr", "op": "<", "value": 1000}}}])
    e = client(tmp_db, tmp_path).get("/api/cards/not_range").json()["engine"]
    assert e["ready"] is False and any("NOT" in b for b in e["blockers"])


def test_two_analysts_approve_through_the_page(tmp_db, tmp_path):
    queued(tmp_db)
    c = client(tmp_db, tmp_path)
    r = c.post("/api/cards/relative_voice_clone/decision", json={"analyst": "asha", "decision": "approve"}).json()
    assert r["status"] == "review"
    assert c.post("/api/cards/relative_voice_clone/decision", json={"analyst": "asha", "decision": "approve"}).status_code == 400
    r = c.post("/api/cards/relative_voice_clone/decision", json={"analyst": "ravi", "decision": "approve"}).json()
    assert r["status"] == "approved" and (tmp_path / "exports" / "relative_voice_clone" / "playbooks_entry.yaml").exists()
    assert [s["name"] for s in c.get("/api/cards").json()["approved"]] == ["relative_voice_clone"]


def test_reject_needs_a_reason_and_edits_clear_approvals(tmp_db, tmp_path):
    queued(tmp_db)
    c = client(tmp_db, tmp_path)
    c.post("/api/cards/relative_voice_clone/decision", json={"analyst": "asha", "decision": "approve"})
    r = c.post("/api/cards/relative_voice_clone/text", json={"analyst": "ravi", "fields": {"title": "Voice-clone 'son in trouble' call"}}).json()
    assert r["changed"] == ["title"] and r["approvals_cleared"] == ["asha"]
    bad = c.post("/api/cards/relative_voice_clone/text", json={"analyst": "ravi", "fields": {"advice_hi": "english only"}})
    assert bad.status_code == 400 and "Devanagari" in bad.json()["detail"]
    assert c.post("/api/cards/relative_voice_clone/text", json={"analyst": "ravi", "fields": {"match": []}}).status_code == 400
    assert c.post("/api/cards/relative_voice_clone/decision", json={"analyst": "ravi", "decision": "reject"}).status_code == 400
    r = c.post("/api/cards/relative_voice_clone/decision", json={"analyst": "ravi", "decision": "reject", "note": "same as digital_arrest"}).json()
    assert r["status"] == "rejected"
    assert c.get("/api/cards/digital_arrest").status_code == 404


def test_runs_events_and_reset(tmp_db, tmp_path):
    import json
    run = tmp_path / "runs" / "r1"
    (run / "candidates").mkdir(parents=True)
    (run / "status.json").write_text(json.dumps({"run_id": "r1", "state": "done"}), encoding="utf-8")
    lines = [json.dumps({"seq": i, "ts": "2026-10-23T00:00:00", "stage": "hdbscan", "kind": "decision",
                         "text": f"step {i}", "refs": {}, "data": {}}) for i in (1, 2, 3)]
    (run / "events.jsonl").write_text("".join(line + chr(10) for line in lines), encoding="utf-8")
    (run / "cases.json").write_text(json.dumps([{"case_id": "rep1", "status": "missed"}]), encoding="utf-8")
    queued(tmp_db)
    c = client(tmp_db, tmp_path)
    assert [r["run_id"] for r in c.get("/api/runs").json()] == ["r1"]
    ev = c.get("/api/runs/r1/events?after=1").json()
    assert [e["seq"] for e in ev["events"]] == [2, 3] and ev["status"]["state"] == "done"
    assert c.get("/api/runs/r1/cases").json()[0]["case_id"] == "rep1"
    assert c.get("/api/runs/..%2Fetc/events").status_code == 404           # run ids are checked
    assert "relative_voice_clone" in c.get("/api/cards/relative_voice_clone/yaml").text
    db = c.get("/api/database").json()
    assert {k["name"] for k in db["known"]} >= {"digital_arrest", "refund_qr"} and db["waiting"] == 1
    assert c.post("/api/reset", json={"confirm": "yes"}).status_code == 400
    assert c.post("/api/reset", json={"confirm": "RESET"}).json()["deleted_cards"] == 1
    assert c.get("/api/runs").json() == [] and c.get("/api/cards").json()["review"] == []


def test_cited_sources_are_checked_against_real_tool_calls():
    from blue_team.investigator import check_sources
    tr = [{"tool_calls": [{"name": "get_case", "input": {"case_id": "rep_7"}}, {"name": "get_cluster_overview", "input": {}}]}]
    out = check_sources([{"source": "get_case rep_7", "fact": "a"}, {"source": "get_case rep_9", "fact": "b"},
                         {"source": "get_cluster_overview", "fact": "c"}, {"source": "test_matcher", "fact": "d"}], tr)
    assert [e["seen"] for e in out] == [True, False, True, False]


def test_the_console_script_parses(tmp_path):
    """A syntax error blanks every page; node checks the page's script when it is installed."""
    import shutil
    import subprocess

    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    page = webapp.PAGE.read_text(encoding="utf-8")
    js = tmp_path / "console.js"
    js.write_text(page[page.index("<script>") + 8:page.rindex("</script>")], encoding="utf-8")
    r = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
