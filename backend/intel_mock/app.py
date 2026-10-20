"""The mock world: NPCI, banks, DoT FRI and I4C registry as one FastAPI app with one sim clock.

    PYTHONPATH=backend:ml:data python -m intel_mock.app --data data/ --port 8001

Each organisation has its own URL prefix and only answers with what it would really know.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from . import bank, dot_fri, i4c_registry, npci
from .store import Store


class ClockUpdate(BaseModel):
    set: Optional[datetime] = None
    advance_hours: Optional[float] = None


class Settings(BaseModel):
    visibility: Optional[Literal["none", "partner", "dpip"]] = None
    latency_ms: Optional[int] = Field(None, ge=0, le=5000)


def create_app(data_dir: str | Path) -> FastAPI:
    app = FastAPI(title="RUKO mock world", description=__doc__)
    app.state.store = Store.load(data_dir)
    app.state.mulehunter_cache = {}

    @app.middleware("http")
    async def simulated_latency(request: Request, call_next):
        # Lets the risk engine's timeout and fail-open path be tested. ?delay_ms= works per call.
        if not request.url.path.startswith(("/sim", "/health", "/docs", "/openapi")):
            ms = int(request.query_params.get("delay_ms", 0)) or app.state.store.latency_ms
            if ms:
                await asyncio.sleep(ms / 1000)
        return await call_next(request)

    for r in (npci.router, bank.router, dot_fri.router, i4c_registry.router):
        app.include_router(r)

    @app.get("/health", tags=["Sim controls"])
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/sim/state", tags=["Sim controls"])
    def state() -> dict:
        s = app.state.store
        return {"now": s.now.isoformat(), "data_end": s.data_end.isoformat(),
                "visibility": s.visibility, "latency_ms": s.latency_ms,
                "live_payments": s.live_payments}

    @app.post("/sim/clock", tags=["Sim controls"])
    def clock(body: ClockUpdate) -> dict:
        s = app.state.store
        if body.set:
            s.set_clock(body.set)
        if body.advance_hours:
            s.advance(body.advance_hours)
        return state()

    @app.post("/sim/settings", tags=["Sim controls"])
    def settings(body: Settings) -> dict:
        s = app.state.store
        if body.visibility:
            s.visibility = body.visibility
        if body.latency_ms is not None:
            s.latency_ms = body.latency_ms
        return state()

    @app.post("/sim/reset", tags=["Sim controls"])
    def reset() -> dict:
        """Reload the generated data, drop live payments, put the clock back at the data end."""
        app.state.store.reset()
        app.state.mulehunter_cache.clear()
        return state()

    return app


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(description="Run the mock world")
    p.add_argument("--data", default="data")
    p.add_argument("--port", type=int, default=8001)
    a = p.parse_args()
    uvicorn.run(create_app(a.data), host="0.0.0.0", port=a.port)


if __name__ == "__main__":
    main()
