from fastapi.testclient import TestClient

from blue_team import redteam, webapp


def pb(*steps, **kw):
    return {"name": "x", "steps": list(steps), **kw}


ASK_QR = {"ask": {"amount": {"log": [1000, 4000]}, "entry": {"qr": 0.8, "contact": 0.2}, "mule": "same"}}


def test_techniques_are_read_from_the_script():
    cool = pb({"events": [{"type": "call", "direction": "incoming"}]}, {"gap_min": [40, 90], **ASK_QR})
    assert "cool_off" in redteam.techniques(cool)
    live = pb({"events": [{"type": "call"}]}, {"gap_min": [40, 90], "ask": {**ASK_QR["ask"], "during_call": True}})
    assert "cool_off" not in redteam.techniques(live)
    notif = pb({"events": [{"type": "notification_lure", "tag": "refund", "conf": [0.4, 0.7]}]}, ASK_QR)
    assert "notification_lure" in redteam.techniques(notif)
    weak = pb({"events": [{"type": "sms_lure", "tag": "kyc", "conf": [0.3, 0.55]}]}, ASK_QR)
    assert "sub_threshold_sms" in redteam.techniques(weak)
    anchor = pb({"ask": {"amount": {"int": [100, 220]}, "entry": {"qr": 1}, "mule": "same"}}, ASK_QR)
    assert "anchor_then_drain" in redteam.techniques(anchor)
    typed = pb({"ask": {"amount": 5000, "entry": {"typed": 1.0}}})
    assert "non_typed_entry" not in redteam.techniques(typed)
    assert "single_bait" in redteam.techniques(pb({"crew_pays": {"amount": 150, "repeat": 1}}, ASK_QR))
    assert "mule_cover" in redteam.techniques(pb(ASK_QR, mules={"slots": 8}))


def test_all_fifty_red_team_playbooks_load_with_their_tricks():
    pbs = redteam.load()
    assert len(pbs) == 50 and len({p["name"] for p in pbs}) == 50
    assert all(p["techniques"] for p in pbs)
    assert sum("notification_lure" in p["techniques"] for p in pbs) == 25    # as Nikunj's README says
    assert all(p["claimed_ml_missed"] is not None for p in pbs)


def test_console_lists_the_red_team(tmp_db, tmp_path):
    c = TestClient(webapp.create_app(root=tmp_db, exports=tmp_path / "e", runs=tmp_path / "runs", repo=tmp_path))
    d = c.get("/api/redteam").json()
    assert len(d["playbooks"]) == 50 and "steps_detail" in d["playbooks"][0] and "playbook" not in d["playbooks"][0]
    assert d["world"]["built"] is False and d["build"]["state"] == "idle"
    assert c.post("/api/redteam/build", json={"users": 5}).status_code == 400          # out of range
    assert any(w.get("red_team") for w in c.get("/api/worlds").json())
