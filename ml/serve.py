"""Run the RUKO risk engine with the trained ML scorer instead of the rules (no backend edits).

    PYTHONPATH=backend;ml;data python -m serve --data data --port 8000 [--demo-clock]

Same app and arguments as `python -m api.main`, which now runs this model by default too
(`--scorer ml`); unlike it, this fails at start instead of falling back to the rules when the model
cannot load. `/health` and evidence records carry the model's version.
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
    model = predict.load()  # fail at start, not on the first payment, if the model file is missing
    app.state.score, app.state.model_version = predict.score, model.version
    uvicorn.run(app, host="0.0.0.0", port=a.port)


if __name__ == "__main__":
    main()
