"""The blue-team console: watch a run step by step, see every decision with its reason and its
evidence, and do the human review, in one page with a sidebar.

    PYTHONPATH=backend;ml;data;red_team_blue_team python -m blue_team app      # -> http://127.0.0.1:8765

Pages: Run (start one, live timeline) · Complaints · HDBSCAN · Generator agent · Analyst agent ·
Playbooks (minimal card, exactly what is stored, approve / reject) · Playbook database.

Local only (bound to 127.0.0.1). Every review action goes through blue_team/review.py, so the rules
are the same as on the command line: two different analysts approve, a rejection needs a reason, a
card failing the gates cannot be approved, an edit clears earlier approvals. Analyst names are typed
in, not logged in: this is a demo tool, not access control. Start the app in a shell that has
AWS_BEARER_TOKEN_BEDROCK set if runs should use Bedrock; otherwise they run offline.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import typing
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from blue_team import config, engine_file, matcher, playbook_db, review

PAGE = Path(__file__).resolve().parent / "console.html"
STATES = ("review", "approved", "rejected")
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Decision(BaseModel):
    analyst: str
    decision: str
    note: str = ""


class TextEdit(BaseModel):
    analyst: str
    fields: dict


class StartRun(BaseModel):
    world: int = 0
    llm: str = "auto"            # auto | bedrock | offline
    model: str | None = None


class Reset(BaseModel):
    confirm: str


def engine_status(card: dict) -> dict:
    """Can this card go into the engine's data/playbooks/playbooks.yaml today, and if not, why not."""
    from schema.events import FraudType
    entry, problems = engine_file.export_entry({**card, "approved_by": card.get("approved_by", [])})
    names = typing.get_args(FraudType)
    blockers = list(problems)
    if names and card["name"] not in names:
        blockers.append("the contract's FraudType allows only " + ", ".join(names)
                        + ": a new name would fail the /v1/decide response (backend ask 1)")
    return {"ready": not blockers, "blockers": blockers, "entry": entry}


def _summary(card: dict, state: str) -> dict:
    approvals = sorted({r["analyst"] for r in card.get("reviews", []) if r["decision"] == "approve"})
    return {"name": card["name"], "title": card.get("title"), "state": state,
            "kind": "misnamed" if card.get("misnamed_as") else "new", "misnamed_as": card.get("misnamed_as"),
            "cases": (card.get("evidence") or {}).get("cases"), "verdict": (card.get("analyst") or {}).get("verdict"),
            "run_id": (card.get("evidence") or {}).get("run_id"), "cluster_id": (card.get("evidence") or {}).get("cluster_id"),
            "gates_pass": not card.get("gate_failures"), "approvals": approvals,
            "needed": config.load()["review"]["approvals_needed"]}


def create_app(root: Path | None = None, exports: Path | None = None, runs: Path | None = None,
               repo: Path | None = None) -> FastAPI:
    root, runs = root or config.PLAYBOOKS, runs or config.RUNS
    exports = exports or review.EXPORTS
    repo = repo or Path.cwd()
    app = FastAPI(title="RUKO blue team console", docs_url=None, redoc_url=None)
    running: dict = {"thread": None, "run_id": None}

    def load(name: str) -> tuple[dict, str]:
        try:
            card, state = review.load_card(name, root)
        except review.ReviewError as e:
            raise HTTPException(404, str(e)) from None
        if state not in STATES:
            raise HTTPException(404, f"{name} is a known playbook, not a draft")
        return card, state

    def run_dir(run_id: str) -> Path:
        if not RUN_ID.match(run_id) or not (runs / run_id).is_dir():
            raise HTTPException(404, f"no run {run_id!r}")
        return runs / run_id

    def read_json(p: Path, default=None):
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE.read_text(encoding="utf-8")

    # ---- runs ------------------------------------------------------------------------------------
    @app.get("/api/worlds")
    def worlds() -> list[dict]:
        return [{"index": i, **w, "ready": (repo / w["table"]).exists() and (repo / w["data"]).exists()}
                for i, w in enumerate(config.load()["console"]["worlds"])]

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        out = []
        for d in sorted(runs.glob("*"), reverse=True) if runs.exists() else []:
            st = read_json(d / "status.json")
            if st:
                sm = read_json(d / "summary.json", {})
                out.append({**st, "cases": sm.get("cases"), "candidates": len(sm.get("candidates", [])),
                            "agents": sm.get("agents")})
        return out

    @app.post("/api/runs")
    def start_run(body: StartRun) -> dict:
        if running["thread"] is not None and running["thread"].is_alive():
            raise HTTPException(409, f"run {running['run_id']} is still going")
        ws = worlds()
        if not 0 <= body.world < len(ws) or not ws[body.world]["ready"]:
            raise HTTPException(400, "that world's replayed table is not built (see README: testworld + replay)")
        if body.llm not in ("auto", "bedrock", "offline"):
            raise HTTPException(400, "llm must be auto, bedrock or offline")
        w = ws[body.world]
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

        def go():
            from blue_team import pipeline
            try:
                pipeline.run(repo / w["table"], repo / w["data"], "ml", body.llm, None, runs, root, log=print,
                             model=body.model or None, run_id=run_id)
            except Exception:  # noqa: BLE001 (recorded in the run's status.json and events)
                pass

        # The folder exists before the thread starts, so the timeline can poll it at once.
        (runs / run_id).mkdir(parents=True, exist_ok=True)
        (runs / run_id / "status.json").write_text(json.dumps({"run_id": run_id, "state": "running", "world": w["data"]}),
                                                   encoding="utf-8")
        t = threading.Thread(target=go, daemon=True, name=f"blue-team-{run_id}")
        running.update(thread=t, run_id=run_id)
        t.start()
        return {"run_id": run_id}

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str, after: int = 0) -> dict:
        d = run_dir(run_id)
        evs = []
        p = d / "events.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                e = json.loads(line)
                if e["seq"] > after:
                    evs.append(e)
        return {"status": read_json(d / "status.json", {}), "events": evs}

    @app.get("/api/runs/{run_id}/cases")
    def cases(run_id: str) -> list:
        return read_json(run_dir(run_id) / "cases.json", [])

    @app.get("/api/runs/{run_id}/clusters")
    def clusters(run_id: str) -> dict:
        d = run_dir(run_id)
        return {"clusters": read_json(d / "clusters.json", []), "config": config.load()["cluster"],
                "misnamed_config": config.load()["misnamed"], "summary": read_json(d / "summary.json", {})}

    @app.get("/api/runs/{run_id}/candidates")
    def candidates(run_id: str) -> list[dict]:
        out = []
        for p in sorted((run_dir(run_id) / "candidates").glob("*.json")):
            c = json.loads(p.read_text(encoding="utf-8"))
            out.append({"cluster_id": c["cluster"]["cluster_id"], "kind": c["cluster"]["kind"],
                        "ruko_named": c["cluster"]["nearest_playbook"] if c["cluster"]["kind"] == "misnamed" else None,
                        "name": c["draft"]["card"]["name"], "title": c["draft"]["card"].get("title"),
                        "drafted_by": c["draft"]["drafted_by"], "verdict": c["analyst"].get("verdict"),
                        "cases": len(c["cluster"]["case_ids"])})
        return out

    @app.get("/api/runs/{run_id}/candidates/{cluster_id}")
    def candidate(run_id: str, cluster_id: str) -> dict:
        for p in (run_dir(run_id) / "candidates").glob(f"{cluster_id}_*.json"):
            if p.name.startswith(cluster_id + "_"):
                c = json.loads(p.read_text(encoding="utf-8"))
                c.pop("labels", None)
                return c
        raise HTTPException(404, f"no candidate {cluster_id!r} in run {run_id}")

    # ---- playbook database -----------------------------------------------------------------------
    @app.get("/api/database")
    def database() -> dict:
        known = []
        for pb in playbook_db.load(("known",), root):
            known.append({"name": pb.name, "title": pb.title, "summary": pb.card.get("summary", ""),
                          "advice_en": pb.card.get("advice_en"), "advice_hi": pb.card.get("advice_hi"),
                          "rules": [{"priority": p, "in_words": matcher.describe(r)} for p, r in pb.rules],
                          "why": pb.card.get("engine_why", [])})
        approved = []
        for pb in playbook_db.load(("approved",), root):
            approved.append({"name": pb.name, "title": pb.title, "summary": pb.card.get("summary", ""),
                             "approved_by": pb.card.get("approved_by", []), "approved_at": pb.card.get("approved_at"),
                             "misnamed_as": pb.card.get("misnamed_as"),
                             "rules": [{"priority": p, "in_words": matcher.describe(r)} for p, r in pb.rules],
                             "engine": engine_status(pb.card)})
        return {"engine_file": str(engine_file.engine_path()), "known": known, "approved": approved,
                "waiting": len(list((root / "review").glob("*.yaml"))),
                "rejected": len(list((root / "rejected").glob("*.yaml")))}

    # ---- human review ----------------------------------------------------------------------------
    @app.get("/api/cards")
    def cards() -> dict:
        out = {s: [] for s in STATES}
        for s in STATES:
            for p in sorted((root / s).glob("*.yaml")):
                out[s].append(_summary(yaml.safe_load(p.read_text(encoding="utf-8")), s))
        return out

    @app.get("/api/cards/{name}")
    def card(name: str) -> dict:
        c, state = load(name)
        return {"state": state, "card": {k: v for k, v in c.items() if k != "label_tx_ids"},
                "summary": _summary(c, state), "engine": engine_status(c), "editable": list(review.EDITABLE)}

    @app.get("/api/cards/{name}/yaml", response_class=PlainTextResponse)
    def card_yaml(name: str) -> str:
        _, state = load(name)
        return (root / state / f"{name}.yaml").read_text(encoding="utf-8")

    @app.post("/api/cards/{name}/decision")
    def decide(name: str, body: Decision) -> dict:
        load(name)
        try:
            return review.decide(name, body.analyst, body.decision, body.note, root=root, exports=exports)
        except review.ReviewError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/cards/{name}/text")
    def edit(name: str, body: TextEdit) -> dict:
        load(name)
        try:
            return review.edit_text(name, body.analyst, body.fields, root=root)
        except review.ReviewError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/reset")
    def reset(body: Reset) -> dict:
        """Start from nothing: drafts, approvals, rejections, exports and runs are deleted."""
        if body.confirm != "RESET":
            raise HTTPException(400, "send confirm: RESET")
        if running["thread"] is not None and running["thread"].is_alive():
            raise HTTPException(409, "a run is still going")
        n = 0
        for s in STATES:
            for p in (root / s).glob("*.yaml"):
                p.unlink()
                n += 1
        for d in (exports, runs):
            if d.exists():
                shutil.rmtree(d)
        return {"deleted_cards": n}

    return app


def main(port: int = 8765) -> None:
    import uvicorn
    print(f"blue team console: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")
