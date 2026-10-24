"""Write the C2 decide contract as JSON Schema for the app and anyone else who mirrors it.

    PYTHONPATH=backend:ml:data python -m schema.export
    # writes contracts/c2_decide.schema.json, c2_episode.schema.json and c2_payment_outcome.schema.json

backend/tests/test_schema.py fails when the committed file is out of date with events.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from schema.events import (CONTRACT_VERSION, DecideRequest, DecideResponse, EpisodeEvent, EpisodeEventResponse,
                           Feedback, FeedbackResponse, MoneyReceived, MoneyReceivedResponse, MyPayments, PaymentOutcome,
                           PaymentOutcomeResponse, WatchEvent, WatchEventResponse)

OUT = Path(__file__).resolve().parents[2] / "contracts" / "c2_decide.schema.json"
OUT_EPISODE = OUT.with_name("c2_episode.schema.json")
OUT_OUTCOME = OUT.with_name("c2_payment_outcome.schema.json")
OUT_APP = OUT.with_name("c2_app_events.schema.json")


def build_schema() -> dict:
    return {
        "title": "RUKO C2: POST /v1/decide",
        "contract_version": CONTRACT_VERSION,
        "request": DecideRequest.model_json_schema(),
        "response": DecideResponse.model_json_schema(),
    }


def build_episode_schema() -> dict:
    return {
        "title": "RUKO C2: POST /v1/episode",
        "contract_version": CONTRACT_VERSION,
        "request": EpisodeEvent.model_json_schema(),
        "response": EpisodeEventResponse.model_json_schema(),
    }


def build_outcome_schema() -> dict:
    return {
        "title": "RUKO C2: POST /v1/payment/outcome",
        "contract_version": CONTRACT_VERSION,
        "request": PaymentOutcome.model_json_schema(),
        "response": PaymentOutcomeResponse.model_json_schema(),
    }


def build_app_schema() -> dict:
    """c2-0.9: alert feedback, watch events and the app's own payment list; c2-0.11: money received."""
    return {
        "title": "RUKO C2: POST /v1/feedback, POST /v1/watch, GET /v1/me/payments, POST /v1/payment/received",
        "contract_version": CONTRACT_VERSION,
        "feedback": {"request": Feedback.model_json_schema(), "response": FeedbackResponse.model_json_schema()},
        "watch": {"request": WatchEvent.model_json_schema(), "response": WatchEventResponse.model_json_schema()},
        "me_payments": {"response": MyPayments.model_json_schema()},
        "money_received": {"request": MoneyReceived.model_json_schema(),
                           "response": MoneyReceivedResponse.model_json_schema()},
    }


def render_app() -> str:
    return json.dumps(build_app_schema(), indent=2, ensure_ascii=False) + "\n"


def render() -> str:
    return json.dumps(build_schema(), indent=2, ensure_ascii=False) + "\n"


def render_episode() -> str:
    return json.dumps(build_episode_schema(), indent=2, ensure_ascii=False) + "\n"


def render_outcome() -> str:
    return json.dumps(build_outcome_schema(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    OUT_EPISODE.write_text(render_episode(), encoding="utf-8", newline="\n")
    OUT_OUTCOME.write_text(render_outcome(), encoding="utf-8", newline="\n")
    OUT_APP.write_text(render_app(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}, {OUT_EPISODE.name}, {OUT_OUTCOME.name} and {OUT_APP.name}")


if __name__ == "__main__":
    main()
