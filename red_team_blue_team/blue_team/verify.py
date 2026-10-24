"""Verify an approved playbook: with it, does RUKO now catch the scam it describes?

Two analysts approving a card says the story and the rule look right. This says what it changes,
in three checks, cheapest first. Results go to exports/<name>/verify.json.

1. named (offline, seconds): the engine's playbook file plus this entry, loaded with the engine's
   own parser, run over the replayed payments of the card's world. Share of the scam's payments it
   names, on the complaints it was drafted from and on payments nobody complained about (the
   simulator's answer key, evaluation only: CLAUDE.md rule 9), legit payments named per 1,000, and
   payments it takes from a known playbook. A rule the file format cannot express is measured with
   the blue-team matcher instead and flagged.
2. live (minutes): Nikunj's runner (synthetic_playbook/interface_script) on the scam's playbooks in a
   fresh world (a new seed), the same world judged by several engine set-ups (ARMS): as it is; with
   the entry pasted into its playbook file (RUKO_PLAYBOOKS, only if the format can express it); and a
   PREVIEW with the card's rule in the engine's namer and the contract open to new names
   (verify_engine.py). The contract's FraudType lists six names, so today the real engine fails open
   on a payment it would name with a new one (backend/api/main.py threat_of): the file arm shows it.
3. retrain (optional): LightGBM retrained on its own training table plus the card's complaint-labelled
   payments into exports/<name>/model/ (ml/model/artifacts/v0 is never touched), then check 2's world
   again with RUKO_MODEL pointing at it (alone, and with the preview). A playbook only names a scam;
   interrupting is the model's job.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from blue_team import config, engine_file, matcher, playbook_db, review

INTERRUPT = ("T2", "T3", "T4")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def settings() -> dict:
    return config.load()["verify"]


# ---- the candidate engine file -----------------------------------------------------------------

def candidate_file(card: dict, out: Path, engine: Path | None = None) -> tuple[Path | None, list[str]]:
    """The engine's playbook file with this card's entry where promote() put it (before the playbook
    it corrects, else at the end), checked by the engine's own parser. (None, problems) if the file
    format cannot express the rule yet."""
    from api.playbooks import parse
    entry_yaml, problems = engine_file.export_entry({**card, "approved_by": card.get("approved_by", [])})
    if problems:
        return None, problems
    entry = yaml.safe_load(entry_yaml)[0]
    src = engine or engine_file.engine_path()
    doc = yaml.safe_load(src.read_text(encoding="utf-8"))
    names = [p["name"] for p in doc["playbooks"]]
    at = names.index(card["misnamed_as"]) if card.get("misnamed_as") in names else len(names)
    doc["playbooks"].insert(at, entry)
    doc["version"] = f"{doc.get('version', '?')}+verify:{card['name']}"
    parse(doc)                                       # raises on anything the engine would refuse
    out.mkdir(parents=True, exist_ok=True)
    path = out / "candidate_playbooks.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path, []


def namer(card: dict, cand: Path | None):
    """features -> playbook name after approval, the way the engine would name it."""
    if cand is not None:
        from api.playbooks import parse
        rules = parse(yaml.safe_load(cand.read_text(encoding="utf-8")))
        return lambda f: next((n for n, _, rule in rules if rule(f)), None)
    known = playbook_db.load(("known",))
    pb = playbook_db.Playbook(card["name"], "approved", card,
                              [(int(m["priority"]), matcher.normalize(m["rule"])) for m in card["match"]])
    return lambda f: playbook_db.name_scam(f, known + [pb])


# ---- check 1: named, offline -------------------------------------------------------------------

def _run_paths(card: dict, runs: Path) -> tuple[Path, Path, str, list[str]]:
    ev = card.get("evidence") or {}
    rd = runs / str(ev.get("run_id"))
    st = json.loads((rd / "status.json").read_text(encoding="utf-8"))
    clusters = {c["cluster_id"]: c for c in json.loads((rd / "clusters.json").read_text(encoding="utf-8"))}
    case_ids = clusters[ev["cluster_id"]]["cases"]
    return Path(st["table"]), Path(st["world"]), ev.get("scorer", "ml"), case_ids


def targets(world: Path, case_ids: list[str], min_share: float, max_n: int) -> list[tuple[str, float]]:
    """The scam types (simulator playbooks) behind the card's complaints: answer key, evaluation only."""
    jr = pd.read_parquet(world / "journeys.parquet", columns=["journey_id", "playbook"])
    rep = pd.read_parquet(world / "reports.parquet", columns=["report_id", "journey_id"]).dropna().drop_duplicates("report_id")
    of = dict(zip(jr["journey_id"], jr["playbook"]))
    pb = {r: of.get(j) for r, j in zip(rep["report_id"], rep["journey_id"])}
    cnt = Counter(pb.get(c) for c in case_ids if pb.get(c) is not None)
    n = sum(cnt.values()) or 1
    out = [(p, k / n) for p, k in cnt.most_common() if k / n >= min_share][:max_n]
    return out or [(p, k / n) for p, k in cnt.most_common(1)]


def named_offline(card: dict, runs: Path, out: Path, log=print) -> dict:
    from blue_team import breach
    s = settings()
    table, world, scorer, case_ids = _run_paths(card, runs)
    cand, problems = candidate_file(card, out)
    name_after = namer(card, cand)
    known = playbook_db.load(("known",))
    log(f"check 1: scoring {table.name} as the engine would, before and after '{card['name']}'")
    scored = breach.score(breach.load_table(table), scorer, known)
    comp = breach.complaints(world)
    cases = breach.cases(scored, comp)
    legit = breach.presumed_legit(scored, comp)
    after = pd.Series([name_after(f) for f in scored.feats])
    before = scored.rows["named"].reset_index(drop=True)
    hit = (after == card["name"]).to_numpy()
    w = scored.rows["weight"].to_numpy(float)

    lab = pd.read_parquet(table, columns=["tx_id", "label_is_scam", "playbook"])
    rows = scored.rows[["tx_id"]].reset_index(drop=True).merge(lab, on="tx_id", how="left")
    tgt = targets(world, case_ids, s["min_target_share"], s["max_targets"])
    same = (rows["playbook"].isin([t for t, _ in tgt]) & rows["label_is_scam"].fillna(False).astype(bool)).to_numpy()
    in_case = set(i for rs in cases["rows"] for i in rs)
    mine = set(i for rs in cases.set_index("case_id").loc[[c for c in case_ids if c in set(cases["case_id"])], "rows"]
               for i in rs)
    seen = pd.Series(range(len(rows))).isin(in_case).to_numpy()
    own = pd.Series(range(len(rows))).isin(mine).to_numpy()
    tier = scored.rows["tier"].reset_index(drop=True)

    def share(mask) -> float | None:
        return round(float(hit[mask].mean()), 3) if mask.any() else None

    taken = Counter(b for b, a in zip(before, after) if isinstance(b, str) and a == card["name"] and b != card["name"])
    res = {
        "engine_format": "file" if cand else "not expressible yet: measured with the blue-team matcher",
        "format_problems": problems, "candidate_file": str(cand) if cand else None,
        "world": str(world), "scam_types": [{"playbook": t, "share_of_complaints": round(v, 2)} for t, v in tgt],
        "named_own_complaints": share(own),
        "named_same_scam_complained": share(same & seen),
        "named_same_scam_never_complained": share(same & ~seen),
        "same_scam_payments": {"complained": int((same & seen).sum()), "never_complained": int((same & ~seen).sum())},
        "interrupted_today_same_scam": (round(float(tier[same].isin(INTERRUPT).mean()), 3) if same.any() else None),
        "legit_named_per_1000": round(float(1000 * w[legit & hit].sum() / max(w[legit].sum(), 1e-9)), 3),
        "taken_from_known": dict(taken),
        "contract_names_it": _contract_allows(card["name"]),
    }
    log(f"check 1: names {_pct(res['named_same_scam_never_complained'])} of the scam's payments nobody complained "
        f"about, {res['legit_named_per_1000']} legit per 1,000")
    return res


def _contract_allows(name: str) -> bool:
    import typing

    from schema.events import FraudType
    return name in typing.get_args(FraudType)


def _pct(x) -> str:
    return "–" if x is None else f"{x:.0%}"


# ---- check 2 / 3: live, Nikunj's runner -------------------------------------------------------

def _playbook_ref(name: str, repo: Path) -> str:
    from blue_team import redteam
    for pb in redteam.load():
        if pb["name"] == name:
            return str(redteam.RED_DIR / pb["file"])
    return name                                       # a sim_v2 library name: the runner resolves it


def _summarise(out: Path, name: str) -> dict:
    """`named`: the engine's own decision (named.jsonl); `named_shown`: what the reply carried, which the
    engine shows only at T1+, so a playbook alone is invisible on payments the model lets through."""
    v = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    df = pd.read_csv(out / "results.csv", low_memory=False)
    scam = df[df["judged"].astype(bool) & df["is_scam"].astype(bool)]
    ok = scam[scam["status"] == 200]
    named = None
    if (out / "named.jsonl").exists():
        rec = {}
        for line in (out / "named.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            rec[r["request_id"]] = r["named"]            # the last decision for a payment
        ids = [i for i in scam["tx_id"] if i in rec] if "tx_id" in scam else []
        named = round(sum(rec[i] == name for i in ids) / len(ids), 3) if ids else None
    return {"scam_payments": int(len(scam)), "named": named,
            "named_shown": round(float((ok["fraud_type"] == name).mean()), 3) if len(ok) else None,
            "interrupted": round(float(ok["tier"].isin(INTERRUPT).mean()), 3) if len(ok) else None,
            "called_normal": v["miss_rate"], "false_alarms": v["false_alarm_rate"],
            "fail_open": v["fail_open"], "errors": v["errors"], "breakthrough": v["breakthrough"]}


def runner(ref: str, out: Path, repo: Path, seed: int, env_extra: dict, users: int | None = None) -> tuple[int, Path]:
    """One runner process through verify_engine.py (it drops the runner's blue-team sink, so a
    verification never writes the red-team inbox, and applies the previews env_extra asks for)."""
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": os.pathsep.join(str(repo / p) for p in ("backend", "ml", "data", "synthetic_playbook",
                                                                 "red_team_blue_team"))}
    for k in ("RUKO_PLAYBOOKS", "RUKO_MODEL", "BLUE_VERIFY_CARD", "BLUE_VERIFY_CONTRACT"):
        env.pop(k, None)
    env.update(env_extra)
    cmd = [sys.executable, "-m", "blue_team.verify_engine", "run", "--playbook", ref, "--out", str(out), "--seed", str(seed)]
    if users:
        cmd += ["--users", str(users)]
    with open(out / "runner.log", "w", encoding="utf-8") as fh:
        rc = subprocess.run(cmd, cwd=repo, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    return rc, out


ARMS = {
    "before": "the engine as it is",
    "engine_file": "the engine with the approved entry in its playbook file (RUKO_PLAYBOOKS): names it, and "
                   "policy raises it to a warning when its conditions span two families",
    "preview": "PREVIEW: the card's rule in the engine's namer (the playbooks-0.2 format cannot express it), "
               "without the policy step, which needs an entry in the file",
    "retrained": "the retrained model (RUKO_MODEL), playbooks unchanged",
    "retrained_engine_file": "the retrained model plus the approved entry",
    "retrained_preview": "PREVIEW: the retrained model plus the card's rule in the namer",
}


def live(card: dict, card_path: Path, scam_types: list[str], cand: Path | None, repo: Path, out: Path,
         model: Path | None = None, log=print, stop=lambda: False) -> dict:
    """The same fresh world per scam type, judged by several engine set-ups (ARMS)."""
    s = settings()
    # The real engine with the entry in its file when the format can express it; otherwise a preview.
    after = {"RUKO_PLAYBOOKS": str(cand)} if cand is not None else {"BLUE_VERIFY_CARD": str(card_path)}
    arm = "engine_file" if cand is not None else "preview"
    arms = {"before": {}, arm: after}
    if model is not None:
        arms["retrained"] = {"RUKO_MODEL": str(model)}
        arms[f"retrained_{arm}"] = {"RUKO_MODEL": str(model), **after}
    jobs = [(t, arm, env) for t in scam_types for arm, env in arms.items()]
    log(f"live: {len(scam_types)} scam type(s) x {len(arms)} engine set-ups ({', '.join(arms)}) on a fresh world "
        f"(seed {s['seed']}), {s['workers']} at a time")
    res: dict = {t: {} for t in scam_types}

    def one(job):
        t, arm, env = job
        if stop():
            return
        rc, d = runner(_playbook_ref(t, repo), out / "live" / t / arm, repo, s["seed"], env, s.get("users"))
        r = _summarise(d, card["name"]) if rc == 0 and (d / "verdict.json").exists() else             {"error": f"runner exit {rc}; see {d / 'runner.log'}"}
        res[t][arm] = r
        log(f"live: {t} [{arm}] " + (r.get("error") or f"named {_pct(r['named'])}, interrupted "
                                     f"{_pct(r['interrupted'])}, called normal {_pct(r['called_normal'])}, "
                                     f"fail-open {r['fail_open']}"))

    with ThreadPoolExecutor(max_workers=s["workers"]) as ex:
        list(ex.map(one, jobs))
    return {t: {a: res[t][a] for a in arms if a in res[t]} for t in scam_types}


def retrain(card: dict, runs: Path, out: Path, log=print) -> Path:
    """LightGBM on v0's own training table plus this card's complaint-labelled payments. Only those
    payments are added: the rest of the card's world has no label (unknown is not 'legit', rule 1)."""
    table, _, _, _ = _run_paths(card, runs)
    from model import predict
    base = Path(json.loads(Path(predict.MODEL_PATH).read_text(encoding="utf-8"))["trained_on"])
    if not base.is_absolute():
        base = config.REPO / base
    add = pd.read_parquet(table)
    add = add[add["tx_id"].isin(set(card.get("label_tx_ids", [])))].assign(label_is_scam=True, playbook=card["name"])
    t = pd.concat([pd.read_parquet(base), add], ignore_index=True)
    out.mkdir(parents=True, exist_ok=True)
    tp = out / "train_table.parquet"
    t.to_parquet(tp)
    log(f"retrain: {base.name} ({len(t) - len(add):,} rows) + {len(add)} complaint-labelled payments of '{card['name']}'")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": os.pathsep.join(str(config.REPO / p) for p in ("backend", "ml", "data"))}
    with open(out / "train.log", "w", encoding="utf-8") as fh:
        rc = subprocess.run([sys.executable, "-m", "model.train", "--table", str(tp), "--out", str(out)],
                            cwd=config.REPO, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    if rc:
        raise RuntimeError(f"training failed (exit {rc}); see {out / 'train.log'}")
    return out / "server_model.json"


# ---- the whole thing ---------------------------------------------------------------------------

def verdict(r: dict) -> list[str]:
    """Plain lines a reviewer can act on."""
    out = []
    n = r.get("named") or {}
    if n:
        out.append(f"Named offline: {_pct(n.get('named_same_scam_never_complained'))} of this scam's payments nobody "
                   f"complained about ({_pct(n.get('named_own_complaints'))} of its own complaints), "
                   f"{n.get('legit_named_per_1000')} legit payments per 1,000.")
        if n.get("format_problems"):
            out.append("Not in the engine yet: the playbook file cannot express " + "; ".join(n["format_problems"]) + ".")
    for t, arms in (r.get("live") or {}).items():
        b = arms.get("before") or {}
        if "called_normal" not in b:
            continue
        f, pv = arms.get("engine_file") or {}, arms.get("preview") or {}
        if "called_normal" in f:
            line = (f"Live, {t}, with the approved entry: named {_pct(f['named'])}; interrupted (T2+) "
                    f"{_pct(b['interrupted'])} -> {_pct(f['interrupted'])}; called normal {_pct(b['called_normal'])} -> "
                    f"{_pct(f['called_normal'])}; false alarms {b['false_alarms']:.1%} -> {f['false_alarms']:.1%}")
            if f["fail_open"] > b["fail_open"] + max(2, 0.02 * f["scam_payments"]):
                line += (f". WARNING: fail-open {b['fail_open']} -> {f['fail_open']}: the engine could not finish on "
                         "payments it named; see the runner log before pasting the entry")
            out.append(line + ".")
        if "called_normal" in pv:
            out.append(f"Live, {t}, preview (not expressible in the file yet): named {_pct(pv['named'])} inside the engine, "
                       f"{_pct(pv['named_shown'])} shown to the user (only T1+ shows a name); interrupted {_pct(b['interrupted'])} -> "
                       f"{_pct(pv['interrupted'])}; called normal {_pct(b['called_normal'])} -> {_pct(pv['called_normal'])}. "
                       "Naming alone does not interrupt.")
        rt = arms.get("retrained") or {}
        if "called_normal" in rt:
            out.append(f"After retrain, {t}: interrupted {_pct(b['interrupted'])} -> {_pct(rt['interrupted'])}, "
                       f"called normal {_pct(b['called_normal'])} -> {_pct(rt['called_normal'])}, "
                       f"false alarms {b['false_alarms']:.1%} -> {rt['false_alarms']:.1%}.")
    return out


def verify(name: str, live_check: bool = True, retrain_check: bool = False, root: Path | None = None,
           exports: Path | None = None, runs: Path | None = None, repo: Path | None = None,
           log=print, stop=lambda: False) -> dict:
    card, state = review.load_card(name, root)
    if state != "approved":
        raise review.ReviewError(f"{name} is {state}: only approved playbooks are verified")
    repo, runs = repo or config.REPO, runs or config.RUNS
    out = (exports or review.EXPORTS) / name
    r: dict = {"playbook": name, "started": _now(), "seed": settings()["seed"]}
    r["named"] = named_offline(card, runs, out, log)
    cand = Path(r["named"]["candidate_file"]) if r["named"]["candidate_file"] else None
    scam_types = [t["playbook"] for t in r["named"]["scam_types"]]
    model = retrain(card, runs, out / "model", log) if retrain_check else None
    if live_check or model is not None:
        r["live"] = live(card, (root or config.PLAYBOOKS) / "approved" / f"{name}.yaml", scam_types, cand, repo, out,
                         model, log, stop)
        r["arms"] = ARMS
    r["finished"] = _now()
    r["verdict"] = verdict(r)
    (out / "verify.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
    for line in r["verdict"]:
        log(line)
    return r


def load_result(name: str, exports: Path | None = None) -> dict | None:
    p = (exports or review.EXPORTS) / name / "verify.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
