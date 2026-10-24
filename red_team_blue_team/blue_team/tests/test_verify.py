import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml
from fastapi.testclient import TestClient

from blue_team import engine_file, verify, webapp
from bt_helpers import features

REPO = Path(__file__).resolve().parents[3]


def card(name="qr_stranger_small", rule=None, misnamed_as=None, prio=100):
    rule = rule or {"all": [{"feature": "payee_pass_through_24h", "op": "is", "value": True},
                            {"feature": "first_time_payee", "op": "is", "value": True}]}
    return {"name": name, "title": "QR payment to a pass-through stranger", "misnamed_as": misnamed_as,
            "match": [{"priority": prio, "rule": rule}], "approved_by": ["a", "b"]}


def test_candidate_file_is_the_engine_file_plus_the_entry_where_promote_puts_it(tmp_path):
    from api.playbooks import parse
    path, problems = verify.candidate_file(card(), tmp_path)
    assert problems == []
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    names = [p["name"] for p in doc["playbooks"]]
    assert names[-1] == "qr_stranger_small" and names[:-1] == [n for n, *_ in engine_file.known()]
    assert len(parse(doc)) == len(names)                     # the engine's own parser takes it
    path, _ = verify.candidate_file(card("arrest_fix", misnamed_as="digital_arrest"), tmp_path)
    names = [p["name"] for p in yaml.safe_load(path.read_text(encoding="utf-8"))["playbooks"]]
    assert names.index("arrest_fix") == names.index("digital_arrest") - 1


def test_a_rule_the_file_cannot_express_is_still_measured_and_flagged(tmp_path):
    c = card(rule={"all": [{"feature": "entry_method", "op": "eq", "value": "qr"},
                           {"feature": "amount_inr", "op": "<", "value": 1000}]})
    path, problems = verify.candidate_file(c, tmp_path)
    assert path is None and len(problems) == 2
    name = verify.namer(c, None)
    assert name(features(entry_method="qr", amount_inr=400.0)) == "qr_stranger_small"
    assert name(features(entry_method="qr", amount_inr=4000.0)) is None
    assert name(features(lure_tag="arrest_threat")) == "digital_arrest"      # known ones still come first


def write_run(d: Path, rows: list[dict], fail_open=0, miss=0.9, named=None):
    d.mkdir(parents=True)
    rows = [{**r, "tx_id": f"t_{i}"} for i, r in enumerate(rows)]
    pd.DataFrame(rows).to_csv(d / "results.csv", index=False)
    (d / "verdict.json").write_text(json.dumps({"miss_rate": miss, "false_alarm_rate": 0.01, "fail_open": fail_open,
                                                "errors": 0, "breakthrough": miss >= 0.75}), encoding="utf-8")
    names = named or [None] * len(rows)
    (d / "named.jsonl").write_text("".join(json.dumps({"request_id": r["tx_id"], "named": names[i]}) + "\n"
                                           for i, r in enumerate(rows)), encoding="utf-8")


def test_live_results_and_the_contract_block_are_reported(tmp_path):
    scam = lambda ft, tier: {"judged": True, "is_scam": True, "status": 200, "fraud_type": ft, "tier": tier}
    n = "qr_stranger_small"
    write_run(tmp_path / "before", [scam(None, "T0")] * 9 + [scam(None, "T2")])
    write_run(tmp_path / "file", [scam(None, "T0")] * 10, fail_open=6, named=[n] * 10)
    # the engine names all ten inside, but shows a name only at T1+ (here 2 of 10)
    write_run(tmp_path / "preview", [scam(None, "T0")] * 8 + [scam(n, "T2")] * 2, miss=0.8, named=[n] * 10)
    s = {k: verify._summarise(tmp_path / k, n) for k in ("before", "file", "preview")}
    assert s["preview"]["named"] == 1.0 and s["preview"]["named_shown"] == 0.2
    assert s["preview"]["interrupted"] == 0.2 and s["before"]["interrupted"] == 0.1 and s["before"]["named"] == 0.0
    lines = verify.verdict({"live": {"x": {"before": s["before"], "engine_file": s["file"], "preview": s["preview"]}}})
    assert any("BLOCKED" in x and "FraudType" in x for x in lines)
    assert any("preview: named 100% inside the engine, 20% shown" in x and "10% -> 20%" in x for x in lines)


def test_the_preview_opens_the_contract_only_inside_its_own_process():
    code = ("from blue_team import verify_engine; from schema.events import Threat; verify_engine._open_contract(); "
            "print(Threat(score=50, level='medium', fraud_type='qr_stranger_small', families=['P']).fraud_type)")
    env = {"PYTHONPATH": ";".join(str(REPO / p) for p in ("backend", "ml", "data", "synthetic_playbook", "red_team_blue_team")),
           "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=REPO)
    assert out.stdout.strip() == "qr_stranger_small", out.stderr[-500:]
    from schema.events import FraudType, Threat
    import typing
    assert Threat.model_fields["fraud_type"].annotation == typing.Optional[FraudType]   # this process untouched


def test_console_verifies_only_approved_cards(tmp_db, tmp_path):
    from blue_team import playbook_db
    playbook_db.write({**card(), "status": "review", "reviews": [], "evidence": {}}, "review", tmp_db)
    c = TestClient(webapp.create_app(root=tmp_db, exports=tmp_path / "e", runs=tmp_path / "runs", repo=tmp_path))
    r = c.post("/api/cards/qr_stranger_small/verify", json={})
    assert r.status_code == 400 and "only approved" in r.json()["detail"]
    s = c.get("/api/cards/qr_stranger_small/verify").json()
    assert s["state"] == "idle" and s["result"] is None and not s["running"]
    assert c.get("/api/cards/nope/verify").status_code == 404
