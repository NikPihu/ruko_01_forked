"""The published C2 contract (contracts/) must match schema/events.py exactly."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from schema.events import (CONTRACT_VERSION, DecideRequest, DecideResponse, EpisodeEvent, EpisodeEventResponse,
                           PaymentOutcome, PaymentOutcomeResponse)
from schema.export import OUT, OUT_EPISODE, OUT_OUTCOME, render, render_episode, render_outcome

EXAMPLES = Path(__file__).resolve().parents[2] / "contracts" / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_committed_schema_is_current():
    # Fails after any change to events.py until `python -m schema.export` is re-run and committed.
    assert OUT.read_text(encoding="utf-8") == render()
    assert OUT_EPISODE.read_text(encoding="utf-8") == render_episode()
    assert OUT_OUTCOME.read_text(encoding="utf-8") == render_outcome()


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("payment_outcome_*.json")
                                        if "response" not in p.name))
def test_payment_outcome_examples_validate(name):
    o = PaymentOutcome.model_validate(load(name))
    # The payment id is the id of a published decide request.
    assert any(load(r.name)["request_id"] == o.request_id for r in EXAMPLES.glob("decide_request_*.json"))


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("payment_outcome_response_*.json")))
def test_payment_outcome_response_examples_validate(name):
    assert PaymentOutcomeResponse.model_validate(load(name)).contract_version == CONTRACT_VERSION


def test_payment_outcome_only_completed_or_cancelled():
    with pytest.raises(ValidationError):
        PaymentOutcome.model_validate({**load("payment_outcome_completed.json"), "status": "pending"})


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("episode_event_*.json")
                                        if "response" not in p.name))
def test_episode_event_examples_validate(name):
    EpisodeEvent.model_validate(load(name))


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("episode_event_response_*.json")))
def test_episode_response_examples_validate(name):
    r = EpisodeEventResponse.model_validate(load(name))
    assert r.contract_version == CONTRACT_VERSION


def test_episode_event_caps_accounts_at_ten():
    body = load("episode_event_active.json")
    body["accounts"] = body["accounts"] * 2
    with pytest.raises(ValidationError):
        EpisodeEvent.model_validate(body)


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("decide_request_*.json")))
def test_request_examples_validate(name):
    DecideRequest.model_validate(load(name))


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("decide_response_*.json")))
def test_response_examples_validate(name):
    r = DecideResponse.model_validate(load(name))
    assert r.contract_version == CONTRACT_VERSION
    assert "p_scam" not in load(name)  # the user never sees a score


def test_unknown_fields_are_rejected():
    body = {**load("decide_request_minimal.json"), "payee_vpa_hash": "abc"}
    with pytest.raises(ValidationError):
        DecideRequest.model_validate(body)


def test_missing_context_means_unknown_not_safe():
    req = DecideRequest.model_validate(load("decide_request_meena.json"))
    assert req.context.device.untrusted_accessibility is None
    assert req.context.device.sideloaded_last_24h is None
