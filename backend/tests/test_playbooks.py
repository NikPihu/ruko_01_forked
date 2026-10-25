"""Step 6: the playbooks file (data/playbooks/playbooks.yaml) and the built-in fallback agree."""
from __future__ import annotations

import itertools
import random
from pathlib import Path

import pytest
import yaml

from api import playbooks
from api.playbooks import BUILTIN, PlaybookError, load, parse
from api.rule_scorer import PLAYBOOK_RULES, PLAYBOOK_SOURCE, _playbook

FLAGS = ["on_call", "outgoing_to_unknown", "remote_control", "video_call", "story_mismatch",
         "session_dictated", "sideloaded_last_24h", "voip_call"]


def features(rng: random.Random) -> dict:
    f = {k: rng.choice([True, False, None]) for k in FLAGS}
    f["caller_unknown"] = rng.choice([True, False, None])
    f["entry_typed"] = rng.choice([True, False, None])
    f["episode_state"] = rng.choice([0, 1, 2, None])
    f["lure_tag"] = rng.choice([None, "kyc", "arrest_threat", "trading_tip", "task_job", "refund", "normal"])
    return f


def first(rules, f):
    return next((name for name, _, rule in rules if rule(f)), None)


def test_engine_uses_the_shipped_file():
    assert PLAYBOOK_SOURCE.startswith("file:")
    assert [(n, w) for n, w, _ in PLAYBOOK_RULES] == [(n, w) for n, w, _ in BUILTIN]


def test_file_and_builtin_name_the_same_playbook():
    rules, _ = load()
    rng = random.Random(7)
    for _ in range(5000):
        f = features(rng)
        assert first(rules, f) == first(BUILTIN, f), f


def test_every_rule_of_the_file_can_match():
    """Each playbook in the file names at least one feature set (no dead rule)."""
    rules, _ = load()
    rng = random.Random(11)
    seen = set()
    for _ in range(20000):
        f = features(rng)
        for i, (_, _, rule) in enumerate(rules):
            if rule(f):
                seen.add(i)
    assert seen == set(range(len(rules)))


def test_scorer_names_playbooks_from_the_file():
    f = {k: None for k in FLAGS} | {"caller_unknown": None, "entry_typed": False, "episode_state": 0, "lure_tag": None}
    assert _playbook(f) is None
    assert _playbook(f | {"on_call": True, "caller_unknown": True}) == "refund_qr"
    assert _playbook(f | {"on_call": True, "voip_call": True, "video_call": True}) == "digital_arrest"
    assert _playbook(f | {"episode_state": 2, "lure_tag": "kyc"}) == "task_job"


def test_a_missing_or_broken_file_falls_back_to_builtin(tmp_path: Path):
    assert load(tmp_path / "nope.yaml") == (BUILTIN, "builtin")
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: x\nplaybooks:\n  - name: refund_qr\n    why: typo\n    match: {on_cal: true}\n", encoding="utf-8")
    assert load(bad) == (BUILTIN, "builtin")
    bad.write_text("not: [valid", encoding="utf-8")
    assert load(bad) == (BUILTIN, "builtin")


@pytest.mark.parametrize("doc, error", [
    ({"playbooks": []}, "non-empty"),
    ({"playbooks": [{"name": "Bad Name", "why": "x", "match": {"on_call": True}}]}, "snake_case"),
    ({"playbooks": [{"name": "a", "match": {"on_call": True}}]}, "'why'"),
    ({"playbooks": [{"name": "a", "why": "x", "match": {}}]}, "at least one"),
    ({"playbooks": [{"name": "a", "why": "x", "match": {"on_cal": True}}]}, "unknown feature"),
    ({"playbooks": [{"name": "a", "why": "x", "match": {"any": []}}]}, "'any'"),
    ({"playbooks": [{"name": "a", "why": "x", "match": {"on_call": True}, "extra": 1}]}, "unknown keys"),
])
def test_bad_files_are_refused(doc, error):
    with pytest.raises(PlaybookError, match=error):
        parse(doc)


def test_a_new_playbook_is_picked_up_without_code(tmp_path: Path):
    doc = yaml.safe_load(playbooks.PATH.read_text(encoding="utf-8"))
    doc["playbooks"].insert(0, {"name": "electricity_disconnection", "why": "a bill threat + screen control",
                                "match": {"lure_tag": ["kyc", "refund"], "remote_control": True}})
    path = tmp_path / "playbooks.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    rules, source = load(path)
    assert source == "file:playbooks-0.3"
    f = {k: None for k in FLAGS} | {"caller_unknown": None, "entry_typed": True, "episode_state": 0}
    assert first(rules, f | {"lure_tag": "refund", "remote_control": True}) == "electricity_disconnection"
    assert first(rules, f | {"lure_tag": "kyc", "sideloaded_last_24h": True}) == "fake_kyc_apk"


def test_an_emerging_pattern_draft_is_a_valid_playbook():
    """Naming an emerging pattern (console) drafts an entry the loader accepts as is."""
    from patterns.emerging import draft_playbook

    pattern = {"pattern_id": "pat_x", "people": 9, "payments": 12, "first_seen": "2026-10-20T10:00:00+05:30",
               "description": "unknown video call → screen control → a new payee",
               "signature": {"families": ["C", "P"], "call": "video call from an unknown caller", "lure": None,
                             "control": "screen control", "pay_screen": ["amount dictated"], "entry": "typed",
                             "new_payee": True, "amount": "₹20k–50k"}}
    text = draft_playbook(pattern, "fake_officer_video")
    rules = parse({"playbooks": yaml.safe_load(text)})
    f = {k: None for k in FLAGS} | {"on_call": True, "video_call": True, "caller_unknown": True, "remote_control": True,
                                    "session_dictated": True, "entry_typed": True, "episode_state": 0, "lure_tag": None}
    assert first(rules, f) == "fake_officer_video"
