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


# ---------- c2-0.8: alert feedback, watch events, the app's own payments ----------

def test_app_events_schema_is_current():
    from schema.export import OUT_APP, render_app
    assert OUT_APP.read_text(encoding="utf-8") == render_app()


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("feedback_*.json") if "response" not in p.name))
def test_feedback_examples_validate(name):
    from schema.events import Feedback
    f = Feedback.model_validate(load(name))
    assert any(load(r.name)["request_id"] == f.request_id for r in EXAMPLES.glob("decide_request_*.json"))
    assert (f.why is not None) == (f.action == "i_know_them")


def test_feedback_response_example_validates():
    from schema.events import FeedbackResponse
    assert FeedbackResponse.model_validate(load("feedback_response_not_accepted.json")).contract_version == CONTRACT_VERSION


@pytest.mark.parametrize("name", sorted(p.name for p in EXAMPLES.glob("watch_event_*.json") if "response" not in p.name))
def test_watch_examples_validate(name):
    from schema.events import WatchEvent
    WatchEvent.model_validate(load(name))


def test_watch_response_and_my_payments_validate():
    from schema.events import MyPayments, WatchEventResponse
    assert WatchEventResponse.model_validate(load("watch_event_response.json")).contract_version == CONTRACT_VERSION
    mp = MyPayments.model_validate(load("me_payments.json"))
    assert "p_scam" not in json.dumps(load("me_payments.json"))   # rule 4: never a score for the user
    assert mp.payments[0].status == "cancelled"


def test_money_received_examples_validate():
    from schema.events import MoneyReceived, MoneyReceivedResponse
    m = MoneyReceived.model_validate(load("money_received.json"))
    r = MoneyReceivedResponse.model_validate(load("money_received_response.json"))
    assert r.event_id == m.event_id and r.contract_version == CONTRACT_VERSION


def test_watch_event_never_carries_text():
    from schema.events import WatchEvent
    with pytest.raises(ValidationError):
        WatchEvent.model_validate({**load("watch_event_lure.json"), "text": "Your account is under arrest"})


def test_campaign_handles_and_r13_validate():
    """c2-0.13: money handles on lure_seen (UPI plain, link/number pseudonyms) and reason R13."""
    from schema.events import DecideResponse, WatchEvent
    w = WatchEvent.model_validate(load("watch_event_lure_handles.json"))
    kinds = {h.kind: h.value for h in w.handles}
    assert kinds["upi"].endswith("@ybl") and kinds["link"].startswith("sha256:") and kinds["phone"].startswith("sha256:")
    assert "R13_scam_campaign" in DecideResponse.model_validate(load("decide_response_t2_campaign.json")).reasons
    # At most 10 handles; never an unknown kind; never the text inside a handle object.
    with pytest.raises(ValidationError):
        WatchEvent.model_validate({**load("watch_event_lure_handles.json"), "handles": [{"kind": "upi", "value": "a.b@ybl"}] * 11})
    with pytest.raises(ValidationError):
        WatchEvent.model_validate({**load("watch_event_lure_handles.json"), "handles": [{"kind": "email", "value": "x@y.z"}]})
    with pytest.raises(ValidationError):
        WatchEvent.model_validate({**load("watch_event_lure_handles.json"),
                                   "handles": [{"kind": "upi", "value": "a.b@ybl", "text": "pay now"}]})


def test_ai_written_lure_check_runs_and_has_no_false_alarms():
    """A3: the lure model on AI-written scam messages, scored the way the phone scores."""
    pytest.importorskip("sklearn")
    from evalsuite.ai_lures import run
    r = run()
    assert r["scam_messages"] >= 20 and r["honest_messages"] >= 10
    assert r["caught"] >= 0.8 and r["false_alarms"] <= 0.1
