"""What the runner must keep doing.

    PYTHONPATH=backend;ml;data;synthetic_playbook python -m pytest synthetic_playbook/interface_script/tests -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from interface_script import scenario
from interface_script.judge import Verdict
from interface_script.run import run

SMALL = {"judge": {"normal_max_score": 70, "breakthrough_share": 0.75},
         "world": {"users": 120, "days": 10, "seed": 7, "warmup_days": 4},
         "scenario": {"victims": 6, "victims_mode": "comply", "normal_sample": 0.1},
         "server": {"target": "local", "timeout_s": 20, "scorer": "ml"}}


def test_library_playbooks_load():
    names = sorted(p.stem for p in scenario.LIBRARY.glob("*.yaml"))
    assert len(names) >= 12
    for n in names:
        name, pb = scenario.load_playbook(n)
        assert name == n and pb["steps"]


def test_playbook_from_a_path(tmp_path):
    src = scenario.LIBRARY / "refund_qr.yaml"
    dst = tmp_path / "mine.yaml"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    name, pb = scenario.load_playbook(dst)
    assert name == "mine" and pb["steps"]


def test_rejects_a_file_that_is_not_a_playbook(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"hello": 1}), encoding="utf-8")
    with pytest.raises(SystemExit):
        scenario.load_playbook(bad)


def test_victim_rate_scales_with_the_window():
    # 60-day rate: 10 of 100 users in 60 days is 0.1; the same 10 inside 30 days needs twice that.
    assert scenario._victim_rate(10, 100, 60) == pytest.approx(0.10)
    assert scenario._victim_rate(10, 100, 30) == pytest.approx(0.20)


def test_judge_counts_and_breakthrough():
    v = Verdict("p", "lgbm-0.2", normal_max_score=70, breakthrough_share=0.75)
    label = lambda scam, jid: {"judge": True, "is_scam": scam, "journey_id": jid, "tx_id": "t",
                               "user_id": "u", "payee_upi": "a@b", "amount_inr": 1.0, "ts": "",
                               "flow": "scam" if scam else "normal", "playbook": "p", "stage": None,
                               "journey_pay_index": 0, "device_level": None, "device_class": None}
    reply = lambda score: {"tier": "T0", "reasons": [], "threat": {"score": score, "level": "none"}}
    for _ in range(8):                      # called normal
        v.add(label(True, "j1"), reply(10), 200)
    for _ in range(2):                      # caught
        v.add(label(True, "j2"), reply(90), 200)
    v.add(label(False, None), reply(95), 200)   # a false alarm
    assert v.scam_judged == 10 and v.scam_missed == 8 and v.scam_caught == 2
    assert v.miss_rate == pytest.approx(0.8) and v.breakthrough          # 0.8 >= 0.75
    assert v.journeys_fully_missed == 1 and v.false_alarm_rate == pytest.approx(1.0)


def test_fail_open_is_not_counted_as_missed():
    """Rule 3: no score means the check never ran, so it is neither caught nor missed."""
    v = Verdict("p", "x", 70, 0.75)
    label = {"judge": True, "is_scam": True, "journey_id": "j", "tx_id": "t", "user_id": "u",
             "payee_upi": "a@b", "amount_inr": 1.0, "ts": "", "flow": "scam", "playbook": "p",
             "stage": None, "journey_pay_index": 0, "device_level": None, "device_class": None}
    row = v.add(label, {"tier": "T0", "fail_open": True, "threat": None}, 200)
    assert v.fail_open == 1 and v.errors == 0
    assert v.scam_judged == 0 and v.scam_missed == 0 and row["fail_open"] is True
    assert not v.breakthrough


def test_warmup_payments_are_not_judged():
    v = Verdict("p", "x", 70, 0.75)
    label = {"judge": False, "is_scam": True, "journey_id": "j", "tx_id": "t", "user_id": "u",
             "payee_upi": "a@b", "amount_inr": 1.0, "ts": "", "flow": "scam", "playbook": "p",
             "stage": None, "journey_pay_index": 0, "device_level": None, "device_class": None}
    v.add(label, {"tier": "T0", "threat": {"score": 5}}, 200)
    assert v.scam_judged == 0


@pytest.mark.slow
def test_end_to_end_writes_every_file(tmp_path):
    out = tmp_path / "run"
    v = run("refund_qr", SMALL, out, log=lambda *_: None)
    for f in ("summary.txt", "verdict.json", "results.csv", "requests.jsonl", "responses.jsonl",
              "playbook.yaml"):
        assert (out / f).exists(), f
    saved = json.loads((out / "verdict.json").read_text())
    assert saved["playbook"] == "refund_qr" and saved["scorer"]
    assert v.scam_judged + v.fail_open > 0, "the playbook produced no judged scam payment"
    assert (out / "handoff").exists() == v.breakthrough


@pytest.mark.slow
def test_sim_v2_config_is_never_edited():
    before = {p: p.read_bytes() for p in scenario.SIM_V2_CONFIG.rglob("*") if p.is_file()}
    scenario.build("refund_qr", SMALL, log=lambda *_: None)
    assert {p: p.read_bytes() for p in scenario.SIM_V2_CONFIG.rglob("*") if p.is_file()} == before


def test_run_all_finds_every_playbook_in_a_folder(tmp_path):
    """Adding a playbook = dropping a YAML into the folder: no list to update."""
    from interface_script.__main__ import discover
    src = (scenario.LIBRARY / "refund_qr.yaml").read_text(encoding="utf-8")
    for name in ("b_second.yaml", "a_first.yml", "c_third.yaml"):
        (tmp_path / name).write_text(src, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a playbook", encoding="utf-8")
    found = discover(tmp_path)
    assert [p.name for p in found] == ["a_first.yml", "b_second.yaml", "c_third.yaml"]
    for p in found:
        name, pb = scenario.load_playbook(p)
        assert name == p.stem and pb["steps"]


def test_run_all_rejects_an_empty_folder(tmp_path):
    from interface_script.__main__ import discover
    with pytest.raises(SystemExit):
        discover(tmp_path)
