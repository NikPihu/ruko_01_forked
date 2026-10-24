"""Talking to the RUKO server.

Two ways in, same methods, so a run can be checked either way:
    local  - the real engine started inside this process (no server to run; used by the tests)
    <url>  - a server already running (scripts\\dev.ps1), reached over HTTP

The server is never changed from here: we only post what a phone posts and read the reply.
"""
from __future__ import annotations

from pathlib import Path


class Server:
    """post(path, body) -> (status_code, reply dict); clock(ts) moves the mock services' clock."""

    def __init__(self, client, label: str, close=None, clock=None):
        self._c, self.label, self._close, self._clock = client, label, close, clock

    def clock(self, ts: str) -> None:
        """The mock bank, NPCI and registry answer as of their clock and hide anything later, as the
        real ones do at payment time. It starts at the world's last day, so a run that does not move it
        asks about every payee as of the end of the world (wrong account age, payers, MuleHunter,
        pass-through, even registry listings from the future). The replay that builds the training
        tables moves it the same way (ml/tests/test_replay_parity.py). No-op for a server over HTTP."""
        if self._clock:
            self._clock(ts)

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        r = self._c.post(path, json=body)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"error": r.text[:300]}

    def health(self) -> dict:
        """Which scorer the server is running, so a result can be read against a model version."""
        try:
            return self._c.get("/health").json()
        except Exception as e:                                  # noqa: BLE001 - reported, not raised
            return {"error": str(e)[:200]}

    def close(self) -> None:
        if self._close:
            self._close()


def open_local(world_dir: str | Path, scorer: str = "ml") -> Server:
    """The engine and the mock intel services in this process, both reading the built world.

    `scorer`: "ml" (the trained model) or "rules". The engine falls back to the rules by itself if
    the model file is missing, and /health reports which one is live.
    """
    import httpx
    from fastapi.testclient import TestClient

    from api.main import create_app
    from intel_mock.app import create_app as create_mock

    world_dir = Path(world_dir)
    mock = create_mock(world_dir)
    intel = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock), base_url="http://mock")
    app = create_app(world_dir, intel_client=intel, intel_cache_ttl_s=0, log_path=None,
                     evidence_async=False, scorer_name=scorer)
    client, mock_client = TestClient(app), TestClient(mock)

    def clock(ts: str) -> None:
        mock_client.post("/sim/clock", json={"set": ts}).raise_for_status()
    return Server(client, f"local ({app.state.model_version})", close=client.close, clock=clock)


def open_http(url: str, timeout_s: float = 20) -> Server:
    import httpx

    client = httpx.Client(base_url=url.rstrip("/"), timeout=timeout_s)
    return Server(client, url, close=client.close)


def open_server(target: str, world_dir: str | Path, timeout_s: float = 20, scorer: str = "ml") -> Server:
    return open_local(world_dir, scorer) if target == "local" else open_http(target, timeout_s)
