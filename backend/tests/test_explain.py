"""The explainable layer: the user sees a few reasons in words; the analyst sees everything."""
import httpx
import pytest
from fastapi.testclient import TestClient

import api.main
from api.main import create_app as create_engine
from api.rule_scorer import PLAYBOOK_RULES, _playbook
from test_decide import (DEMO_KIRANA_UPI, MEENA_CONTEXT, mock, pump, req, users_in, world)  # noqa: F401


@pytest.fixture()
def engine(world, mock, monkeypatch):
    monkeypatch.setattr(api.main, "DEADLINE_S", 10.0)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock[0]), base_url="http://mock")
    return TestClient(create_engine(world[0], intel_client=client, intel_cache_ttl_s=0, log_path=None,
                                    evidence_async=False, intel_budget_s=5.0))


def test_meena_explanation_has_everything_for_the_analyst(engine, mock, world):
    pump(mock[1], world)
    r = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government", rid="p_m")).json()
    x = engine.get("/v1/payments/p_m/explain").json()
    # What the user saw is exactly the decide answer, at most 3 reasons, no score.
    assert x["user_view"]["tier"] == r["tier"] and x["user_view"]["reasons"] == r["reasons"][:3]
    # The analyst sees the scores...
    assert 0 < x["scores"]["p_scam"] <= 1 and set(x["scores"]["families"]) == {"C", "L", "P", "B"}
    assert len(x["scores"]["lit_families"]) >= 2
    # ...every reason traced to its inputs and its strength...
    by = {rs["code"]: rs for rs in x["reasons"]}
    assert by["R2_remote_control"]["inputs"]["remote_control"] is True
    assert by["R2_remote_control"]["band"] == "large" and by["R2_remote_control"]["family"] == "C"
    assert all(rs["shown_to_user"] == (rs["code"] in r["reasons"][:3]) for rs in x["reasons"])
    # ...every playbook checked, exactly one chosen, and it is the decided one.
    assert len(x["playbooks"]) == len(PLAYBOOK_RULES)
    chosen = [p for p in x["playbooks"] if p["chosen"]]
    assert len(chosen) == 1 and chosen[0]["playbook"] == r["playbook"] == "digital_arrest"
    assert x["sources"]["payee_registry"] in ("ok", "not_found") or x["sources"]["payee_registry"]


def test_quiet_payment_explains_why_nothing_happened(engine, world):
    user = users_in(world)[0]
    engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid="p_k"))
    x = engine.get("/v1/payments/p_k/explain").json()
    assert x["user_view"]["tier"] == "T0" and x["user_view"]["reasons"] == []
    assert not any(p["chosen"] for p in x["playbooks"])
    assert len(x["scores"]["lit_families"]) < 2


def test_unknown_payment_is_404(engine):
    assert engine.get("/v1/payments/nope/explain").status_code == 404


def test_playbook_rules_keep_the_old_order():
    """The rules moved into a named list; the first match still wins, as before."""
    base = {k: None for k in ("episode_state", "sideloaded_last_24h", "lure_tag", "outgoing_to_unknown",
                              "remote_control", "session_dictated", "on_call", "caller_unknown", "story_mismatch",
                              "entry_typed")}
    assert _playbook({**base, "episode_state": 2, "lure_tag": "arrest_threat"}) == "task_job"
    assert _playbook({**base, "lure_tag": "arrest_threat"}) == "digital_arrest"
    assert _playbook({**base, "on_call": True, "caller_unknown": True, "entry_typed": False}) == "refund_qr"
    assert _playbook({**base, "entry_typed": True}) is None


def test_summary_says_why_in_words_with_real_values(engine, mock, world):
    """The console's "Why this decision": lit families first, each with its inputs in words and values."""
    pump(mock[1], world)
    r = engine.post("/v1/decide", json=req(context=MEENA_CONTEXT, says="government", rid="p_s")).json()
    sm = engine.get("/v1/payments/p_s/explain").json()["summary"]
    lit = [fam for fam in sm["families"] if fam["lit"]]
    assert sm["headline"].endswith(f"{len(lit)} of 4 kinds of evidence were lit (2 needed).")
    assert [fam["lit"] for fam in sm["families"]] == sorted((fam["lit"] for fam in sm["families"]), reverse=True)
    context = next(fam for fam in sm["families"] if fam["family"] == "C")
    assert "a screen-sharing or remote-control app is active" in context["facts"]
    behaviour = next(fam for fam in sm["families"] if fam["family"] == "B")
    assert any(fact.startswith("amount ₹") for fact in behaviour["facts"])
    assert sm["how"] and sm["how"][0].startswith(f"{r['tier']} needs a scam score of at least")
    assert sm["scam_type"] == "digital_arrest"


def test_quiet_summary_says_nothing_happened(engine, world):
    user = users_in(world)[0]
    engine.post("/v1/decide", json=req(user=user, payee=DEMO_KIRANA_UPI, amount=180, entry="qr", rid="p_q"))
    sm = engine.get("/v1/payments/p_q/explain").json()["summary"]
    assert sm["headline"].startswith("No interruption: only")
    # Unknown or false inputs are never listed as facts (rule 1: unknown is not shown as safe or risky).
    assert all("= None" not in fact and "= False" not in fact for fam in sm["families"] for fact in fam["facts"])
