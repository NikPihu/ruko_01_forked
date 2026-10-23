"""The whole blue-team run: breaches -> clusters -> investigator -> analyst -> review queue.

    PYTHONPATH=backend;ml;data;red_team_blue_team python -m blue_team run \
        --table ml/data/tables/breach.parquet --data data/sim_v2_out/breach

Writes runs/<run_id>/ (summary.json, report.md, one JSON per candidate with both agents' transcripts)
and one YAML per new-scam candidate into playbooks/review/, where two human analysts approve or
reject it (blue_team/review.py).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from blue_team import analyst, breach, cluster, config, investigator, llm, playbook_db, report
from blue_team.evidence import Workspace


def workspace(table: Path, world: Path, scorer: str = "ml", as_of: pd.Timestamp | None = None) -> Workspace:
    pbs = playbook_db.load(("known", "approved"))
    scored = breach.score(breach.load_table(table), scorer, pbs)
    comp = breach.complaints(world, as_of)
    cases = breach.cases(scored, comp)
    res = cluster.run(cases)
    return Workspace(scored, cases, res, breach.presumed_legit(scored, comp), pbs)


def connect(provider: str, log=print, model: str | None = None, region: str | None = None):
    """(client, model id) for Bedrock, or (None, None) for offline. `auto` falls back to offline."""
    if provider == "offline":
        return None, None
    try:
        rt, model = llm.connect([model] if model else None, log=log, region=region)
        log(f"agents: Bedrock {model}")
        return rt, model
    except llm.LLMUnavailable as e:
        if provider == "bedrock":
            raise
        log(f"agents: offline (Bedrock unavailable: {str(e).splitlines()[0]})")
        return None, None


def run(table: Path, world: Path, scorer: str = "ml", provider: str | None = None, as_of: pd.Timestamp | None = None,
        out_root: Path | None = None, playbook_root: Path | None = None, log=print, model: str | None = None,
        region: str | None = None) -> dict:
    provider = provider or config.load()["agents"]["provider"]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = (out_root or config.RUNS) / run_id
    (out / "candidates").mkdir(parents=True, exist_ok=True)

    ws = workspace(table, world, scorer, as_of)
    status = ws.cases["status"].value_counts().to_dict() if len(ws.cases) else {}
    log(f"{len(ws.cases)} complaint cases ({status}); scorer {ws.scored.scorer}")
    new = [c for c in ws.clusters.clusters if c.kind in ("new", "misnamed")]
    n_mis = sum(c.kind == "misnamed" for c in new)
    log(f"{len(ws.clusters.clusters) - n_mis} breach clusters ({len(new) - n_mis} new), "
        f"{len(ws.clusters.noise)} breaches in no cluster; {n_mis} misnamed? groups among held complaints")

    rt, model = connect(provider, log, model, region)
    taken = {pb.name for pb in playbook_db.load(("known", "review", "approved"), playbook_root)}
    candidates = []
    for c in new:
        log(f"  {c.cluster_id}: {len(c.case_ids)} cases, " + (
            f"misnamed? RUKO said {c.nearest_playbook} (fit {c.similarity})" if c.kind == "misnamed"
            else f"nearest {c.nearest_playbook} ({c.similarity})"))
        draft = (investigator.investigate(ws, c.cluster_id, rt, model, taken) if rt
                 else investigator.investigate_offline(ws, c.cluster_id, taken))
        rev = analyst.review(ws, c.cluster_id, draft, rt, model) if rt else analyst.review_offline(ws, c.cluster_id, draft)
        card = draft["card"]
        taken.add(card["name"])
        log(f"    drafted '{card['name']}' ({draft['drafted_by']}), gates "
            f"{'pass' if not draft['gate_failures'] else 'FAIL'}; analyst: {rev['verdict']} ({rev.get('reviewed_by')})")
        cand = {"run_id": run_id, "cluster": c.__dict__, "overview": ws.overview(c.cluster_id), "draft": draft, "analyst": rev,
                "examples": [ws.case(i) for i in c.case_ids[:3]],   # shown to the human reviewers
                "mules": ws.mules(c.cluster_id), "labels": ws.labels(c.cluster_id)}
        (out / "candidates" / f"{c.cluster_id}_{card['name']}.json").write_text(
            json.dumps(cand, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
        path = playbook_db.write(queue_card(cand, scorer=ws.scored.scorer), "review", playbook_root)
        candidates.append({"cluster_id": c.cluster_id, "kind": c.kind, "name": card["name"], "cases": len(c.case_ids),
                           "drafted_by": draft["drafted_by"], "gate_failures": draft["gate_failures"],
                           "verdict": rev["verdict"], "nearest_playbook": rev.get("nearest_playbook"),
                           "queued": str(path)})

    summary = {
        "run_id": run_id, "table": str(table), "world": str(world), "scorer": ws.scored.scorer,
        "agents": model or "offline", "as_of": None if as_of is None else str(as_of),
        "cases": int(len(ws.cases)), "status": status,
        "clusters": [{"cluster_id": c.cluster_id, "kind": c.kind, "cases": len(c.case_ids), "nearest": c.nearest_playbook,
                      "similarity": c.similarity, "named_share": c.named_share, "top_tokens": c.top_tokens[:6]}
                     for c in ws.clusters.clusters],
        "noise": len(ws.clusters.noise), "candidates": candidates,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    (out / "report.md").write_text(report.markdown(summary, ws, out), encoding="utf-8")
    log(f"-> {out}")
    return summary


def queue_card(cand: dict, scorer: str) -> dict:
    """The review-queue YAML: the card, its matcher at approved priority, the evidence humans need."""
    d, card = cand["draft"], cand["draft"]["card"]
    mis = cand["cluster"]["nearest_playbook"] if cand["cluster"]["kind"] == "misnamed" else None
    return {
        "name": card["name"], "title": card["title"], "status": "review",
        "summary": card["summary"], "steps": card["steps"], "signals": card.get("signals", []),
        "reason_codes": card["reason_codes"], "advice_en": card["advice_en"], "advice_hi": card["advice_hi"],
        "ai_powered": card.get("ai_powered"), "confidence": card.get("confidence"),
        "open_questions": card.get("open_questions", []),
        "misnamed_as": mis,
        "match": [{"priority": playbook_db.priority_before(mis) if mis else playbook_db.APPROVED_MIN_PRIORITY,
                   "rule": card["matcher"]}],
        "evidence": {"run_id": cand["run_id"], "cluster_id": cand["cluster"]["cluster_id"],
                     "cases": len(cand["cluster"]["case_ids"]), "scorer": scorer,
                     "nearest_known": cand["cluster"]["nearest_playbook"], "similarity": cand["cluster"]["similarity"]},
        "backtest": {k: v for k, v in (d["backtest"] or {}).items() if k != "rule_in_words"},
        "rule_in_words": (d["backtest"] or {}).get("rule_in_words"),
        "gate_failures": d["gate_failures"],
        "drafted_by": d["drafted_by"],
        "analyst": {k: cand["analyst"].get(k) for k in ("verdict", "nearest_playbook", "rationale", "required_changes",
                                                       "confidence", "reviewed_by")},
        "mule_accounts": cand["mules"],
        "label_tx_ids": cand["labels"],
        "reviews": [],
    }


if __name__ == "__main__":
    sys.exit("use: python -m blue_team run ...")
