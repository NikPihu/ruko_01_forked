"""The whole loop on one small world: new scams get through, the blue team learns them, two analysts
approve, and the same payments go through the engine again.

    python -m blue_team scenario start [--new a,b] [--known x,y,z] [--llm auto|offline|bedrock]
    python -m blue_team app --scenario          # Playbooks page: two analysts approve the drafts
    python -m blue_team scenario rerun          # the same payments again, with the approved playbooks
    python -m blue_team scenario status

1. A sim_v2 world where two red-team playbooks (new to RUKO) and three known scams attack.
2. Round 1: every payment of that world through the real engine (Nikunj's record stream,
   synthetic_playbook/interface_script/records.py), as a phone would send it.
3. The blue team on the victims' complaints: HDBSCAN -> generator agent -> analyst agent -> queue.
4. People approve (two analysts) in the console started with --scenario.
5. Round 2: the same records through a fresh engine whose playbook file has the approved entries.

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
LOG = HOME / "log.txt"                  # every step's line, for the console's Demo page
INTERRUPT = ("T2", "T3", "T4")


LOCK = config.HERE / "scenario.lock"    # outside HOME, which start() deletes


class Busy(RuntimeError):
    pass


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

def stream(world: Path, out: Path) -> None:
    """Runs in its own process (the engine reads RUKO_PLAYBOOKS when imported): every record of the
    world to a local engine, as run.py does, and every payment's answer to payments.csv."""
    import pandas as pd
    from interface_script import records
    from interface_script.server import open_local
    s = settings()
    seen = _watch_policy()
    srv = open_local(world, "ml")
    rows = []
    try:
        for rec in records.stream(world, seed=s["seed"], warmup_days=s["warmup_days"], normal_sample=1.0):
            if rec["kind"] == "episode":
                srv.post("/v1/episode", rec["body"])
                continue
            if rec["kind"] != "pay":
                continue
            body, label = rec["body"], rec["label"]
            status, reply = srv.post("/v1/decide", body)
            threat = (reply or {}).get("threat") or {}
            rows.append({"tx_id": label["tx_id"], "ts": label["ts"], "user_id": label["user_id"],
                         "journey_id": label["journey_id"], "playbook": label["playbook"], "is_scam": label["is_scam"],
                         "judged": label["judge"], "status": status, "tier": (reply or {}).get("tier"),
                         "named": (reply or {}).get("playbook"), "threat_level": threat.get("level"),
                         "fail_open": bool((reply or {}).get("fail_open")),
                         **seen.pop(body["request_id"], {})})
            srv.post("/v1/payment/outcome", {"request_id": body["request_id"], "user_id": body["user_id"],
                                             "payee_upi_id": body["payee_upi_id"], "amount_inr": body["amount_inr"],
                                             "status": "completed", "ts": body["ts"]})
    finally:
        srv.close()
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "payments.csv", index=False)
    (out / "health.json").write_text(json.dumps({"playbooks": os.environ.get("RUKO_PLAYBOOKS", "engine default")}),
                                     encoding="utf-8")


def _watch_policy() -> dict:
    """{request_id: what the engine decided inside}: its internal playbook name (the reply shows one
    only at T1+), whether two analysts approved it and its families, and the policy steps that set the
    tier. Wraps the engine's own build_features and Policy.decide in this process; nothing changes."""
    import api.main as engine
    from api.policy import Policy
    seen: dict = {}
    current: dict = {}
    build, decide = engine.build_features, Policy.decide

    def build_features(req, *a, **k):
        current["id"] = req.request_id
        return build(req, *a, **k)

    def watched(self, s, *a, **k):
        d = decide(self, s, *a, **k)
        fam = s.get("playbook_families")
        seen[current.get("id")] = {"inner_name": s.get("playbook"), "approved_families": "+".join(fam) if fam else "",
                                   "policy_steps": "|".join(d.applied), "lit": "+".join(d.lit_families)}
        return d

    engine.build_features = build_features
    Policy.decide = watched
    return seen


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


def live_round(name: str, playbooks_file: Path | None, log=print) -> dict:
    out = LIVE / name
    env = _env({"RUKO_PLAYBOOKS": str(playbooks_file)} if playbooks_file else None)
    log(f"round '{name}': every payment of the world through the engine"
        + (f" with {playbooks_file.name}" if playbooks_file else " as it is"))
    with open(HOME / f"{name}.log", "w", encoding="utf-8") as fh:
        rc = subprocess.run([sys.executable, "-m", "blue_team.scenario", "stream", str(WORLD), str(out)],
                            cwd=config.REPO, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    if rc:
        raise RuntimeError(f"round {name} failed (exit {rc}); see {HOME / f'{name}.log'}")
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
    if HOME.exists():
        shutil.rmtree(HOME)
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


def main() -> None:
    if len(sys.argv) == 4 and sys.argv[1] == "stream":
        stream(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        sys.exit("internal: python -m blue_team.scenario stream <world> <out> (use python -m blue_team scenario ...)")


if __name__ == "__main__":
    main()
