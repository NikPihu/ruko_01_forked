"""Write the C2 decide contract as JSON Schema for the app and anyone else who mirrors it.

    PYTHONPATH=backend:ml:data python -m schema.export
    # writes contracts/c2_decide.schema.json, c2_episode.schema.json and c2_payment_outcome.schema.json

backend/tests/test_schema.py fails when the committed file is out of date with events.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from schema.events import (CONTRACT_VERSION, DecideRequest, DecideResponse, EpisodeEvent, EpisodeEventResponse,
                           PaymentOutcome, PaymentOutcomeResponse)

OUT = Path(__file__).resolve().parents[2] / "contracts" / "c2_decide.schema.json"
OUT_EPISODE = OUT.with_name("c2_episode.schema.json")
OUT_OUTCOME = OUT.with_name("c2_payment_outcome.schema.json")


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
    print(f"wrote {OUT}, {OUT_EPISODE.name} and {OUT_OUTCOME.name}")


if __name__ == "__main__":
    main()
