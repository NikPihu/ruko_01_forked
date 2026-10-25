"""The whole loop on one small world: new scams get through, the blue team learns them, two analysts
approve, and the same payments go through the engine again.

    python -m blue_team scenario start [--new a,b] [--known x,y,z] [--llm auto|offline|bedrock]
    python -m blue_team app --scenario          # Playbooks page: two analysts approve the drafts
    python -m blue_team scenario rerun          # the same payments again, with the approved playbooks
    python -m blue_team scenario status

1. A sim_v2 world where two red-team playbooks (new to RUKO) and three known scams attack.
2. Round 1: every payment of that world through the real engine (the attack runner's record stream,
   synthetic_playbook/interface_script/records.py), as a phone would send it.
3. The blue team on the victims' complaints: HDBSCAN -> generator agent -> analyst agent -> queue.
4. People approve (two analysts) in the console started with --scenario.
5. Round 2: the same records through a fresh engine whose playbook file has the approved entries.

The live loop (`start_live` / `rerun_live`, the console's Live tab) is the same machinery for one
attack, made visible: every scam payment, every false alarm and a sample of honest payments are written
to a feed one at a time, paced (pause / step / speed from the console), as they hit the real engine; when
the attack's payments got through, the blue team runs on the victims' complaints in the same feed, waits
for two analysts, and the replay sends the same payments again with the approved playbooks.

Everything lives in blue_team/scenario/ (git ignored), with its own playbook database, so the real
review queue is never touched. The answer key (which journey ran which playbook) is used only to
report results (CLAUDE.md rule 9).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from blue_team import config, playbook_db

HOME = config.HERE / "scenario"
WORLD, TABLE, RUNS, DB, EXPORTS, LIVE = (HOME / "world", HOME / "table.parquet", HOME / "runs", HOME / "playbooks",
                                         HOME / "exports", HOME / "live")
STATE = HOME / "scenario.json"
FEED = HOME / "feed.jsonl"              # the live loop's timeline: one JSON line per payment shown or step
CONTROL = HOME / "control.json"         # the live loop's pacing: {"paused": bool, "delay": s, "steps": n}
SELECTION = HOME / "live_selection.json"  # the live session's transactions: tx ids, journeys, window start
WORLD_LIVE = HOME / "world_live"        # the world as the blue team sees it in a live session: its complaints only
CHILDREN = HOME / "children.json"       # the processes a session started, so Stop can end them
LOG = HOME / "log.txt"                  # every step's line, for the console's Demo page
INTERRUPT = ("T2", "T3", "T4")


LOCK = config.HERE / "scenario.lock"    # outside HOME, which start() deletes


class Busy(RuntimeError):
    pass


class Cancelled(RuntimeError):
    """The console's Stop & clear ended the session."""


def cancelled() -> bool:
    return bool(control().get("cancel"))


def _children() -> list[int]:
    try:
        return [int(p) for p in json.loads(CHILDREN.read_text(encoding="utf-8"))]
    except (OSError, ValueError):
        return []


def _remember(pid: int, add: bool) -> None:
    pids = set(_children())
    pids.add(pid) if add else pids.discard(pid)
    HOME.mkdir(parents=True, exist_ok=True)
    CHILDREN.write_text(json.dumps(sorted(pids)), encoding="utf-8")


def _start_child(cmd: list[str], log_path: Path, env: dict) -> subprocess.Popen:
    """A session's process, remembered so Stop can end it; refused once Stop was pressed."""
    if cancelled():
        raise Cancelled("stopped")
    fh = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=config.REPO, env=env, stdout=fh, stderr=subprocess.STDOUT)
    fh.close()                                      # the child has its own handle
    _remember(proc.pid, True)
    return proc


def _wait_child(proc: subprocess.Popen, what: str, log_path: Path) -> None:
    import time
    while proc.poll() is None:
        time.sleep(0.5)
    _remember(proc.pid, False)
    if cancelled():
        raise Cancelled("stopped")
    if proc.returncode:
        raise RuntimeError(f"{what} failed (exit {proc.returncode}); see {log_path}")


def stop_children() -> int:
    """End every process the session started, with their own children (Stop & clear)."""
    n = 0
    for pid in _children():
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                import signal
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            n += 1
        except (OSError, ProcessLookupError):
            pass
    return n


def stop_and_clear(wait_for=None, timeout: float = 60.0) -> dict:
    """Stop & clear: refuse new steps, end the session's processes, wait for its thread (`wait_for`,
    the console's job) to notice, then empty the demo folder."""
    import time
    control(cancel=True)
    killed = stop_children()
    if wait_for is not None:
        t0 = time.time()
        while wait_for() and time.time() - t0 < timeout:
            stop_children()
            time.sleep(0.5)
        if wait_for():
            raise Busy("the session is still stopping (the world builder cannot be interrupted); try again in a few seconds")
    _clear_home()
    return {"stopped_processes": killed}


class _Lock:
    """One demo step at a time across processes (console and command line): an OS lock on LOCK,
    released when the step ends or its process dies. A second start would otherwise delete the
    world a running round is still reading."""

    def __enter__(self):
        self.fh = open(LOCK, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            raise Busy("a demo step is already running (console or command line); wait for it to finish") from None
        return self

    def __exit__(self, *exc):
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.fh.close()


def _clear_home() -> None:
    """Empty HOME for a new demo, keeping the folder itself: on Windows a folder that any process has
    open (a terminal or Explorer sitting in it) cannot be deleted, but its contents can. Busy files are
    retried for a few seconds, then named."""
    import shutil
    import time
    HOME.mkdir(parents=True, exist_ok=True)
    for child in list(HOME.iterdir()):
        for attempt in range(10):
            try:
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                break
            except FileNotFoundError:
                break
            except PermissionError as e:
                if attempt == 9:
                    raise RuntimeError(f"cannot clear the old demo: {e.filename or child} is open in another program "
                                       "(close it, e.g. an editor, a terminal or Explorer window in that folder, and start again)") from None
                time.sleep(0.5)


def busy() -> bool:
    try:
        with _Lock():
            return False
    except Busy:
        return True


def settings() -> dict:
    return config.load()["scenario"]


def _env(extra: dict | None = None) -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": os.pathsep.join(str(config.REPO / p) for p in ("backend", "ml", "data", "synthetic_playbook",
                                                                       "red_team_blue_team"))}
    env.pop("RUKO_PLAYBOOKS", None)
    env.update(extra or {})
    return env


def _save(state: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


# ---- one round: every record of the world through the real engine ---------------------------------

def stream(world: Path, out: Path, feed: Path | None = None, round_name: str = "before") -> None:
    """Runs in its own process (the engine reads RUKO_PLAYBOOKS when imported): every record of the
    world to a local engine, as run.py does, and every payment's answer to payments.csv. With `feed`
    (the live loop), the payments worth watching also go to the feed, one at a time, paced."""
    import pandas as pd
    from interface_script import records
    from interface_script.server import open_local
    s = settings()
    seen = _watch_policy()
    srv = open_local(world, "ml")
    rows = []
    pace = _Pacer() if feed else None
    every = s.get("live", {}).get("honest_every", 30)
    n_pay = n_honest = shown = 0
    sel = json.loads(Path(os.environ["RUKO_LIVE_SELECTION"]).read_text(encoding="utf-8")) \
        if feed and os.environ.get("RUKO_LIVE_SELECTION") else None
    picked = set(sel["tx_ids"]) if sel else set()
    window = datetime.fromisoformat(sel["window_start"]) if sel else None
    reported: set[tuple] = set()                 # (journey, payee): one complaint per victim per account
    if feed:
        app = srv._c.app
        emit({"kind": "stage", "stage": "attack" if round_name == "before" else "replay",
              "text": f"Engine {app.state.model_version} · fused threat {'on' if app.state.fusion else 'off'} · "
                      f"playbooks {'with the approved ones' if os.environ.get('RUKO_PLAYBOOKS') else 'as shipped'}. "
                      "The first days build each user's history; the attack follows."}, feed)
    try:
        for rec in records.stream(world, seed=s["seed"], warmup_days=s["warmup_days"], normal_sample=1.0):
            if rec["body"].get("ts"):
                srv.clock(rec["body"]["ts"])         # the mock services answer as of this message's time
            if rec["kind"] == "episode":
                srv.post("/v1/episode", rec["body"])
                continue
            if rec["kind"] != "pay":
                continue
            body, label = rec["body"], rec["label"]
            in_window = sel is not None and datetime.fromisoformat(label["ts"]) >= window
            if in_window and str(label["tx_id"]) not in picked:
                continue                                 # only the session's transactions after the warm-up
            if in_window:
                label = {**label, "judge": True}
            elif sel is not None:
                label = {**label, "judge": False}        # the warm-up: history, not shown, not scored
            status, reply = srv.post("/v1/decide", body)
            threat = (reply or {}).get("threat") or {}
            if feed:
                n_pay += 1
                inner = seen.get(body["request_id"], {})
                tier = (reply or {}).get("tier")
                honest = not label["is_scam"]
                if label["judge"] and honest:
                    n_honest += 1
                show = label["judge"] and (sel is not None or label["is_scam"] or tier in INTERRUPT or n_honest % every == 1)
                if show:
                    pace.wait()
                    shown += 1
                    emit({**_payment_event(round_name, body, label, reply, inner, n_pay), "shown": shown,
                          "of": len(picked) if sel else None}, feed)
                    key = (label["journey_id"], body["payee_upi_id"])
                    if label["is_scam"] and tier not in INTERRUPT and key not in reported:
                        reported.add(key)                # it got through: the victim reports it (1930)
                        emit({"kind": "complaint", "round": round_name, "source": "1930",
                              "filed_at": label["ts"], "accounts": [body["payee_upi_id"]]}, feed)
                elif n_pay % 2000 == 0:
                    emit({"kind": "progress", "round": round_name, "payments": n_pay,
                          "text": f"{n_pay:,} payments through the engine so far"}, feed)
            rows.append({"tx_id": label["tx_id"], "ts": label["ts"], "user_id": label["user_id"],
                         "journey_id": label["journey_id"], "playbook": label["playbook"], "is_scam": label["is_scam"],
                         "judged": label["judge"], "status": status, "tier": (reply or {}).get("tier"),
                         "named": (reply or {}).get("playbook"), "threat_level": threat.get("level"),
                         "fail_open": bool((reply or {}).get("fail_open")),
                         **{k: v for k, v in seen.pop(body["request_id"], {}).items() if not k.startswith("_")}})
            srv.post("/v1/payment/outcome", {"request_id": body["request_id"], "user_id": body["user_id"],
                                             "payee_upi_id": body["payee_upi_id"], "amount_inr": body["amount_inr"],
                                             "status": "completed", "ts": body["ts"]})
    finally:
        srv.close()
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "payments.csv", index=False)
    (out / "health.json").write_text(json.dumps({"playbooks": os.environ.get("RUKO_PLAYBOOKS", "engine default")}),
                                     encoding="utf-8")


def breakthroughs(payments_csv: Path) -> list[dict]:
    """The session's scam payments the engine did not interrupt (below T2), per victim journey. Each
    victim reports them (1930); only these reach the blue team."""
    import pandas as pd
    df = pd.read_csv(payments_csv, low_memory=False)
    df = df[df["judged"].astype(bool) & df["is_scam"].astype(bool) & ~df["tier"].isin(INTERRUPT)]
    return [{"journey_id": str(j), "tx_ids": sorted(map(str, g["tx_id"]))} for j, g in df.groupby("journey_id")]


def _watch_policy() -> dict:
    """{request_id: what the engine decided inside}: its internal playbook name (the reply shows one
    only at T1+), whether two analysts approved it and its families, the policy steps that set the
    tier, and for the live feed the scam steps it saw, the model's and the playbook search's parts of
    the fused threat. Wraps the engine's own functions in this process; nothing changes."""
    import api.main as engine
    from api import playbook_search
    from api.policy import Policy
    seen: dict = {}
    current: dict = {}
    build, decide, search = engine.build_features, Policy.decide, playbook_search.search

    def build_features(req, *a, **k):
        current["id"] = req.request_id
        return build(req, *a, **k)

    def searched(steps, *a, **k):
        current["steps"] = [s for s, v in steps.items() if v]
        return search(steps, *a, **k)

    def watched(self, s, *a, **k):
        d = decide(self, s, *a, **k)
        fam = s.get("playbook_families")
        top = (s.get("playbook_search") or [None])[0]
        seen[current.get("id")] = {"inner_name": s.get("playbook"), "approved_families": "+".join(fam) if fam else "",
                                   "policy_steps": "|".join(d.applied), "lit": "+".join(d.lit_families),
                                   "_steps": current.get("steps", []), "_parts": s.get("threat_parts"),
                                   "_match": {k: top[k] for k in ("name", "similarity", "matched")} if top else None,
                                   "_reasons": s.get("reasons", [])}
        return d

    engine.build_features = build_features
    playbook_search.search = searched
    Policy.decide = watched
    return seen


def emit(event: dict, feed: Path | None = None) -> None:
    """One line of the live loop's timeline (the console polls it)."""
    feed = feed or FEED
    feed.parent.mkdir(parents=True, exist_ok=True)
    with open(feed, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": datetime.now().strftime("%H:%M:%S"), **event}, default=str) + "\n")


def feed_since(n: int) -> tuple[list[dict], int]:
    if not FEED.exists():
        return [], 0
    lines = FEED.read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines[n:]], len(lines)


def control(**change) -> dict:
    """The live loop's pacing, shared by the console (writes) and the streaming process (reads)."""
    cur = {"paused": False, "delay": settings().get("live", {}).get("delay_s", 1.2), "steps": 0}
    if CONTROL.exists():
        try:
            cur.update(json.loads(CONTROL.read_text(encoding="utf-8")))
        except ValueError:
            pass
    if change:
        if change.pop("step", False):
            cur["steps"] = int(cur.get("steps", 0)) + 1
        cur.update({k: v for k, v in change.items() if v is not None})
        HOME.mkdir(parents=True, exist_ok=True)
        CONTROL.write_text(json.dumps(cur), encoding="utf-8")
    return cur


class _Pacer:
    """Waits between shown payments: the delay, or while paused until the console sends a step."""

    def __init__(self):
        self.used = int(control().get("steps", 0))

    def wait(self) -> None:
        import time
        c = control()
        while c.get("paused") and int(c.get("steps", 0)) <= self.used:
            time.sleep(0.25)
            c = control()
        if c.get("paused"):
            self.used = int(c.get("steps", 0))
            return
        self.used = int(c.get("steps", 0))
        time.sleep(max(0.0, float(c.get("delay", 1.2))))


def _payment_event(round_name: str, body: dict, label: dict, reply: dict | None, inner: dict, n: int) -> dict:
    ctx = body.get("context") or {}
    call, dev = ctx.get("call") or {}, ctx.get("device") or {}
    tier = (reply or {}).get("tier")
    threat = (reply or {}).get("threat") or {}
    scam = bool(label["is_scam"])
    verdict = ("caught" if tier in INTERRUPT else "warned only" if tier == "T1" else "missed") if scam else \
              ("false alarm" if tier in INTERRUPT else "ok")
    return {"kind": "payment", "round": round_name, "n": n, "ts": body["ts"], "user": "u…" + str(body["user_id"])[-4:],
            "payee": body["payee_upi_id"], "amount": body["amount_inr"], "entry": body.get("entry_method"),
            "payer_says": body.get("payer_says"),
            "phone": {"call": bool(call.get("active")), "call_kind": call.get("kind"),
                      "unknown_caller": call.get("caller_in_contacts") is False, "remote": bool(dev.get("remote_access_active")),
                      "lures": [x.get("tag") for x in ctx.get("lures") or []],
                      "verdict": (ctx.get("device_verdict") or {}).get("level")},
            "red": {"scam": scam, "playbook": label.get("playbook"), "journey": label.get("journey_id"),
                    "step": label.get("journey_pay_index")},
            "engine": {"tier": tier, "score": threat.get("score"), "level": threat.get("level"),
                       "named": (reply or {}).get("playbook") or inner.get("inner_name"), "reasons": inner.get("_reasons") or (reply or {}).get("reasons", []),
                       "fail_open": bool((reply or {}).get("fail_open")), "steps": inner.get("_steps", []),
                       "parts": inner.get("_parts"), "match": inner.get("_match"),
                       "policy": inner.get("policy_steps", "")},
            "verdict": verdict}


def why_missed(r) -> str:
    """Why a scam payment was not stopped, from the engine's own decision."""
    def text(v) -> str:                              # a CSV round trip turns empty cells into NaN
        return v if isinstance(v, str) else ""
    steps, fam = text(r.get("policy_steps")), text(r.get("approved_families"))
    if r.get("fail_open"):
        return "the engine failed open (no answer in time)"
    if fam and "+" not in fam:
        return "an approved playbook named it, but its conditions are one family (rule 5): name only"
    if "trusted_payee" in steps:
        return "the user marked the payee as trusted"
    if "amount_cap" in steps:
        return "a small payment (amount cap)"
    if "alert_budget" in steps:
        return "the user's alert budget was used up"
    if fam:
        return "an approved playbook matched; another policy step lowered it"
    name = r.get("inner_name")
    if isinstance(name, str) and name:
        return f"named {name}, but the model scored it low"
    return "no playbook matched and the model scored it low"


def live_round(name: str, playbooks_file: Path | None, log=print, feed: Path | None = None) -> dict:
    out = LIVE / name
    extra = {"RUKO_PLAYBOOKS": str(playbooks_file)} if playbooks_file else {}
    if feed and SELECTION.exists():
        extra["RUKO_LIVE_SELECTION"] = str(SELECTION)
    env = _env(extra)
    log(f"round '{name}': every payment of the world through the engine"
        + (f" with {playbooks_file.name}" if playbooks_file else " as it is"))
    log_path = HOME / f"{name}.log"
    proc = _start_child([sys.executable, "-m", "blue_team.scenario", "stream", str(WORLD), str(out), name]
                        + ([str(feed)] if feed else []), log_path, env)
    _wait_child(proc, f"round {name}", log_path)
    return summarise(out / "payments.csv")


def summarise(path: Path) -> dict:
    """Per scam type: its payments after the warm-up, how many RUKO interrupted (T2+), warned (T1+),
    named; and honest payments interrupted per 1,000."""
    import pandas as pd
    df = pd.read_csv(path, low_memory=False)
    df = df[df["judged"].astype(bool)]
    scam = df[df["is_scam"].astype(bool)]
    out = {"types": {}}
    for pb, g in scam.groupby("playbook"):
        out["types"][pb] = {"payments": int(len(g)), "journeys": int(g["journey_id"].nunique()),
                            "interrupted": int(g["tier"].isin(INTERRUPT).sum()),
                            "warned": int(g["tier"].isin(("T1",) + INTERRUPT).sum()),
                            "named_as": dict(Counter(g["named"].dropna())),
                            "fail_open": int(g["fail_open"].sum()),
                            "missed_because": (dict(Counter(why_missed(r) for _, r in g[~g["tier"].isin(INTERRUPT)].iterrows()))
                                               if "policy_steps" in g else {})}
    legit = df[~df["is_scam"].astype(bool)]
    out["honest_payments"] = int(len(legit))
    out["honest_interrupted_per_1000"] = round(1000 * float(legit["tier"].isin(INTERRUPT).mean()), 2) if len(legit) else None
    return out


# ---- start ---------------------------------------------------------------------------------------

def start(new: list[str], known: list[str], provider: str | None = None, log=print) -> dict:
    with _Lock():
        return _start(new, known, provider, log)


def _start(new: list[str], known: list[str], provider: str | None, log) -> dict:
    import shutil

    from blue_team import pipeline, redteam
    s = settings()
    _clear_home()
    (HOME / "red").mkdir(parents=True)
    by_name = {pb["name"]: pb for pb in redteam.load()}
    for n in new:
        if n not in by_name:
            raise ValueError(f"{n} is not a red-team playbook (red_team/playbooks)")
        shutil.copy(redteam.RED_DIR / by_name[n]["file"], HOME / "red" / by_name[n]["file"])
    shutil.copytree(config.PLAYBOOKS / "known", DB / "known")
    log = _logger(log)
    state = {"started": _now(), "new": new, "known": known, "step": "world"}
    _save(state)

    log(f"1/4 world: {s['users']} users x {s['days']} days; new to RUKO: {', '.join(new)}; known: {', '.join(known)}")
    redteam.build_world(WORLD, s["users"], s["days"], s["seed"], s["victim_rate"], s["new_boost"],
                        red_dir=HOME / "red", log=log, known=known, known_boost=s["known_boost"])
    rc = subprocess.run([sys.executable, "-m", "dataset.replay", "--data", str(WORLD), "--out", str(TABLE),
                         "--warmup-days", str(s["warmup_days"])], cwd=config.REPO, env=_env(),
                        stdout=open(HOME / "replay.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT).returncode
    if rc:
        raise RuntimeError(f"replay failed (exit {rc}); see {HOME / 'replay.log'}")

    log("2/4 round 1: the payments through the engine as it is")
    state.update(step="round1")
    _save(state)
    state.update(before=live_round("before", None, log))
    _save(state)
    log(report(state["before"], None, new))

    log("3/4 the blue team on the victims' complaints (HDBSCAN -> generator agent -> analyst agent)")
    state.update(step="review")
    _save(state)
    r = pipeline.run(TABLE, WORLD, provider=provider, out_root=RUNS, playbook_root=DB, log=log)
    state.update(step="review", run_id=r["run_id"], agents=r.get("agents"))
    _save(state)
    queued = sorted(p.stem for p in (DB / "review").glob("*.yaml"))
    log(f"4/4 {len(queued)} playbook(s) wait for two analysts: {', '.join(queued) or 'none'}")
    log("    approve them on the Playbooks page:  python -m blue_team app --scenario   (two different names)")
    log("    then:                                python -m blue_team scenario rerun")
    return state


def _logger(log):
    """Print through `log` and append to LOG, so the console shows the same lines."""
    def say(line: str) -> None:
        log(line)
        HOME.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().strftime('%H:%M:%S')}  {line}\n")
    return say


def log_tail(n: int = 120) -> list[str]:
    return LOG.read_text(encoding="utf-8").splitlines()[-n:] if LOG.exists() else []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def redraft(provider: str | None = None, log=print) -> dict:
    """Step 3 again on the same world and round 1 (no 12-minute rebuild): drops the drafts waiting for
    review or rejected in the demo database, keeps approved ones, runs the blue team again."""
    with _Lock():
        from blue_team import pipeline
        log = _logger(log)
        state = load_state()
        if not state.get("before"):
            raise RuntimeError("no demo yet: start one")
        for s in ("review", "rejected"):
            for f in (DB / s).glob("*.yaml") if (DB / s).exists() else []:
                f.unlink()
        log("3/4 again: the blue team on the same complaints (HDBSCAN -> generator agent -> analyst agent)")
        state.update(step="review")
        _save(state)
        r = pipeline.run(TABLE, WORLD, provider=provider, out_root=RUNS, playbook_root=DB, log=log)
        state.update(step="review", run_id=r["run_id"], agents=r.get("agents"))
        _save(state)
        queued = sorted(p.stem for p in (DB / "review").glob("*.yaml"))
        log(f"4/4 {len(queued)} playbook(s) wait for two analysts: {', '.join(queued) or 'none'}")
        return state


# ---- rerun ---------------------------------------------------------------------------------------

def playbooks_file(cards: list[dict], out: Path) -> tuple[Path, list[str]]:
    """The engine's playbook file plus every approved card that the format can express."""
    from api.playbooks import parse

    from blue_team import engine_file
    doc = yaml.safe_load(engine_file.engine_path().read_text(encoding="utf-8"))
    skipped = []
    for card in cards:
        text, problems = engine_file.export_entry(card)
        if problems:
            skipped.append(f"{card['name']}: {'; '.join(problems)}")
            continue
        names = [p["name"] for p in doc["playbooks"]]
        at = names.index(card["misnamed_as"]) if card.get("misnamed_as") in names else len(names)
        doc["playbooks"].insert(at, yaml.safe_load(text)[0])
    doc["version"] = f"{doc.get('version', '?')}+scenario"
    parse(doc)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "playbooks_with_approved.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path, skipped


def rerun(log=print) -> dict:
    with _Lock():
        return _rerun(log)


def _rerun(log) -> dict:
    log = _logger(log)
    state = load_state()
    if not state.get("before"):
        raise RuntimeError("no scenario yet: python -m blue_team scenario start")
    approved = [pb.card for pb in playbook_db.load(("approved",), DB)]
    if not approved:
        raise RuntimeError("no approved playbook yet: approve on the Playbooks page (python -m blue_team app --scenario)")
    path, skipped = playbooks_file(approved, HOME)
    for s in skipped:
        log(f"not in the engine file (format): {s}")
    log(f"round 2 with {len(approved) - len(skipped)} approved playbook(s): {', '.join(c['name'] for c in approved)}")
    state.update(step="round2")
    _save(state)
    state.update(step="done", approved=[c["name"] for c in approved], skipped=skipped,
                 after=live_round("after", path, log), rerun_at=_now())
    _save(state)
    log(report(state["before"], state["after"], state["new"]))
    return state


# ---- the live loop: two or three attacks, a fixed set of transactions, one at a time --------------

def select_live(world: Path, attacks: list[str], total: int, scam_share: float, warmup_days: float, seed: int) -> dict:
    """The live session's transactions, chosen before anything is sent: whole victim journeys of the
    chosen attacks (round robin, so each attack gets its share) up to `scam_share` of `total`, then
    honest payments by RUKO users spread over the same days, to `total` in all. Only journeys that start
    after the warm-up are taken; the warm-up days are the users' history, sent quietly before."""
    import numpy as np
    import pandas as pd

    from dataset.replay import world_start
    led = pd.read_parquet(world / "ledger.parquet", columns=["tx_id", "ts", "from_upi", "journey_id", "label_is_scam"])
    jr = pd.read_parquet(world / "journeys.parquet", columns=["journey_id", "playbook"])
    users = set(pd.read_parquet(world / "users.parquet", columns=["upi_id"])["upi_id"])
    start = world_start(json.loads((world / "manifest.json").read_text(encoding="utf-8")))
    window = pd.Timestamp(start) + pd.Timedelta(days=warmup_days)
    led = led[led["from_upi"].isin(users)]
    scam = led[led["label_is_scam"].astype(bool) & led["journey_id"].notna()].merge(jr, on="journey_id")
    first = scam.groupby("journey_id")["ts"].min()
    scam = scam[scam["journey_id"].isin(first[first >= window].index) & scam["playbook"].isin(attacks)]
    cap = int(total * scam_share)
    queues = {a: [j for j, _ in sorted(((j, first[j]) for j in scam.loc[scam["playbook"] == a, "journey_id"].unique()),
                                        key=lambda x: x[1])] for a in attacks}
    size = scam.groupby("journey_id").size()
    chosen, n = [], 0
    while any(queues.values()):
        for a in attacks:
            if queues[a] and n + size[queues[a][0]] <= cap:
                j = queues[a].pop(0)
                chosen.append(j)
                n += int(size[j])
            elif queues[a]:
                queues[a] = []                       # the next journey would not fit: this attack is done
    scam_tx = scam.loc[scam["journey_id"].isin(chosen), "tx_id"].tolist()
    honest = led[~led["label_is_scam"].astype(bool) & (led["ts"] >= window)]
    k = min(len(honest), total - len(scam_tx))
    idx = np.sort(np.random.default_rng(seed).choice(len(honest), size=k, replace=False)) if k > 0 else []
    honest_tx = honest.iloc[idx]["tx_id"].tolist()
    per = scam.loc[scam["journey_id"].isin(chosen)].groupby("playbook").agg(journeys=("journey_id", "nunique"),
                                                                          payments=("tx_id", "size"))
    return {"window_start": window.isoformat(), "tx_ids": sorted(map(str, scam_tx + honest_tx)), "journeys": sorted(chosen),
            "scam_payments": len(scam_tx), "honest_payments": len(honest_tx),
            "per_attack": {a: {"journeys": int(per.loc[a, "journeys"]) if a in per.index else 0,
                               "payments": int(per.loc[a, "payments"]) if a in per.index else 0} for a in attacks}}


def world_for_blue_team(world: Path, through: list[dict], out: Path) -> Path:
    """A copy of the world whose only complaints are the session's breakthroughs (`breakthroughs()`):
    one 1930 complaint per victim and account a payment got through to, filed a day after it, naming
    that account. The world's own complaints (victims who were warned and paid anyway, or who never
    reported) are left out, so the blue team works on what broke through and nothing else. The honest
    payments it measures false alarms on stay the whole world's: a few hundred are too few to tell
    0.5 per 1,000 apart."""
    import shutil

    import pandas as pd
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(world, out)
    led = pd.read_parquet(world / "ledger.parquet", columns=["tx_id", "ts", "to_upi", "journey_id"])
    led = led.assign(tx_id=led["tx_id"].astype(str))
    want = {t for b in through for t in b["tx_ids"]}
    rows = []
    for (j, payee), g in led[led["tx_id"].isin(want)].groupby(["journey_id", "to_upi"], sort=True):
        filed = g["ts"].max() + pd.Timedelta(days=1)
        rows.append({"report_id": f"live_{len(rows) + 1:04d}", "identifier_type": "upi_id", "identifier": str(payee),
                     "journey_id": str(j), "filed_at": filed, "listed_at": filed + pd.Timedelta(days=1),
                     "source": "1930", "is_false": False})
    cols = list(pd.read_parquet(world / "reports.parquet").columns)
    pd.DataFrame(rows, columns=cols).to_parquet(out / "reports.parquet", index=False)
    return out




MIN_TX, MAX_TX = 100, 5000             # a live session's size, chosen on the Live tab


def start_live(attacks: list[str] | str, provider: str | None = None, log=print, transactions: int | None = None) -> dict:
    with _Lock():
        return _start_live([attacks] if isinstance(attacks, str) else list(attacks), provider, log, transactions)


def _start_live(attacks: list[str], provider: str | None, log, transactions: int | None = None) -> dict:
    import shutil
    import time

    from blue_team import pipeline, redteam
    s, lv = settings(), settings()["live"]
    by_name = {pb["name"]: pb for pb in redteam.load()}
    bad = [a for a in attacks if a not in by_name]
    if bad or not 1 <= len(attacks) <= 3 or len(set(attacks)) != len(attacks):
        raise ValueError(f"pick one to three different red-team playbooks (unknown: {', '.join(bad) or 'none'})")
    _clear_home()
    (HOME / "red").mkdir(parents=True)
    for a in attacks:
        shutil.copy(redteam.RED_DIR / by_name[a]["file"], HOME / "red" / by_name[a]["file"])
    shutil.copytree(config.PLAYBOOKS / "known", DB / "known")
    control(paused=False, cancel=False)
    log = _logger(log)
    known = lv["known"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")      # the blue team's run, known from the start
    state = {"started": _now(), "mode": "live", "new": attacks, "known": known, "step": "world", "run_id": run_id}
    _save(state)
    emit({"kind": "stage", "stage": "world", "text": f"Red team picked {len(attacks)} attacks: "
          + "; ".join(f"'{a}' ({by_name[a]['title']})" for a in attacks)
          + f". Building a world of {s['users']} people over {s['days']} days where they attack"
          + (f", next to {', '.join(known)} (known to RUKO)" if known else "") + "."})
    redteam.build_world(WORLD, s["users"], s["days"], s["seed"], s["victim_rate"], s["new_boost"],
                        red_dir=HOME / "red", log=log, known=known, known_boost=s["known_boost"])
    total = int(transactions or lv["transactions"])
    if not MIN_TX <= total <= MAX_TX:
        raise ValueError(f"transactions: {MIN_TX:,} to {MAX_TX:,}")
    sel = select_live(WORLD, attacks + known, total, lv["scam_share"], s["warmup_days"], s["seed"])
    SELECTION.write_text(json.dumps(sel), encoding="utf-8")
    state.update(selection={k: v for k, v in sel.items() if k not in ("tx_ids", "journeys")})
    _save(state)
    emit({"kind": "stage", "stage": "world", "text": f"{len(sel['tx_ids'])} transactions picked for the session: "
          f"{sel['scam_payments']} from {len(sel['journeys'])} victims of the attacks ("
          + ", ".join(f"{a} {v['payments']}" for a, v in sel["per_attack"].items()) + f") and {sel['honest_payments']} "
          "honest ones. The first days (each user's history) go to the engine quietly first."})
    # the replayed table is only for the blue team: build it while the attack plays
    replay = _start_child([sys.executable, "-m", "dataset.replay", "--data", str(WORLD), "--out", str(TABLE),
                           "--warmup-days", str(s["warmup_days"])], HOME / "replay.log", _env())
    state.update(step="round1")
    _save(state)
    state.update(before=live_round("before", None, log, feed=FEED))
    _save(state)
    types = state["before"]["types"]
    broke = breakthroughs(LIVE / "before" / "payments.csv")
    through = sum(len(b["tx_ids"]) for b in broke)
    emit({"kind": "summary", "round": "before", "attack": ", ".join(attacks), "types": types,
          "honest_per_1000": state["before"]["honest_interrupted_per_1000"],
          "text": "Attack over: " + "; ".join(f"'{a}' {types.get(a, {}).get('interrupted', 0)} of "
                                              f"{types.get(a, {}).get('payments', 0)} interrupted" for a in attacks)
                  + f". {through} scam payments got through."})
    if not through:
        _wait_child(replay, "replay", HOME / "replay.log")
        state.update(step="done")
        _save(state)
        emit({"kind": "stage", "stage": "done", "text": "RUKO stopped every payment of these attacks: nothing for the "
              "blue team to learn. Pick others."})
        return state

    emit({"kind": "blue", "text": f"{through} payments got through, from {len(broke)} victims; they report them (1930). "
          "The blue team activates on these breakthroughs only."}, FEED)
    _wait_child(replay, "replay", HOME / "replay.log")
    state.update(step="review")
    _save(state)

    # the blue team in its own process (its agents can take minutes; Stop must be able to end them),
    # writing its steps to the same feed
    live_world = world_for_blue_team(WORLD, broke, WORLD_LIVE)
    blue = _start_child([sys.executable, "-m", "blue_team.scenario", "bluerun", str(TABLE), str(live_world),
                         provider or "auto", run_id], HOME / "blue.log", _env())
    _wait_child(blue, "the blue team", HOME / "blue.log")
    summary = json.loads((RUNS / run_id / "summary.json").read_text(encoding="utf-8"))
    state.update(run_id=run_id, agents=summary.get("agents"))
    _save(state)
    queued = sorted(p.stem for p in (DB / "review").glob("*.yaml"))
    emit({"kind": "stage", "stage": "review", "run_id": run_id, "drafts": queued,
          "text": f"{len(queued)} playbook(s) drafted and checked; two different analysts must approve before "
                  "RUKO uses them." if queued else "The blue team drafted nothing it could check: not enough complaints "
                  "in one group yet."})
    return state


def rerun_live(log=print) -> dict:
    with _Lock():
        log = _logger(log)
        state = load_state()
        if state.get("mode") != "live" or not state.get("before"):
            raise RuntimeError("no live attack yet: start one")
        approved = [pb.card for pb in playbook_db.load(("approved",), DB)]
        if not approved:
            raise RuntimeError("no approved playbook yet: two analysts approve on the Playbooks tab")
        path, skipped = playbooks_file(approved, HOME)
        control(paused=False, cancel=False)
        emit({"kind": "stage", "stage": "replay", "text": f"Replaying the same attack with {len(approved) - len(skipped)} "
              f"approved playbook(s) in the engine's file: {', '.join(c['name'] for c in approved)}"
              + (f". Not expressible yet: {'; '.join(skipped)}" if skipped else "")})
        state.update(step="round2")
        _save(state)
        state.update(step="done", approved=[c["name"] for c in approved], skipped=skipped,
                     after=live_round("after", path, log, feed=FEED), rerun_at=_now())
        _save(state)
        bt, at = state["before"]["types"], state["after"]["types"]
        emit({"kind": "summary", "round": "after", "attack": ", ".join(state["new"]), "types": at,
              "honest_per_1000": state["after"]["honest_interrupted_per_1000"],
              "text": "; ".join(f"'{x}' {bt.get(x, {}).get('interrupted', 0)} of {bt.get(x, {}).get('payments', 0)} interrupted "
                                f"before the blue team, {at.get(x, {}).get('interrupted', 0)} of {at.get(x, {}).get('payments', 0)} after"
                                for x in state["new"])
                      + f". Honest interruptions per 1,000: {state['before']['honest_interrupted_per_1000']} → "
                        f"{state['after']['honest_interrupted_per_1000']}."})
        emit({"kind": "stage", "stage": "done", "text": "Loop complete."})
        return state


def report(before: dict, after: dict | None, new: list[str]) -> str:
    lines = ["", f"{'scam type':42s} {'':5s} {'payments':>8s}  {'interrupted (T2+)':>18s}  named as"]
    for pb, b in sorted(before["types"].items(), key=lambda kv: (kv[0] not in new, kv[0])):
        tag = "NEW" if pb in new else "known"
        a = (after or {}).get("types", {}).get(pb)
        cell = f"{b['interrupted']}/{b['payments']}" + (f" -> {a['interrupted']}/{a['payments']}" if a else "")
        names = (a or b)["named_as"]
        lines.append(f"{pb:42s} {tag:5s} {b['payments']:8d}  {cell:>18s}  {', '.join(f'{k} {v}' for k, v in names.items()) or '-'}")
        for why, n in ((a or b).get("missed_because") or {}).items():
            lines.append(f"{'':50s} not stopped: {n} x {why}")
    fa = f"{before['honest_interrupted_per_1000']}" + (f" -> {after['honest_interrupted_per_1000']}" if after else "")
    lines.append(f"honest payments interrupted per 1,000: {fa}  ({before['honest_payments']:,} honest payments)")
    return "\n".join(lines)


def _blue_run(table: Path, world: Path, provider: str, run_id: str) -> None:
    """The live session's blue team, in its own process: every step to the feed."""
    from blue_team import cluster, pipeline
    cluster.SMALL_SET_ONE_GROUP = True               # a handful of breakthroughs is still worth a playbook
    pipeline.run(table, world, provider=None if provider == "auto" else provider, out_root=RUNS, playbook_root=DB,
                 log=lambda line: emit({"kind": "blue", "text": line}), run_id=run_id)


def main() -> None:
    if len(sys.argv) == 6 and sys.argv[1] == "bluerun":
        _blue_run(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5])
        return
    if len(sys.argv) in (4, 5, 6) and sys.argv[1] == "stream":
        stream(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[5]) if len(sys.argv) == 6 else None,
               sys.argv[4] if len(sys.argv) >= 5 else "before")
    else:
        sys.exit("internal: python -m blue_team.scenario stream <world> <out> (use python -m blue_team scenario ...)")


if __name__ == "__main__":
    main()
