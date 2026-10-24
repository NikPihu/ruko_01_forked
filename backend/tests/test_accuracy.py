"""The Accuracy page: held-out numbers with false alarms, misses and named failure cases."""
import json

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from evalsuite import accuracy
from test_decide import world  # noqa: F401


def test_message_numbers_come_from_the_held_out_templates():
    m = accuracy.messages()
    held = json.loads(accuracy.LURE_METRICS.read_text(encoding="utf-8"))["held_out_templates"]
    assert m["scam_caught"] == round(held["scam_caught"], 4)
    assert m["normal_false_alarm"] == round(held["normal_false_alarm"], 4)    # false alarms shown, not hidden
    assert {"en", "hi", "hinglish"} <= set(m["by_language"])


def test_new_scams_come_from_the_red_team_manifest():
    n = accuracy.new_scams()
    assert n["playbooks"] == 50 and n["scam_payments"] > 0 and 0 <= n["missed"] <= 1
    assert len(n["examples"]) == 5


def test_committed_results_have_a_confusion_table_and_named_failures():
    if not accuracy.OUT.exists():
        pytest.skip("run python -m evalsuite.accuracy")
    res = json.loads(accuracy.OUT.read_text(encoding="utf-8"))
    live = res["payments"]["scorers"][res["payments"]["live_scorer"]]
    c = live["confusion"]
    assert c["scam_interrupted"] + c["scam_missed"] == res["payments"]["scam_payments"]
    assert "false_alarms_per_1000" in live and live["missed_by_type"] is not None
    names = [f["name"] for f in res["failure_cases"]]
    assert len(names) >= 3 and all(f["measured"] and f["fix"] for f in res["failure_cases"])


def test_endpoint_serves_the_file(world):
    app = create_app(world[0], log_path=None)
    r = TestClient(app).get("/v1/accuracy")
    assert r.status_code == (200 if accuracy.OUT.exists() else 404)
