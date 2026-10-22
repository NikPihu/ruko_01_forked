"""Run the RUKO risk engine with the trained ML scorer instead of the rules (no backend edits).

    PYTHONPATH=backend;ml;data python -m serve --data data --port 8000 [--demo-clock]

Same app and arguments as `python -m api.main`; only `app.state.score` (the engine's swap point)
becomes model.predict.score. Evidence records carry the model's version. `/health` still names
the rules version until backend reports the active scorer (ml/PLAN.md §12, Jagdeep).
"""
from __future__ import annotations

import argparse

from api.main import create_app
from model import predict


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", default="data")
    p.add_argument("--intel", default="http://127.0.0.1:8001")
    p.add_argument("--evidence", default="logs/evidence.db")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--demo-clock", action="store_true")
    a = p.parse_args()
    app = create_app(a.data, intel_url=a.intel, evidence_path=a.evidence, demo_clock=a.demo_clock,
                     discover_every_s=3600)
    predict.load()  # fail at start, not on the first payment, if the model file is missing
    app.state.score = predict.score
    uvicorn.run(app, host="0.0.0.0", port=a.port)


if __name__ == "__main__":
    main()
