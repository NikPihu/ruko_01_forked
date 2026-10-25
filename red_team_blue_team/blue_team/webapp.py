"""The blue-team console: watch a run step by step, see every decision with its reason and its
evidence, and do the human review, in one page with a sidebar.

    PYTHONPATH=backend;ml;data;red_team_blue_team python -m blue_team app      # -> http://127.0.0.1:8765

Four tabs that follow the loop (docs/design/red-blue-console/README.md): Overview (scam groups,
waiting list) · 1 Attack (red-team runner, per-attack detail, attack world, generator) · 2 Investigate
(run progress, HDBSCAN groups, complaints) · 3 Playbooks (review queue, library, the "why it was
chosen" page with sign-off), plus the Live check panel (the demo, scenario.py).

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


class Generate(BaseModel):
    count: int = 10                  # red-team playbooks to generate (red_team/generator.py)


class VerifyStart(BaseModel):
    live: bool = True                # check 2: the attack runner before / after on a fresh world
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


def backtest_summary(draft: dict) -> dict:
    """What a draft's rule did on past payments, and whether, approved, it would warn or only name."""
    bt = draft.get("backtest") or {}
    fam = bt.get("families")
    if fam is None:                                  # runs from before backtests reported families
        fam = sorted(engine_file.rule_families(draft["card"]["matcher"])) if draft.get("card", {}).get("matcher") else []
    return {"gate_failures": draft.get("gate_failures") or [], "recall": bt.get("cluster_case_recall"),
            "payment_recall": bt.get("cluster_payment_recall"), "legit_per_1000": bt.get("legit_payments_named_per_1000"),
            "families": fam, "warns": len(fam) >= 2}


def _summary(card: dict, state: str) -> dict:
    approvals = sorted({r["analyst"] for r in card.get("reviews", []) if r["decision"] == "approve"})
    bt = card.get("backtest") or {}
    fam = bt.get("families")
    if fam is None and (card.get("match") or [{}])[0].get("rule"):
        fam = sorted(engine_file.rule_families(card["match"][0]["rule"]))
    return {"name": card["name"], "title": card.get("title"), "state": state,
            "kind": "misnamed" if card.get("misnamed_as") else "new", "misnamed_as": card.get("misnamed_as"),
            "cases": (card.get("evidence") or {}).get("cases"), "verdict": (card.get("analyst") or {}).get("verdict"),
            "run_id": (card.get("evidence") or {}).get("run_id"), "cluster_id": (card.get("evidence") or {}).get("cluster_id"),
            "gates_pass": not card.get("gate_failures"), "approvals": approvals,
            "needed": config.load()["review"]["approvals_needed"],
            "catches": bt.get("cluster_case_recall"), "legit_per_1000": bt.get("legit_payments_named_per_1000"),
            "families": fam or [], "warns": len(fam or []) >= 2, "approved_at": card.get("approved_at")}


class LiveStart(BaseModel):
    attacks: list[str] = []          # one to three red-team playbooks (red_team/playbooks)
    attack: str | None = None        # older consoles send one
    llm: str | None = None           # bedrock | offline | auto
    transactions: int | None = None  # the session's size (config scenario.live.transactions when not given)


class LiveControl(BaseModel):
    paused: bool | None = None
    delay: float | None = None       # seconds between shown payments
    step: bool = False               # while paused: show one more


class ScenarioStart(BaseModel):
    llm: str | None = None           # bedrock | offline | auto (config agents.provider when None)


def create_app(root: Path | None = None, exports: Path | None = None, runs: Path | None = None,
               repo: Path | None = None, scenario_mode: bool = False) -> FastAPI:
    root, runs = root or config.PLAYBOOKS, runs or config.RUNS
    exports = exports or review.EXPORTS
    repo = repo or Path.cwd()
    app = FastAPI(title="RUKO Analyst Console", docs_url=None, redoc_url=None)
    running: dict = {"thread": None, "run_id": None}
    building: dict = {"thread": None, "state": "idle", "step": None, "params": None}
    runner: dict = {"thread": None, "state": "idle", "stop": False, "total": 0, "skipped": 0, "done": 0,
                    "running": [], "set": None}
    verifying: dict = {"thread": None, "state": "idle", "name": None, "log": [], "stop": False}
    demo: dict = {"thread": None, "state": "idle", "error": None}
    generating: dict = {"thread": None, "state": "idle"}

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
        if scenario_mode:
            from blue_team import scenario as sc
            if (sc.load_state() or {}).get("mode") == "live":
                raise HTTPException(409, "a live session owns Investigate and Playbooks: its blue team runs by itself "
                                         "when the attack is over. Press Stop & clear on Live to start something else.")
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

    # ---- red team: one attack in detail, the generator, scam groups ---------------------------
    @app.get("/api/redteam/playbooks/{name}/detail")
    def redteam_detail(name: str) -> dict:
        """Where RUKO lost one attack, from the runner's per-payment results (results.csv)."""
        import pandas as pd
        from blue_team import inbox as inbox_mod
        if not RUN_ID.match(name):
            raise HTTPException(404, "no such playbook")
        v = inbox_mod.verdicts().get(name)
        if not v:
            raise HTTPException(404, f"{name} has not been run by the attack runner yet")
        f = Path(v.get("runner_out", "")) / "results.csv"
        out = {"verdict": v, "histogram": [], "by_step": [], "reasons": {}, "normal_max_score": v.get("normal_max_score", 70)}
        if not f.exists():
            return {**out, "note": "the runner's per-payment results are gone (results.csv)"}
        r = pd.read_csv(f)
        for col in ("judged", "is_scam", "called_normal"):   # empty on fail-open rows, so read as text
            r[col] = r[col].map({True: True, False: False, "True": True, "False": False}).fillna(False).astype(bool)
        scam = r[r.judged & r.is_scam]
        bins = (scam["threat_score"].clip(0, 99) // 5).astype(int).value_counts()
        out["histogram"] = [int(bins.get(i, 0)) for i in range(20)]
        out["by_step"] = [{"step": int(k), "payments": int(len(g)), "called_normal": int(g.called_normal.sum())}
                          for k, g in scam.assign(step=scam.journey_pay_index.fillna(-1).astype(int)).groupby("step")]
        caught = scam[~scam.called_normal].reasons.dropna()
        out["reasons"] = pd.Series([x for line in caught for x in str(line).split("|") if x],
                                   dtype=object).value_counts().to_dict()
        return out

    def generate_status() -> dict:
        g = config.load()["console"]
        log_p = repo / g["red_team_generate"]["log"]
        tail = log_p.read_text(encoding="utf-8", errors="replace").splitlines()[-20:] if log_p.exists() else []
        alive = generating["thread"] is not None and generating["thread"].is_alive()
        out_dir = repo / g["red_team_runner"]["sets"]["generated"]
        return {"state": "running" if alive else generating["state"], "log": tail,
                "generated": len(list(out_dir.glob("*.yaml"))) if out_dir.is_dir() else 0,
                "bedrock": bool(os.environ.get("BEDROCK_MODEL_ID"))}

    @app.get("/api/redteam/generate")
    def redteam_generate_status() -> dict:
        return generate_status()

    @app.post("/api/redteam/generate")
    def redteam_generate(body: Generate) -> dict:
        """New attack playbooks from the red team's generator (red_team/cli.py) into the `generated` set."""
        import subprocess
        import sys
        if generating["thread"] is not None and generating["thread"].is_alive():
            raise HTTPException(409, "the generator is already running")
        if not 1 <= body.count <= 50:
            raise HTTPException(400, "count 1-50")
        g = config.load()["console"]
        log_p = repo / g["red_team_generate"]["log"]
        log_p.parent.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(["backend", "ml", "data", "red_team_blue_team"]),
               "PYTHONIOENCODING": "utf-8"}
        cmd = [sys.executable, "-m", "red_team.cli", "--out-dir", g["red_team_runner"]["sets"]["generated"],
               "--target-count", str(body.count)]

        def go():
            with open(log_p, "w", encoding="utf-8") as fh:
                rc = subprocess.run(cmd, cwd=repo, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
            generating["state"] = "failed" if rc else "done"

        t = threading.Thread(target=go, daemon=True, name="red-team-generate")
        generating.update(thread=t, state="running")
        t.start()
        return generate_status()

    @app.get("/api/groups")
    def scam_groups(run: str | None = None) -> dict:
        """The red team's attacks per scam group (blue_team/groups.py), graded with a run's scorecard."""
        from blue_team import groups as groups_mod, inbox as inbox_mod, redteam
        rid = run or next((r["run_id"] for r in list_runs() if r.get("state") == "done"), None)
        sc, cl = None, []
        if rid:
            try:
                sc = scorecard(rid)
                sc = sc if sc.get("is_red_world") else None
                cl = clusters(rid)["clusters"]
            except HTTPException:
                sc = None
        titles = {pb.name: pb.title for pb in playbook_db.load(("known",), root)}
        out = groups_mod.build(redteam.load(), inbox_mod.verdicts(), sc, cl, cards(), titles)
        return {"run_id": rid, "graded": sc is not None, "groups": out}

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
                        "cases": len(c["cluster"]["case_ids"]), **backtest_summary(c["draft"])})
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
        cfg = config.load()
        return {"state": state, "card": {k: v for k, v in c.items() if k != "label_tx_ids"},
                "summary": _summary(c, state), "engine": engine_status(c), "editable": list(review.EDITABLE),
                "limits": {**cfg["gates"], "known_similarity": cfg["cluster"]["known_similarity"]}}

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
            except sc.Cancelled:
                demo.update(state="idle", error=None)
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

    # ---- the live loop: one attack, one payment at a time (scenario.start_live) --------------------
    @app.get("/api/live")
    def live_get(after: int = 0) -> dict:
        from blue_team import scenario as sc
        events, total = sc.feed_since(after)
        st = scenario_status()
        return {"events": events, "total": total, "control": sc.control(), "running": st["running"],
                "state": st["state"], "error": st["error"], "mode": scenario_mode, "scenario": st["scenario"],
                "queued": st["queued"], "approved": st["approved"], "rejected": st["rejected"]}

    @app.post("/api/live/start")
    def live_start(body: LiveStart) -> dict:
        from blue_team import redteam, scenario as sc
        attacks = body.attacks or ([body.attack] if body.attack else [])
        names = {p["name"] for p in redteam.load()}
        bad = [a for a in attacks if a not in names]
        if bad:
            raise HTTPException(400, f"not red-team playbooks: {', '.join(bad)}")
        if not 1 <= len(attacks) <= 3 or len(set(attacks)) != len(attacks):
            raise HTTPException(400, "pick one to three different attacks")
        if body.transactions is not None and not sc.MIN_TX <= body.transactions <= sc.MAX_TX:
            raise HTTPException(400, f"transactions: {sc.MIN_TX:,} to {sc.MAX_TX:,}")
        return scenario_job(lambda: sc.start_live(attacks, body.llm, log=lambda *_: None, transactions=body.transactions))

    @app.post("/api/live/control")
    def live_control(body: LiveControl) -> dict:
        from blue_team import scenario as sc
        if body.delay is not None and not 0 <= body.delay <= 10:
            raise HTTPException(400, "delay 0-10 s")
        return sc.control(paused=body.paused, delay=body.delay, step=body.step)

    @app.post("/api/live/clear")
    def live_clear() -> dict:
        """Stop & clear: end the session wherever it is (attack, blue team, replay) and empty the demo folder."""
        from blue_team import scenario as sc
        if not scenario_mode:
            raise HTTPException(400, "start the console with --scenario: python -m blue_team app --scenario")
        try:
            out = sc.stop_and_clear(wait_for=lambda: demo["thread"] is not None and demo["thread"].is_alive())
        except sc.Busy as e:
            raise HTTPException(409, str(e)) from None
        demo.update(state="idle", error=None)
        return out

    @app.post("/api/live/replay")
    def live_replay() -> dict:
        from blue_team import scenario as sc
        st = sc.load_state()
        if st.get("mode") != "live" or not st.get("before"):
            raise HTTPException(400, "no live attack yet: start one")
        if not scenario_status()["approved"]:
            raise HTTPException(400, "no approved playbook yet: two analysts approve on the Playbooks tab")
        return scenario_job(lambda: sc.rerun_live(log=lambda *_: None))

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
        print(f"RUKO Analyst Console (demo database {sc.DB}): http://127.0.0.1:{port}  (Ctrl+C to stop)")
    else:
        app = create_app()
        print(f"RUKO Analyst Console: http://127.0.0.1:{port}  (Ctrl+C to stop)")
    # HOST=0.0.0.0 only inside the hosting container (Dockerfile); locally it stays on 127.0.0.1.
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=port, log_level="warning")
