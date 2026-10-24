import sys
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from blue_team import inbox, webapp

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "synthetic_playbook"))
from interface_script.judge import Verdict  # noqa: E402  (the attack runner's judge, the real thing)


def verdict(name, missed, judged):
    v = Verdict(playbook=name, scorer="lgbm-0.2", normal_max_score=70, breakthrough_share=0.75)
    for i in range(judged):
        v.add({"judge": True, "is_scam": True, "journey_id": f"j{i}"}, {"threat": {"score": 10 if i < missed else 90}}, 200)
    return v


def test_breakthroughs_reach_the_inbox_and_caught_ones_leave_it(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "playbook.yaml").write_text("name: x\nsteps: []\n", encoding="utf-8")
    box = tmp_path / "inbox"
    inbox.receive(verdict("courier_cooloff", 9, 10), None, pd.DataFrame(), out, log=lambda *a: None, inbox=box)
    inbox.receive(verdict("loud_scam", 1, 10), None, pd.DataFrame(), out, log=lambda *a: None, inbox=box)
    assert [p.stem for p in inbox.breakthroughs(box)] == ["courier_cooloff"]
    v = inbox.verdicts(box)
    assert v["courier_cooloff"]["breakthrough"] and not v["loud_scam"]["breakthrough"] and v["loud_scam"]["miss_rate"] == 0.1
    inbox.receive(verdict("courier_cooloff", 1, 10), None, pd.DataFrame(), out, log=lambda *a: None, inbox=box)
    assert inbox.breakthroughs(box) == []          # RUKO catches it now: no longer the blue team's job


def test_the_runner_sink_list_includes_the_blue_team():
    from interface_script import sinks
    assert sinks.blue_team in sinks.SINKS


def test_console_runner_and_build_guards(tmp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "INBOX", tmp_path / "inbox")
    c = TestClient(webapp.create_app(root=tmp_db, exports=tmp_path / "e", runs=tmp_path / "runs", repo=tmp_path))
    s = c.get("/api/redteam/runner").json()
    assert s["state"] == "idle" and "red_team" in s["sets"] and s["verdicts"] == {} and s["breakthroughs"] == []
    assert c.post("/api/redteam/runner", json={"playbooks": "nope"}).status_code == 400
    assert c.post("/api/redteam/runner", json={"workers": 99}).status_code == 400
    r = c.post("/api/redteam/build", json={"source": "breakthroughs"})
    assert r.status_code == 400 and "no breakthroughs" in r.json()["detail"]


def test_missing_bedrock_key_is_said_plainly(tmp_db, tmp_path, monkeypatch):
    from blue_team import llm, pipeline
    monkeypatch.setattr(llm, "has_credentials", lambda: False)
    c = TestClient(webapp.create_app(root=tmp_db, exports=tmp_path / "e", runs=tmp_path / "runs", repo=tmp_path))
    a = c.get("/api/agents").json()
    assert a["key"] is False and "AWS_BEARER_TOKEN_BEDROCK" in a["help"]
    said = []
    assert pipeline.connect("auto", log=said.append) == (None, None)
    assert "AWS_BEARER_TOKEN_BEDROCK" in said[-1]
