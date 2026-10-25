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


def tiny_world(root):
    """Two attacks with three journeys each (two payments a journey), one journey inside the warm-up,
    and 800 honest payments, over 10 days from 2026-10-01."""
    import json as _json

    import pandas as pd
    root.mkdir(parents=True)
    t0 = pd.Timestamp("2026-10-01", tz="Asia/Kolkata")
    rows, jr, rep = [], [], []
    for a in ("shop", "relative"):
        for k in range(3):
            j = f"{a}_{k}"
            start = t0 + pd.Timedelta(days=(1 if k == 0 else 5 + k))       # k == 0 starts in the warm-up
            jr.append({"journey_id": j, "playbook": a, "user_id": f"u{k}"})
            for i in range(2):
                rows.append({"tx_id": f"{j}_{i}", "ts": start + pd.Timedelta(hours=i), "from_upi": f"u{k}@ybl",
                             "journey_id": j, "label_is_scam": True})
            rep.append({"report_id": f"r_{j}", "identifier_type": "upi_id", "identifier": f"mule_{j}@ybl", "journey_id": j,
                        "filed_at": start + pd.Timedelta(days=1), "source": "1930"})
    for i in range(800):
        rows.append({"tx_id": f"h{i}", "ts": t0 + pd.Timedelta(minutes=17 * i), "from_upi": f"u{i % 5}@ybl",
                     "journey_id": None, "label_is_scam": False})
    pd.DataFrame(rows).to_parquet(root / "ledger.parquet")
    pd.DataFrame(jr).to_parquet(root / "journeys.parquet")
    pd.DataFrame(rep).to_parquet(root / "reports.parquet")
    pd.DataFrame({"user_id": [f"u{i}" for i in range(5)], "upi_id": [f"u{i}@ybl" for i in range(5)]}).to_parquet(root / "users.parquet")
    (root / "manifest.json").write_text(_json.dumps({"config": {"end": (t0 + pd.Timedelta(days=10)).isoformat(), "n_days": 10}}))
    return root


def test_the_session_takes_whole_journeys_of_every_attack_and_fills_to_the_total_with_honest_ones(tmp_path):
    w = tiny_world(tmp_path / "w")
    sel = sc.select_live(w, ["shop", "relative"], total=20, scam_share=0.5, warmup_days=3, seed=0)
    assert len(sel["tx_ids"]) == 20 and sel["scam_payments"] + sel["honest_payments"] == 20
    assert sel["per_attack"] == {"shop": {"journeys": 2, "payments": 4}, "relative": {"journeys": 2, "payments": 4}}
    assert "shop_0" not in sel["journeys"]                                        # started in the warm-up
    assert {"u1", "u2"} <= set(sel["users"])                                      # the victims' records are streamed
    small = sc.select_live(w, ["shop", "relative"], total=10, scam_share=0.5, warmup_days=3, seed=0)
    assert small["scam_payments"] == 4 and small["per_attack"]["shop"]["journeys"] == 1   # a fair share each


def test_the_blue_team_sees_only_the_session_victims_complaints(tmp_path):
    import pandas as pd
    w = tiny_world(tmp_path / "w")
    out = sc.world_for_blue_team(w, ["shop_1", "relative_2"], tmp_path / "live")
    assert sorted(pd.read_parquet(out / "reports.parquet")["journey_id"]) == ["relative_2", "shop_1"]
    assert (out / "ledger.parquet").exists() and len(pd.read_parquet(w / "reports.parquet")) == 6
    c = sc._complaints(w, ["shop_1", "relative_2"])
    assert [x["accounts"] for x in c] == [["mule_shop_1@ybl"], ["mule_relative_2@ybl"]] and c[0]["filed_at"] < c[1]["filed_at"]


def test_the_start_endpoint_takes_one_to_three_different_attacks(monkeypatch, tmp_path):
    use_home(monkeypatch, tmp_path)
    from blue_team import redteam
    names = [p["name"] for p in redteam.load()][:4]
    c = TestClient(webapp.create_app(root=tmp_path / "db", exports=tmp_path / "e", runs=tmp_path / "r", scenario_mode=True))
    assert c.post("/api/live/start", json={"attacks": names}).status_code == 400            # four
    assert c.post("/api/live/start", json={"attacks": [names[0], names[0]]}).status_code == 400
    assert c.post("/api/live/start", json={"attacks": []}).status_code == 400


def test_a_world_of_only_the_picked_attacks_builds(tmp_path):
    """No known scam picked: the simulator's scripted demo journeys still need their crew (KeyError
    'crew_digital_arrest_0' before), so that playbook stays at weight 0."""
    import shutil

    import pandas as pd
    from blue_team import redteam
    pb = redteam.load()[0]
    (tmp_path / "red").mkdir()
    shutil.copy(redteam.RED_DIR / pb["file"], tmp_path / "red" / pb["file"])
    redteam.build_world(tmp_path / "w", 120, 7, 51, 1.0, 15.0, red_dir=tmp_path / "red", log=lambda *a: None, known=[])
    j = pd.read_parquet(tmp_path / "w" / "journeys.parquet")
    assert pb["name"] in set(j["playbook"])
    assert set(j.loc[j["playbook"] != pb["name"], "journey_id"]) <= {f"j_demo_{k}" for k in range(10)}   # only the scripted ones


def test_stop_and_clear_ends_the_sessions_processes_and_empties_the_demo(monkeypatch, tmp_path):
    import sys
    use_home(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "CHILDREN", tmp_path / "children.json")
    (tmp_path / "world").mkdir()
    (tmp_path / "feed.jsonl").write_text("{}\n", encoding="utf-8")
    proc = sc._start_child([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path / "child.log", {**__import__("os").environ})
    assert sc._children() == [proc.pid]
    out = sc.stop_and_clear()
    assert out["stopped_processes"] == 1
    proc.wait(timeout=10)                                   # it was really ended
    assert proc.returncode != 0 and list(tmp_path.iterdir()) == []


def test_after_stop_nothing_new_starts(monkeypatch, tmp_path):
    import sys

    import pytest
    use_home(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "CHILDREN", tmp_path / "children.json")
    sc.control(cancel=True)
    with pytest.raises(sc.Cancelled):
        sc._start_child([sys.executable, "-c", "pass"], tmp_path / "x.log", {})


def test_the_clear_endpoint_resets_the_console(monkeypatch, tmp_path):
    use_home(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "CHILDREN", tmp_path / "children.json")
    monkeypatch.setattr(sc, "STATE", tmp_path / "scenario.json")
    sc.emit({"kind": "stage", "text": "old"})
    c = TestClient(webapp.create_app(root=tmp_path / "db", exports=tmp_path / "e", runs=tmp_path / "r", scenario_mode=True))
    assert c.post("/api/live/clear", json={}).status_code == 200
    d = c.get("/api/live").json()
    assert d["events"] == [] and d["state"] in ("none", "idle")
    off = TestClient(webapp.create_app(root=tmp_path / "db", exports=tmp_path / "e", runs=tmp_path / "r"))
    assert off.post("/api/live/clear", json={}).status_code == 400
