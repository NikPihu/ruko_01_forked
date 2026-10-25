"""Playbook search (playbooks-0.3, api/playbook_search.py): known scams written in steps, matched on a
payment's steps with unknown counting half and a required step that was not seen ruling a scam out."""
from __future__ import annotations

import pytest
import yaml

from api import playbook_search as ps
from features import steps


def pbs(doc: str) -> list[ps.Playbook]:
    return ps.parse(yaml.safe_load(doc))


TWO = """
search:
  - name: arrest
    steps:
      - {step: video_call, weight: 2, required: true}
      - {step: new_payee}
  - name: refund
    steps:
      - {any: [qr_entry, contact_entry], weight: 2, required: true}
      - {step: new_payee}
"""


def test_the_file_parses_names_real_steps_and_covers_the_known_scams():
    assert ps.SOURCE == "file:playbooks-0.3"
    names = {pb.name for pb in ps.PLAYBOOKS}
    assert names == {"task_job", "fake_kyc_apk", "fake_customer_care", "digital_arrest", "trading_group", "refund_qr"}
    for pb in ps.PLAYBOOKS:
        assert {s for it in pb.items for s in it.steps} <= set(steps.STEP_IDS)


def test_unknown_steps_and_rules_without_a_required_step_are_refused():
    with pytest.raises(ps.SearchError, match="unknown steps"):
        pbs("search: [{name: x, steps: [{step: video_cal, required: true}]}]")
    with pytest.raises(ps.SearchError, match="required"):
        pbs("search: [{name: x, steps: [{step: video_call}]}]")
    with pytest.raises(ps.SearchError, match="unknown keys"):
        pbs("search: [{name: x, match: {}, steps: [{step: video_call, required: true}]}]")


def test_a_broken_search_section_turns_the_search_off_not_the_engine(tmp_path):
    bad = tmp_path / "playbooks.yaml"
    bad.write_text("version: x\nsearch: [{name: x, steps: [{step: nope, required: true}]}]\n", encoding="utf-8")
    assert ps.load(bad) == ([], "none")


def test_rare_steps_weigh_more_than_shared_ones():
    a = pbs(TWO)[0]
    video, payee = a.items
    assert video.idf > payee.idf                     # new_payee is in both playbooks


def test_a_required_step_measured_and_not_seen_rules_the_scam_out():
    a, _ = pbs(TWO)
    r = ps.score(a, {"video_call": False, "new_payee": True})
    assert r["similarity"] == 0 and r["blocked_by"] == "video_call"


def test_a_new_payee_alone_matches_nothing():
    assert ps.search({"new_payee": True}, pbs(TWO)) == []


def test_unknown_counts_half_never_as_seen_or_absent():
    a, _ = pbs(TWO)
    full = ps.score(a, {"video_call": True, "new_payee": True})["similarity"]
    unknown = ps.score(a, {"video_call": True, "new_payee": None})
    absent = ps.score(a, {"video_call": True, "new_payee": False})["similarity"]
    assert full == 1.0 and absent < unknown["similarity"] < full
    assert unknown["unmeasured"] == ["new_payee"]


def test_any_is_seen_by_one_option_and_absent_only_when_all_were_measured():
    _, b = pbs(TWO)
    item = b.items[0]
    assert item.reading({"qr_entry": False, "contact_entry": True}) is True
    assert item.reading({"qr_entry": False, "contact_entry": None}) is None
    assert item.reading({"qr_entry": False, "contact_entry": False}) is False


def test_search_ranks_and_explains():
    out = ps.search({"video_call": True, "new_payee": True, "qr_entry": True}, pbs(TWO))
    assert [r["name"] for r in out] == ["arrest", "refund"]
    assert out[0]["matched"] == ["video_call", "new_payee"] and out[0]["missing"] == []
    assert out[1]["matched"] == ["any(qr_entry, contact_entry)", "new_payee"]


def test_the_known_scams_are_found_from_their_steps():
    arrest = {"unknown_call": True, "video_call": True, "long_call": True, "amount_large": True, "new_payee": True,
              "lure:arrest_threat": None}
    assert ps.search(arrest, ps.PLAYBOOKS)[0]["name"] == "digital_arrest"
    care = {"call_out_to_unknown": True, "remote_control": True, "unknown_call": False, "new_payee": True}
    assert ps.search(care, ps.PLAYBOOKS)[0]["name"] == "fake_customer_care"
    task = {"episode_active": True, "bait_credit": True, "escalating_payments": True, "new_payee": True}
    assert ps.search(task, ps.PLAYBOOKS)[0]["name"] == "task_job"
    refund = {"unknown_call": True, "qr_entry": True, "amount_small": True, "lure:arrest_threat": False,
              "video_call": False, "remote_control": False, "dictated_amount": False}
    assert ps.search(refund, ps.PLAYBOOKS)[0]["name"] == "refund_qr"


def test_an_ordinary_payment_matches_no_scam():
    quiet = {s: False for s in steps.STEP_IDS} | {"typed_entry": True, "amount_small": True}
    assert ps.search(quiet, ps.PLAYBOOKS) == []
