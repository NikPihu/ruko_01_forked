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
import os
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


class RunnerStart(BaseModel):
    playbooks: str = "red_team"      # a key of console.red_team_runner.sets
    workers: int | None = None
    users: int | None = None
    victims: int | None = None
    rerun: bool = False              # judge again playbooks the inbox already has a verdict for


class VerifyStart(BaseModel):
    live: bool = True                # check 2: Nikunj's runner before / after on a fresh world
    retrain: bool = False            # check 3: LightGBM retrained with the card's labels


class RedBuild(BaseModel):
    source: str = "breakthroughs"    # breakthroughs (the inbox) | all (every red-team playbook)
    users: int | None = None
    days: int | None = None
    victim_rate: float | None = None
    red_boost: float | None = None
    seed: int | None = None


def engine_status(card: dict) -> dict:
    """Can this card go into the engine's data/playbooks/playbooks.yaml, and what would it do there:
    warn (policy raises its payments to T2+, its conditions span two families) or only name the scam."""
    from api.playbooks import families
    from schema.events import FraudType
    entry, problems = engine_file.export_entry({**card, "approved_by": card.get("approved_by") or ["analyst_1", "analyst_2"]})
    fam = sorted(families(yaml.safe_load(entry)[0]["match"])) if not problems else []
    notes = []
    if card["name"] not in typing.get_args(FraudType):
        notes.append("threat.fraud_type stays empty for a new name (the contract lists six); the payment is "
                     "labelled through `playbook` and the message key, and the app shows the tier's generic words")
    return {"ready": not problems, "blockers": list(problems), "entry": entry, "families": fam,
            "effect": None if problems else ("warns" if len(fam) >= 2 else "names only"), "notes": notes}


def _summary(card: dict, state: str) -> dict:
    approvals = sorted({r["analyst"] for r in card.get("reviews", []) if r["decision"] == "approve"})
    return {"name": card["name"], "title": card.get("title"), "state": state,
            "kind": "misnamed" if card.get("misnamed_as") else "new", "misnamed_as": card.get("misnamed_as"),
            "cases": (card.get("evidence") or {}).get("cases"), "verdict": (card.get("analyst") or {}).get("verdict"),
            "run_id": (card.get("evidence") or {}).get("run_id"), "cluster_id": (card.get("evidence") or {}).get("cluster_id"),
            "gates_pass": not card.get("gate_failures"), "approvals": approvals,
            "needed": config.load()["review"]["approvals_needed"]}


class ScenarioStart(BaseModel):
    llm: str | None = None           # bedrock | offline | auto (config agents.provider when None)


def create_app(root: Path | None = None, exports: Path | None = None, runs: Path | None = None,
               repo: Path | None = None, scenario_mode: bool = False) -> FastAPI:
    root, runs = root or config.PLAYBOOKS, runs or config.RUNS
    exports = exports or review.EXPORTS
    repo = repo or Path.cwd()
    app = FastAPI(title="RUKO blue team console", docs_url=None, redoc_url=None)
    running: dict = {"thread": None, "run_id": None}
    building: dict = {"thread": None, "state": "idle", "step": None, "params": None}
    runner: dict = {"thread": None, "state": "idle", "stop": False, "total": 0, "skipped": 0, "done": 0,
                    "running": [], "set": None}
    verifying: dict = {"thread": None, "state": "idle", "name": None, "log": [], "stop": False}
    demo: dict = {"thread": None, "state": "idle", "error": None}

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

    @app.get("/api/agents")
    def agents() -> dict:
        """Whether this console process can reach Bedrock at all (the key is read when the run starts)."""
        from blue_team import llm
        a = config.load()["agents"]
        return {"key": llm.has_credentials(), "region": os.environ.get("AWS_REGION") or a["region"],
                "models": a["models"], "help": None if llm.has_credentials() else llm.NO_KEY}

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
        if building["thread"] is not None and building["thread"].is_alive():
            raise HTTPException(409, "the red-team world is being built; run after it finishes")
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
        (runs / run_id / "status.json").write_text(json.dumps({"run_id": run_id, "state": "running", "world": w["data"],
                                                               "table": w["table"]}), encoding="utf-8")
        t = threading.Thread(target=go, daemon=True, name=f"blue-team-{run_id}")
        running.update(thread=t, run_id=run_id)
        t.start()
        return {"run_id": run_id}

    # ---- red team ------------------------------------------------------------------------------
    def red_world() -> dict:
        w = next((w for w in config.load()["console"]["worlds"] if w.get("red_team")), None)
        if not w:
            return {}
        data_dir, table = repo / w["data"], repo / w["table"]
        meta = read_json(data_dir / "red_team.json", {})
        info = {"data": w["data"], "table": w["table"], "built": bool(meta), "replayed": table.exists(), "meta": meta}
        if meta and (data_dir / "journeys.parquet").exists():
            import pandas as pd
            j = pd.read_parquet(data_dir / "journeys.parquet", columns=["playbook", "n_payments", "reported"])
            red = j["playbook"].isin(meta.get("red_team", []))
            info.update(journeys=int(len(j)), red_journeys=int(red.sum()),
                        red_types=int(j.loc[red, "playbook"].nunique()), red_paid=int((j.loc[red, "n_payments"] > 0).sum()),
                        red_reported=int(j.loc[red, "reported"].sum()))
        return info

    @app.get("/api/redteam")
    def redteam_info() -> dict:
        from blue_team import redteam
        pbs = redteam.load()
        for p in pbs:
            pb = p.pop("playbook")
            p["steps_detail"] = [{"id": s.get("id"), "gap_min": s.get("gap_min"), "events": s.get("events", []),
                                  "ask": s.get("ask"), "crew_pays": s.get("crew_pays"), "p": s.get("p")}
                                 for s in pb.get("steps", [])]
            p["mules"], p["mule_kinds"] = pb.get("mules"), pb.get("mule_kinds")
        return {"playbooks": pbs, "techniques": redteam.TECHNIQUES, "world": red_world(),
                "build": build_status(), "defaults": config.load()["console"]["red_team_build"]}

    def build_status() -> dict:
        log_p = repo / config.load()["console"]["red_team_build"]["log"]
        tail = log_p.read_text(encoding="utf-8", errors="replace").splitlines()[-25:] if log_p.exists() else []
        alive = building["thread"] is not None and building["thread"].is_alive()
        return {"state": "running" if alive else building["state"], "step": building["step"],
                "params": building["params"], "log": tail}

    @app.get("/api/redteam/build")
    def redteam_build_status() -> dict:
        return build_status()

    @app.post("/api/redteam/build")
    def redteam_build(body: RedBuild) -> dict:
        import os
        import subprocess
        import sys
        if building["thread"] is not None and building["thread"].is_alive():
            raise HTTPException(409, "the red-team world is already being built")
        if runner["thread"] is not None and runner["thread"].is_alive():
            raise HTTPException(409, "the red-team runner is still judging playbooks")
        if running["thread"] is not None and running["thread"].is_alive():
            raise HTTPException(409, "a blue-team run is going; build after it finishes")
        d = config.load()["console"]["red_team_build"]
        prm = {k: getattr(body, k) if getattr(body, k) is not None else d[k] for k in ("users", "days", "victim_rate", "red_boost", "seed")}
        from blue_team import inbox as inbox_mod, redteam as red_mod
        if body.source == "breakthroughs":
            if not inbox_mod.breakthroughs():
                raise HTTPException(400, "the blue-team inbox has no breakthroughs yet: run the red team first")
            red_dir = inbox_mod.INBOX / "breakthroughs"
        elif body.source == "all":
            red_dir = red_mod.RED_DIR
        else:
            raise HTTPException(400, "source must be breakthroughs or all")
        prm["source"] = body.source
        if not (100 <= prm["users"] <= 20000 and 7 <= prm["days"] <= 60 and 0 < prm["victim_rate"] <= 1 and 0 < prm["red_boost"] <= 10):
            raise HTTPException(400, "users 100-20000, days 7-60, victim_rate 0-1, red_boost 0-10")
        w = next(w for w in config.load()["console"]["worlds"] if w.get("red_team"))
        log_p = repo / d["log"]
        log_p.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(["backend", "ml", "data", "red_team_blue_team"]),
               "PYTHONIOENCODING": "utf-8"}
        steps = [("building the world with sim_v2", [sys.executable, "-m", "blue_team.testworld", "--red-team",
                  "--users", str(prm["users"]), "--days", str(prm["days"]), "--victim-rate", str(prm["victim_rate"]),
                  "--red-boost", str(prm["red_boost"]), "--seed", str(prm["seed"]), "--out", w["data"],
                  "--red-dir", str(red_dir)]),
                 ("replaying every payment through RUKO (minutes)", [sys.executable, "-m", "dataset.replay", "--data", w["data"],
                  "--out", w["table"], "--warmup-days", "7"])]

        def go():
            with open(log_p, "w", encoding="utf-8") as fh:
                for step, cmd in steps:
                    building["step"] = step
                    fh.write(f"== {step}\n")
                    fh.flush()
                    rc = subprocess.run(cmd, cwd=repo, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
                    if rc:
                        fh.write(f"== failed with exit code {rc}\n")
                        building["state"] = "failed"
                        return
                fh.write("== done\n")
            building.update(state="done", step=None)

        t = threading.Thread(target=go, daemon=True, name="red-team-build")
        building.update(thread=t, state="running", step="starting", params=prm)
        t.start()
        return build_status()

    def runner_status() -> dict:
        from blue_team import inbox as inbox_mod
        rc = config.load()["console"]["red_team_runner"]
        log_p = repo / rc["log"]
        tail = log_p.read_text(encoding="utf-8", errors="replace").splitlines()[-30:] if log_p.exists() else []
        alive = runner["thread"] is not None and runner["thread"].is_alive()
        return {"state": "running" if alive else runner["state"], "set": runner["set"], "total": runner["total"],
                "skipped": runner["skipped"], "done": runner["done"], "running": list(runner["running"]),
                "stopping": runner["stop"] and alive, "log": tail, "sets": list(rc["sets"]), "workers": rc["workers"],
                "verdicts": inbox_mod.verdicts(), "breakthroughs": [p.stem for p in inbox_mod.breakthroughs()]}

    @app.get("/api/redteam/runner")
    def redteam_runner_status() -> dict:
        return runner_status()

    @app.post("/api/redteam/runner")
    def redteam_runner(body: RunnerStart) -> dict:
        import os
        import subprocess
        import sys
        from concurrent.futures import ThreadPoolExecutor
        from blue_team import inbox as inbox_mod
        rc = config.load()["console"]["red_team_runner"]
        for job, what in ((runner, "the red-team runner is already going"), (building, "the attack world is being built"),
                          (running, "a blue-team run is going"), (verifying, "a playbook is being verified")):
            if job["thread"] is not None and job["thread"].is_alive():
                raise HTTPException(409, what)
        if body.playbooks not in rc["sets"]:
            raise HTTPException(400, f"playbooks must be one of {list(rc['sets'])}")
        workers = body.workers or rc["workers"]
        if not 1 <= workers <= 8 or (body.users is not None and not 50 <= body.users <= 3000) or \
                (body.victims is not None and not 5 <= body.victims <= 200):
            raise HTTPException(400, "workers 1-8, users 50-3000, victims 5-200")
        files = sorted((repo / rc["sets"][body.playbooks]).glob("*.yaml"))
        seen = set() if body.rerun else set(inbox_mod.verdicts())
        todo = [f for f in files if f.stem not in seen]
        log_p = repo / rc["log"]
        log_p.parent.mkdir(parents=True, exist_ok=True)
        out_base = repo / rc["out"] / body.playbooks
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(["backend", "ml", "data", "synthetic_playbook", "red_team_blue_team"]),
               "PYTHONIOENCODING": "utf-8"}
        extra = (["--users", str(body.users)] if body.users else []) + (["--victims", str(body.victims)] if body.victims else [])
        lock = threading.Lock()

        def say(line: str):
            with lock, open(log_p, "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().strftime('%H:%M:%S')}  {line}\n")

        def one(f: Path):
            if runner["stop"]:
                return
            with lock:
                runner["running"].append(f.stem)
            out = out_base / f.stem
            out.mkdir(parents=True, exist_ok=True)
            with open(out / "runner.log", "w", encoding="utf-8") as fh:
                rcode = subprocess.run([sys.executable, "-m", "interface_script", "run", "--playbook", str(f), "--out", str(out),
                                        *extra], cwd=repo, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
            v = inbox_mod.verdicts().get(f.stem)
            with lock:
                runner["running"].remove(f.stem)
                runner["done"] += 1
            if rcode or not v:
                say(f"{f.stem}: FAILED (exit {rcode}); see {out / 'runner.log'}")
            else:
                say(f"{f.stem}: {'BREAKTHROUGH' if v['breakthrough'] else 'caught'} - {v['scam_called_normal']}/"
                    f"{v['scam_payments_judged']} scam payments called normal ({v['miss_rate']:.0%}), "
                    f"{v['false_alarm_rate']:.1%} false alarms")

        def go():
            log_p.write_text("", encoding="utf-8")
            say(f"red team: {len(files)} playbooks in {rc['sets'][body.playbooks]}, {len(files) - len(todo)} already judged, "
                f"{len(todo)} to run, {workers} at a time")
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(one, todo))
            say("stopped" if runner["stop"] else "done")
            runner.update(state="stopped" if runner["stop"] else "done")

        t = threading.Thread(target=go, daemon=True, name="red-team-runner")
        runner.update(thread=t, state="running", stop=False, total=len(files), skipped=len(files) - len(todo), done=0,
                      running=[], set=body.playbooks)
        t.start()
        return runner_status()

    @app.post("/api/redteam/runner/stop")
    def redteam_runner_stop() -> dict:
        runner["stop"] = True
        return runner_status()

    @app.get("/api/runs/{run_id}/scorecard")
    def scorecard(run_id: str) -> dict:
        from blue_team import redteam
        d = run_dir(run_id)
        cached = d / "scorecard.json"
        if cached.exists():
            return read_json(cached)
        st = read_json(d / "status.json", {})
        if st.get("state") != "done":
            raise HTTPException(409, "the run has not finished")
        world, table = Path(st.get("world", "")), Path(st.get("table", ""))
        if not world.is_absolute():
            world, table = repo / world, repo / table
        if not (world / "journeys.parquet").exists() or not table.exists():
            raise HTTPException(404, "the run's world or replayed table is gone")
        res = redteam.scorecard(d, world, table)
        if "error" not in res:
            cached.write_text(json.dumps(res, default=str), encoding="utf-8")
        return res

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
        return {"clusters": read_json(d / "clusters.json", []), "map": read_json(d / "cluster_map.json", {}),
                "config": config.load()["cluster"],
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

    def verify_status(name: str) -> dict:
        from blue_team import verify
        alive = verifying["thread"] is not None and verifying["thread"].is_alive()
        mine = verifying["name"] == name
        return {"state": verifying["state"] if mine else "idle", "running": alive and mine,
                "busy_with": verifying["name"] if alive and not mine else None,
                "log": verifying["log"][-60:] if mine else [], "result": verify.load_result(name, exports)}

    @app.get("/api/cards/{name}/verify")
    def card_verify_status(name: str) -> dict:
        load(name)
        return verify_status(name)

    @app.post("/api/cards/{name}/verify")
    def card_verify(name: str, body: VerifyStart) -> dict:
        """Does RUKO now catch the scam this approved playbook describes (verify.py)."""
        from blue_team import verify
        _, state = load(name)
        if state != "approved":
            raise HTTPException(400, f"{name} is {state}: only approved playbooks are verified")
        for job, what in ((verifying, "a playbook is already being verified"), (runner, "the red-team runner is going"),
                          (building, "the attack world is being built"), (running, "a blue-team run is going")):
            if job["thread"] is not None and job["thread"].is_alive():
                raise HTTPException(409, what)

        def say(line: str):
            verifying["log"].append(f"{datetime.now().strftime('%H:%M:%S')}  {line}")

        def go():
            try:
                verify.verify(name, live_check=body.live, retrain_check=body.retrain, root=root, exports=exports,
                              runs=runs, repo=repo, log=say, stop=lambda: verifying["stop"])
                verifying["state"] = "done"
            except Exception as e:  # noqa: BLE001 (shown on the page)
                say(f"FAILED: {e}")
                verifying["state"] = "failed"

        t = threading.Thread(target=go, daemon=True, name=f"verify-{name}")
        verifying.update(thread=t, state="running", name=name, log=[], stop=False)
        t.start()
        return verify_status(name)

    # ---- the demo: the whole loop on one small world (scenario.py) ------------------------------
    def scenario_status() -> dict:
        from blue_team import scenario as sc
        st = sc.load_state()
        alive = (demo["thread"] is not None and demo["thread"].is_alive()) or sc.busy()   # also one started elsewhere
        names = lambda s: sorted(p.stem for p in (sc.DB / s).glob("*.yaml")) if (sc.DB / s).exists() else []
        return {"mode": scenario_mode, "running": alive, "state": demo["state"] if alive or demo["state"] == "failed" else
                ("done" if st.get("step") == "done" else st.get("step") or "none"),
                "error": demo["error"], "scenario": st, "log": sc.log_tail(),
                "drafts": [{"name": c["name"], "gate_failures": c.get("gate_failures") or [],
                            "warns": (c.get("backtest") or {}).get("warns"), "families": (c.get("backtest") or {}).get("families", []),
                            "recall": (c.get("backtest") or {}).get("cluster_case_recall")}
                           for c in (yaml.safe_load(f.read_text(encoding="utf-8"))
                                     for f in sorted((sc.DB / "review").glob("*.yaml")) if (sc.DB / "review").exists())],
                "queued": names("review"), "approved": names("approved"), "rejected": names("rejected"),
                "settings": sc.settings(), "report": sc.report(st["before"], st.get("after"), st["new"]) if st.get("before") else None}

    @app.get("/api/scenario")
    def scenario_get() -> dict:
        return scenario_status()

    def scenario_job(fn) -> dict:
        if not scenario_mode:
            raise HTTPException(400, "start the console with --scenario: python -m blue_team app --scenario")
        from blue_team import scenario as sc
        if sc.busy():
            raise HTTPException(409, "a demo step is already running (console or command line)")
        for job, what in ((demo, "the demo is already running"), (running, "a blue-team run is going"),
                          (runner, "the red-team runner is going"), (building, "the attack world is being built"),
                          (verifying, "a playbook is being verified")):
            if job["thread"] is not None and job["thread"].is_alive():
                raise HTTPException(409, what)

        def go():
            try:
                fn()
                demo.update(state="done", error=None)
            except Exception as e:  # noqa: BLE001 (shown on the page)
                demo.update(state="failed", error=f"{type(e).__name__}: {e}")

        t = threading.Thread(target=go, daemon=True, name="scenario")
        demo.update(thread=t, state="running", error=None)
        t.start()
        return scenario_status()

    @app.post("/api/scenario/start")
    def scenario_start(body: ScenarioStart) -> dict:
        from blue_team import scenario as sc
        s = sc.settings()
        return scenario_job(lambda: sc.start(s["new"], s["known"], body.llm, log=lambda *_: None))

    @app.post("/api/scenario/redraft")
    def scenario_redraft(body: ScenarioStart) -> dict:
        from blue_team import scenario as sc
        if not sc.load_state().get("before"):
            raise HTTPException(400, "no demo yet: start one")
        return scenario_job(lambda: sc.redraft(body.llm, log=lambda *_: None))

    @app.post("/api/scenario/rerun")
    def scenario_rerun() -> dict:
        from blue_team import scenario as sc
        if not sc.load_state().get("before"):
            raise HTTPException(400, "no scenario yet: start one")
        if not scenario_status()["approved"]:
            raise HTTPException(400, "no approved playbook yet: two analysts approve on the Playbooks page")
        return scenario_job(lambda: sc.rerun(log=lambda *_: None))

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


def main(port: int = 8765, scenario: bool = False) -> None:
    import uvicorn
    if scenario:   # the scenario's own playbook database, runs and exports (scenario.py)
        from blue_team import scenario as sc
        app = create_app(root=sc.DB, exports=sc.EXPORTS, runs=sc.RUNS, repo=config.REPO, scenario_mode=True)
        print(f"blue team console (SCENARIO database {sc.DB}): http://127.0.0.1:{port}  (Ctrl+C to stop)")
    else:
        app = create_app()
        print(f"blue team console: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
