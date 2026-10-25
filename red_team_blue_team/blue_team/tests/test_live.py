"""The live loop (scenario.start_live / rerun_live, the console's Live tab): pacing, the payment events
it shows one at a time, the feed, and the endpoints' checks."""
import time

from fastapi.testclient import TestClient

from blue_team import scenario as sc, webapp


def use_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "HOME", tmp_path)
    monkeypatch.setattr(sc, "FEED", tmp_path / "feed.jsonl")
    monkeypatch.setattr(sc, "CONTROL", tmp_path / "control.json")


def test_control_pauses_steps_and_sets_the_speed(monkeypatch, tmp_path):
    use_home(monkeypatch, tmp_path)
    assert sc.control()["paused"] is False
    assert sc.control(paused=True, delay=0.0)["paused"] is True
    c = sc.control(step=True)
    assert c["steps"] == 1 and c["paused"] is True and c["delay"] == 0.0
    assert sc.control(step=True)["steps"] == 2


def test_the_pacer_waits_while_paused_and_lets_one_payment_through_per_step(monkeypatch, tmp_path):
    use_home(monkeypatch, tmp_path)
    sc.control(paused=False, delay=0.0)
    pacer = sc._Pacer()
    t0 = time.perf_counter()
    pacer.wait()                                         # not paused, no delay: immediate
    assert time.perf_counter() - t0 < 0.2
    sc.control(paused=True)
    sc.control(step=True)
    t0 = time.perf_counter()
    pacer.wait()                                         # one step was sent: goes at once
    assert time.perf_counter() - t0 < 0.2
    import threading
    done = threading.Event()
    threading.Thread(target=lambda: (pacer.wait(), done.set()), daemon=True).start()
    assert not done.wait(0.6)                            # paused, no new step: waits
    sc.control(step=True)
    assert done.wait(2)


def body(**ctx):
    return {"request_id": "r1", "user_id": "u_000123", "payee_upi_id": "mule@ybl", "amount_inr": 3500.0,
            "entry_method": "qr", "ts": "2026-10-20T11:00:00+05:30", "context": ctx}


def test_payment_events_say_what_the_red_team_sent_and_what_the_engine_answered():
    label = {"is_scam": True, "playbook": "olx_army", "journey_id": "j1", "journey_pay_index": 1}
    inner = {"inner_name": None, "policy_steps": "fused_threat", "_steps": ["new_payee", "qr_entry"],
             "_parts": {"lgbm": 0.01, "playbook": 0.0}, "_match": None, "_reasons": []}
    e = sc._payment_event("before", body(call={"active": True, "kind": "voip", "caller_in_contacts": False}),
                          label, {"tier": "T0", "threat": {"score": 1}}, inner, 7)
    assert e["verdict"] == "missed" and e["red"]["playbook"] == "olx_army" and e["red"]["step"] == 1
    assert e["phone"]["call"] and e["phone"]["unknown_caller"] and e["engine"]["steps"] == ["new_payee", "qr_entry"]
    assert e["user"] == "u…0123"                         # never the full user id on screen
    ok = sc._payment_event("before", body(), {**label, "is_scam": False}, {"tier": "T2", "threat": {}}, inner, 8)
    assert ok["verdict"] == "false alarm"
    assert sc._payment_event("before", body(), label, {"tier": "T3", "threat": {}}, inner, 9)["verdict"] == "caught"
    assert sc._payment_event("before", body(), label, {"tier": "T1", "threat": {}}, inner, 9)["verdict"] == "warned only"


def test_the_feed_is_read_from_where_the_console_left_off(monkeypatch, tmp_path):
    use_home(monkeypatch, tmp_path)
    assert sc.feed_since(0) == ([], 0)
    sc.emit({"kind": "stage", "text": "a"})
    sc.emit({"kind": "stage", "text": "b"})
    evs, n = sc.feed_since(1)
    assert n == 2 and [e["text"] for e in evs] == ["b"] and evs[0]["at"]


def test_endpoints_need_demo_mode_a_real_attack_and_an_approval(monkeypatch, tmp_path):
    use_home(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "STATE", tmp_path / "scenario.json")
    c = TestClient(webapp.create_app(root=tmp_path / "db", exports=tmp_path / "e", runs=tmp_path / "r", scenario_mode=True))
    assert c.post("/api/live/start", json={"attack": "no_such_attack"}).status_code == 400
    assert c.post("/api/live/control", json={"delay": 99}).status_code == 400
    assert c.post("/api/live/control", json={"paused": True}).json()["paused"] is True
    assert c.post("/api/live/replay", json={}).status_code == 400          # no attack yet
    d = c.get("/api/live").json()
    assert d["mode"] is True and d["events"] == [] and d["control"]["paused"] is True
    off = TestClient(webapp.create_app(root=tmp_path / "db", exports=tmp_path / "e", runs=tmp_path / "r"))
    from blue_team import redteam
    name = redteam.load()[0]["name"]
    assert off.post("/api/live/start", json={"attack": name}).status_code == 400   # not in demo mode
