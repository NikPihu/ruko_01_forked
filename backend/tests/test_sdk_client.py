"""RUKO as an SDK: the server knows which app and SDK version asked, and a phone verdict from an
on-device model the server was not trained with counts as unknown (rule 1)."""
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from api.main import create_app as create_engine
from features.build import ACCEPTED_DEVICE_VERSIONS
from intel_mock.app import create_app as create_mock
from tests.test_decide import NOW, req, users_in, world  # noqa: F401  (module fixture)

EXAMPLE = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "examples"
                      / "decide_request_device_verdict.json").read_text(encoding="utf-8"))


def _engine(world):  # noqa: F811
    mock = create_mock(world[0])
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock), base_url="http://mock")
    return TestClient(create_engine(world[0], intel_client=client, log_path=None, evidence_async=False))


def _verdict(version: str) -> dict:
    return {**EXAMPLE["context"]["device_verdict"], "model_version": version}


def test_the_app_and_sdk_version_are_recorded(world):  # noqa: F811
    engine = _engine(world)
    engine.post("/v1/decide", json=req(user=users_in(world)[3], rid="sdk-1"),
                headers={"X-Ruko-App": "com.ruko.demo", "X-Ruko-Sdk": "0.1.0"})
    engine.post("/v1/decide", json=req(user=users_in(world)[3], rid="sdk-2"))
    first = engine.app.state.store.details("sdk-1")
    second = engine.app.state.store.details("sdk-2")
    assert first["client"] == {"app": "com.ruko.demo", "sdk": "0.1.0"}
    assert second["client"] == {"app": None, "sdk": None}   # older apps send nothing; still recorded


def test_a_verdict_from_an_unknown_device_model_is_unknown(world):  # noqa: F811
    engine = _engine(world)
    known = sorted(ACCEPTED_DEVICE_VERSIONS)[0]
    for rid, version in (("dv-known", known), ("dv-old", "device-0.0-old-sdk")):
        engine.post("/v1/decide", json=req(user=users_in(world)[4], rid=rid,
                                           context={"lures": [], "device_verdict": _verdict(version)}))
    used = engine.app.state.store.details("dv-known")["features"]
    ignored = engine.app.state.store.details("dv-old")["features"]
    assert used["device_c"] == 0.99 and used["device_b"] == 0.97
    assert ignored["device_c"] is None and ignored["device_l"] is None and ignored["device_b"] is None
