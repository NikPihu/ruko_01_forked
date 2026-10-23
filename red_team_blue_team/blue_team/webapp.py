"""The human step as a web page: see each drafted playbook in full, fix its words, approve or reject.

    PYTHONPATH=backend;ml;data;red_team_blue_team python -m blue_team app      # -> http://127.0.0.1:8765

Local only (bound to 127.0.0.1). Every action goes through blue_team/review.py, so the rules are the
same as on the command line: two different analysts approve, a rejection needs a reason, a card
failing the gates cannot be approved, an edit clears earlier approvals. Analyst names are typed in,
not logged in: this is a demo tool, not access control.
"""
from __future__ import annotations

import json
import typing
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from blue_team import config, engine_file, review

PAGE = Path(__file__).resolve().parent / "review_page.html"
STATES = ("review", "approved", "rejected")


class Decision(BaseModel):
    analyst: str
    decision: str
    note: str = ""


class TextEdit(BaseModel):
    analyst: str
    fields: dict


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


def _candidate(card: dict, runs: Path) -> dict:
    ev = card.get("evidence") or {}
    p = runs / str(ev.get("run_id")) / "candidates" / f"{ev.get('cluster_id')}_{card['name']}.json"
    if not p.exists():
        return {}
    cand = json.loads(p.read_text(encoding="utf-8"))
    ov = cand.get("overview", {})
    keep = ("cases", "users", "first_payment", "last_complaint", "amount_inr", "distinctive_tokens", "typical_case",
            "complaint_sources", "ruko_said", "payees", "lift_is_against")
    return {"overview": {k: ov.get(k) for k in keep}, "examples": cand.get("examples", []),
            "drafted_by": cand.get("draft", {}).get("drafted_by"),
            "agent_turns": {"investigator": (cand.get("draft", {}).get("usage") or {}).get("turns"),
                            "analyst": (cand.get("analyst", {}).get("usage") or {}).get("turns")}}


def _summary(card: dict, state: str) -> dict:
    approvals = sorted({r["analyst"] for r in card.get("reviews", []) if r["decision"] == "approve"})
    return {"name": card["name"], "title": card.get("title"), "state": state,
            "kind": "misnamed" if card.get("misnamed_as") else "new", "misnamed_as": card.get("misnamed_as"),
            "cases": (card.get("evidence") or {}).get("cases"), "verdict": (card.get("analyst") or {}).get("verdict"),
            "gates_pass": not card.get("gate_failures"), "approvals": approvals,
            "needed": config.load()["review"]["approvals_needed"]}


def create_app(root: Path | None = None, exports: Path | None = None, runs: Path | None = None) -> FastAPI:
    root, runs = root or config.PLAYBOOKS, runs or config.RUNS
    app = FastAPI(title="RUKO blue team review", docs_url=None, redoc_url=None)

    def load(name: str) -> tuple[dict, str]:
        try:
            card, state = review.load_card(name, root)
        except review.ReviewError as e:
            raise HTTPException(404, str(e)) from None
        if state not in STATES:
            raise HTTPException(404, f"{name} is a known playbook, not a draft")
        return card, state

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return PAGE.read_text(encoding="utf-8")

    @app.get("/api/cards")
    def cards() -> dict:
        import yaml
        out = {s: [] for s in STATES}
        for s in STATES:
            for p in sorted((root / s).glob("*.yaml")):
                out[s].append(_summary(yaml.safe_load(p.read_text(encoding="utf-8")), s))
        return out

    @app.get("/api/cards/{name}")
    def card(name: str) -> dict:
        c, state = load(name)
        hidden = {"label_tx_ids"}
        return {"state": state, "card": {k: v for k, v in c.items() if k not in hidden},
                "summary": _summary(c, state), "engine": engine_status(c), "candidate": _candidate(c, runs),
                "editable": list(review.EDITABLE)}

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

    return app


def main(port: int = 8765) -> None:
    import uvicorn
    print(f"blue team review: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")
