"""The red team's playbooks, as the blue team sees them: what each one tries, a world where they
attack, and a scorecard of what RUKO and the blue team made of them.

The playbooks are sim_v2 scam scripts (red_team_blue_team/red_team/playbooks/). They are
data: read with yaml.safe_load, never executed. `techniques()` reads each script and names the
evasion tricks it uses, so the console can say *why* a scam might slip through before any run.

`scorecard()` uses the simulator's answer key (which journey ran which playbook) to grade a run.
That is evaluation only: nothing in the blue-team pipeline reads it (CLAUDE.md rule 9).
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pandas as pd
import yaml

from blue_team import config

RED_DIR = config.HERE.parent / "red_team" / "playbooks"
CLAIMS = config.HERE.parent / "red_team" / "attack_manifest.csv"
INTERRUPT = {"T2", "T3", "T4"}

TECHNIQUES = {
    "cool_off": "pays 30+ minutes after the call ends (no live call at Pay: context family C stays dark)",
    "notification_lure": "the hook arrives as a WhatsApp / Telegram / Instagram notification the phone cannot read",
    "sub_threshold_sms": "the SMS hook is worded so the lure model scores it below the 0.6 send threshold",
    "anchor_then_drain": "a tiny first payment to the mule, so later ones go to a 'known payee'",
    "single_bait": "one bait credit only, so the task-scam watcher never turns ACTIVE",
    "non_typed_entry": "QR or contact only: no typed payee, no 'who are you paying?' question",
    "mule_cover": "many mule slots or merchant-disguised / rented mules, diluting the payee signals",
}


def _hi(spec) -> float | None:
    """Upper bound of a sim_v2 range spec (number, [lo, hi], {log|int: [lo, hi]}); None if relative."""
    if isinstance(spec, (int, float)):
        return float(spec)
    if isinstance(spec, list) and spec:
        return float(spec[-1])
    if isinstance(spec, dict):
        for k in ("log", "int"):
            if k in spec:
                return float(spec[k][-1])
    return None


def _lo(spec) -> float | None:
    if isinstance(spec, (int, float)):
        return float(spec)
    if isinstance(spec, list) and spec:
        return float(spec[0])
    if isinstance(spec, dict):
        for k in ("log", "int"):
            if k in spec:
                return float(spec[k][0])
    return None


def techniques(pb: dict) -> list[str]:
    steps = pb.get("steps", [])
    events = [e for s in steps for e in s.get("events", [])]
    asks = [s for s in steps if s.get("ask")]
    out = []
    called = False
    for s in steps:
        if any(e.get("type") == "call" for e in s.get("events", [])):
            called = True
        a = s.get("ask")
        if called and a and not a.get("during_call") and (_lo(s.get("gap_min", 0)) or 0) >= 30:
            out.append("cool_off")
            break
    lures = [e for e in events if e.get("type") in ("sms_lure", "notification_lure")]
    if lures and all(e["type"] == "notification_lure" for e in lures):
        out.append("notification_lure")
    if any(e.get("type") == "sms_lure" and (_hi(e.get("conf")) or 1) < 0.6 for e in lures):
        out.append("sub_threshold_sms")
    if len(asks) >= 2:
        first = _hi(asks[0]["ask"].get("amount"))
        later = [_hi(s["ask"].get("amount")) for s in asks[1:]]
        if first is not None and first <= 500 and any(x is None or x > first for x in later) and \
                all(s["ask"].get("mule", "same") == "same" for s in asks[1:]):
            out.append("anchor_then_drain")
    pays = [s["crew_pays"] for s in steps if s.get("crew_pays")]
    if pays and all(int(p.get("repeat", 1)) <= 1 for p in pays):
        out.append("single_bait")
    if asks and all(not (s["ask"].get("entry") or {}).get("typed") for s in asks):
        out.append("non_typed_entry")
    kinds = pb.get("mule_kinds") or {}
    if (pb.get("mules") or {}).get("slots", 0) >= 8 or kinds.get("merchant_disguised", 0) >= 0.5:
        out.append("mule_cover")
    return out


def claims() -> dict[str, dict]:
    if not CLAIMS.exists():
        return {}
    with open(CLAIMS, encoding="utf-8") as fh:
        return {r["playbook_name"]: r for r in csv.DictReader(fh)}


def load(red_dir: Path = RED_DIR) -> list[dict]:
    cl = claims()
    out = []
    for p in sorted(red_dir.glob("*.yaml")):
        pb = yaml.safe_load(p.read_text(encoding="utf-8"))
        c = cl.get(pb["name"], {})
        out.append({"name": pb["name"], "title": " ".join(str(pb.get("title", "")).split()), "weight": pb.get("weight"),
                     "steps": len(pb.get("steps", [])), "techniques": techniques(pb), "file": p.name,
                     "claimed_ml_missed": float(c["ml_missed_share"]) if c.get("ml_missed_share") else None,
                     "claimed_ml_threat": float(c["ml_mean_threat_score"]) if c.get("ml_mean_threat_score") else None,
                     "playbook": pb})
    return out


def build_world(out: Path, users: int, days: int, seed: int, victim_rate: float, red_boost: float,
                red_dir: Path = RED_DIR, keep_sim_emerging: bool = False, log=print,
                known: list[str] | None = None, known_boost: float = 1.0) -> dict:
    """A sim_v2 world where the red team's playbooks attack alongside RUKO's six known scams
    (or only the `known` ones, their weights x known_boost)."""
    from sim_v2.core.config import load as load_cfg
    from sim_v2.export import write
    from sim_v2.run import build as run_build

    cfg = load_cfg(users=users, days=days, seed=seed, world="train", victim_rate={"train": victim_rate, "eval": 0.01})
    if not keep_sim_emerging:   # keep only the scams RUKO already knows: the red team is the only unknown
        from blue_team import engine_file
        engine_known = {name for name, *_ in engine_file.known()}
        cfg.playbooks = {k: v for k, v in cfg.playbooks.items() if k in engine_known}
    if known is not None:
        missing = set(known) - set(cfg.playbooks)
        if missing:
            raise ValueError(f"not known sim_v2 playbooks: {sorted(missing)}")
        cfg.playbooks = {k: {**v, "weight": float(v.get("weight", 0.07)) * known_boost}
                         for k, v in cfg.playbooks.items() if k in known}
    red = {}
    for p in sorted(Path(red_dir).glob("*.yaml")):
        pb = yaml.safe_load(p.read_text(encoding="utf-8"))
        pb["weight"] = float(pb.get("weight", 0.07)) * red_boost
        pb["red_team"] = True
        red[pb["name"]] = pb
    clash = set(red) & set(cfg.playbooks)
    if clash:
        raise ValueError(f"red-team playbooks clash with sim_v2 names: {sorted(clash)}")
    cfg.playbooks.update(red)
    log(f"red-team world: {users:,} users x {days} days, victim rate {victim_rate}, {len(red)} red-team playbooks "
        f"(weight x{red_boost}) + {len(cfg.playbooks) - len(red)} sim_v2 playbooks -> {out}")
    write(run_build(cfg), cfg, out)
    meta = {"red_team": sorted(red), "users": users, "days": days, "seed": seed, "victim_rate": victim_rate,
            "red_boost": red_boost, "source": "all" if Path(red_dir).resolve() == RED_DIR.resolve() else str(red_dir)}
    (Path(out) / "red_team.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return meta


def scorecard(run_dir: Path, world: Path, table: Path) -> dict:
    """Per scam playbook: what RUKO did with its payments, where its complaints went, what the blue
    team drafted. Uses the simulator's answer key: evaluation only."""
    run_dir, world = Path(run_dir), Path(world)
    tiers_p = run_dir / "payment_tiers.parquet"
    if not tiers_p.exists():
        return {"error": "this run has no payment_tiers.parquet (runs before the red-team scorecard existed)"}
    red_meta = json.loads((world / "red_team.json").read_text(encoding="utf-8")) if (world / "red_team.json").exists() else {}
    red = set(red_meta.get("red_team", []))
    tiers = pd.read_parquet(tiers_p)
    tab = pd.read_parquet(table, columns=["tx_id", "label_is_scam", "playbook", "journey_id"])
    pay = tab[tab["label_is_scam"].astype(bool)].merge(tiers, on="tx_id", how="left")
    jr = pd.read_parquet(world / "journeys.parquet")
    rep = pd.read_parquet(world / "reports.parquet")[["report_id", "journey_id"]].dropna().drop_duplicates("report_id")
    case_pb = dict(zip(rep["report_id"], rep["journey_id"].map(dict(zip(jr["journey_id"], jr["playbook"])))))
    cases = {c["case_id"]: c for c in json.loads((run_dir / "cases.json").read_text(encoding="utf-8"))}
    clusters = {c["cluster_id"]: c for c in json.loads((run_dir / "clusters.json").read_text(encoding="utf-8"))}
    cands = {}
    for p in (run_dir / "candidates").glob("*.json"):
        c = json.loads(p.read_text(encoding="utf-8"))
        cands[c["cluster"]["cluster_id"]] = {"name": c["draft"]["card"]["name"], "verdict": c["analyst"].get("verdict")}
    # the true scam type that makes up most of each group
    main = {}
    for cid, c in clusters.items():
        cnt = Counter(case_pb.get(i, "?") for i in c["cases"])
        main[cid] = cnt.most_common(1)[0][0] if cnt else None
    from blue_team import inbox
    rows, cl, judged = [], claims(), inbox.verdicts()
    for pb in sorted(set(jr["playbook"])):
        j = jr[jr["playbook"] == pb]
        p = pay[pay["playbook"] == pb]
        my_cases = [cid for cid, t in case_pb.items() if t == pb and cid in cases]
        st = Counter(cases[c]["status"] for c in my_cases)
        groups = Counter(cases[c]["group"] for c in my_cases if cases[c].get("group"))
        found = [{"group": g, "kind": clusters[g]["kind"], "complaints": n, "majority": main.get(g) == pb,
                  "playbook": cands.get(g, {}).get("name"), "verdict": cands.get(g, {}).get("verdict")}
                 for g, n in groups.most_common()]
        drafted = [f for f in found if f["majority"] and f["playbook"]]
        named = Counter(x for x in p["named"].dropna())
        rows.append({
            "playbook": pb, "red_team": pb in red, "journeys": int(len(j)), "victims_paid": int((j["n_payments"] > 0).sum()),
            "claimed": float(cl[pb]["ml_missed_share"]) if cl.get(pb, {}).get("ml_missed_share") else None,
            "runner": ({k: judged[pb][k] for k in ("miss_rate", "breakthrough", "false_alarm_rate", "scam_payments_judged")}
                       if pb in judged else None),
            "scam_payments": int(len(p)),
            "ruko_interrupted": round(float(p["tier"].isin(INTERRUPT).mean()), 3) if len(p) else None,
            "ruko_named": dict(named.most_common(3)),
            "complaints": len(my_cases), "status": dict(st), "groups": found,
            "blue_team": ("drafted" if drafted else "grouped" if found else "complaints, no group" if my_cases
                          else "no complaint yet"),
            "drafted": [{"playbook": f["playbook"], "verdict": f["verdict"], "group": f["group"]} for f in drafted],
        })
    redrows = [r for r in rows if r["red_team"]]
    sp = sum(r["scam_payments"] for r in redrows)
    summary = {
        "red_playbooks": len(red), "red_with_journeys": sum(r["journeys"] > 0 for r in redrows),
        "red_scam_payments": sp,
        "red_ruko_interrupted": (round(sum((r["ruko_interrupted"] or 0) * r["scam_payments"] for r in redrows) / sp, 3) if sp else None),
        "red_with_complaints": sum(r["complaints"] > 0 for r in redrows),
        "red_grouped": sum(bool(r["groups"]) for r in redrows),
        "red_drafted": sum(bool(r["drafted"]) for r in redrows),
        "red_drafted_new_scam": sum(any(d["verdict"] == "new_scam" for d in r["drafted"]) for r in redrows),
    }
    return {"summary": summary, "rows": rows, "is_red_world": bool(red)}
