"""The whole blue-team run: complaints -> breaches -> HDBSCAN -> generator agent -> analyst agent -> review queue.

    PYTHONPATH=backend;ml;data;red_team_blue_team python -m blue_team run \
        --table ml/data/tables/breach.parquet --data data/sim_v2_out/breach

Writes runs/<run_id>/:
- events.jsonl  every step in order, each with a short why and its references (the console's timeline)
- cases.json    every complaint case: status, why, and each payment with RUKO's tier and the signals
- clusters.json every HDBSCAN group and misnamed? group, with the reason for its kind
- candidates/   one JSON per candidate: both agents' full transcripts, the card, the backtest, the verdict
- summary.json, report.md, status.json
and one YAML per candidate into playbooks/review/, where two human analysts approve or reject it.
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from blue_team import analyst, breach, cluster, config, investigator, llm, playbook_db, report, tokens
from blue_team.evidence import Workspace


class EventLog:
    """Append-only run log: one JSON line per step. `echo` prints the decisions to the terminal."""

    def __init__(self, path: Path, echo=print):
        self.path, self.echo, self.seq, self.lock = path, echo, 0, threading.Lock()

    def __call__(self, stage: str, text: str, kind: str = "info", refs: dict | None = None, data: dict | None = None):
        with self.lock:
            self.seq += 1
            rec = {"seq": self.seq, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "stage": stage,
                   "kind": kind, "text": text, "refs": refs or {}, "data": data or {}}
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
        if kind not in ("tool", "thought", "filtered") and self.echo:
            self.echo(("    " if stage in ("generator", "analyst", "database") else "") + text)


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
        return rt, model
    except llm.LLMUnavailable as e:
        if provider == "bedrock":
            raise
        log(f"Bedrock unavailable ({str(e).splitlines()[0]})")
        return None, None


def case_why(c) -> str:
    if c.status == "missed":
        return f"no payment was interrupted: the highest tier was {c.max_tier} (interrupting needs T2 or more)"
    if c.status == "unnamed":
        return f"interrupted ({c.max_tier}) but no playbook named the scam, so the user got a generic warning"
    return f"interrupted ({c.max_tier}) and named {', '.join(c.named)}, yet the victim still paid and complained"


def cases_json(ws: Workspace) -> list[dict]:
    member = {i: c.cluster_id for c in ws.clusters.clusters for i in c.case_ids}
    rows, feats = ws.scored.rows, ws.scored.feats
    out = []
    for c in ws.cases.itertuples(index=False):
        pays = []
        for i in c.rows:
            r, f = rows.loc[i], feats[i]
            pays.append({"tx_id": str(r["tx_id"]), "ts": str(r["ts"]), "amount_inr": float(r["amount"]),
                         "payee_upi_id": r["payee_upi"], "entry_method": f.get("entry_method"),
                         "payer_says": f.get("payer_says"), "ruko_tier": r["tier"],
                         "ruko_named": r["named"] if isinstance(r["named"], str) else None,
                         "p_scam": round(float(r["p_scam"]), 3), "signals": tokens.payment_tokens(f)})
        out.append({"case_id": c.case_id, "user": c.user_id, "filed_at": str(c.filed_at), "source": c.source,
                    "status": c.status, "why": case_why(c), "max_tier": c.max_tier, "named": list(c.named),
                    "payments": pays, "total_inr": float(c.total_inr), "group": member.get(c.case_id),
                    "document": c.document})
    return out


def clusters_json(ws: Workspace) -> list[dict]:
    return [{"cluster_id": c.cluster_id, "kind": c.kind, "cases": c.case_ids, "nearest_playbook": c.nearest_playbook,
             "similarity": c.similarity, "named_share": c.named_share, "top_tokens": c.top_tokens,
             "baseline_cases": len(c.baseline_ids or []), "reason": c.reason} for c in ws.clusters.clusters]


def run(table: Path, world: Path, scorer: str = "ml", provider: str | None = None, as_of: pd.Timestamp | None = None,
        out_root: Path | None = None, playbook_root: Path | None = None, log=print, model: str | None = None,
        region: str | None = None, run_id: str | None = None) -> dict:
    provider = provider or config.load()["agents"]["provider"]
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = (out_root or config.RUNS) / run_id
    (out / "candidates").mkdir(parents=True, exist_ok=True)
    status_file = out / "status.json"
    status_file.write_text(json.dumps({"run_id": run_id, "state": "running", "world": str(world), "table": str(table),
                                       "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}), encoding="utf-8")
    ev = EventLog(out / "events.jsonl", echo=log)
    try:
        summary = _run(ev, out, run_id, table, world, scorer, provider, as_of, playbook_root, model, region)
        state = {"state": "done"}
        return summary
    except Exception as e:
        ev("done", f"Run failed: {type(e).__name__}: {e}", kind="error")
        state = {"state": "failed", "error": f"{type(e).__name__}: {e}"}
        raise
    finally:
        st = json.loads(status_file.read_text(encoding="utf-8"))
        st.update(state, finished=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        status_file.write_text(json.dumps(st), encoding="utf-8")


def _run(ev: EventLog, out: Path, run_id: str, table: Path, world: Path, scorer: str, provider: str,
         as_of, playbook_root, model, region) -> dict:
    cfg = config.load()
    ev("setup", f"Run {run_id}: world {world}, replayed payments {table}, scorer '{scorer}'",
       refs={"config": "red_team_blue_team/blue_team/config.yaml", "world": str(world), "table": str(table)})

    ws = workspace(table, world, scorer, as_of)
    if ws.scored.missing_features:
        ev("setup", f"The replayed table predates {', '.join(ws.scored.missing_features)}: treated as unknown for every "
           "payment (re-run the replay to measure them)", kind="warning", refs={"rule": "CLAUDE.md rule 1"})
    st = ws.cases["status"].value_counts().to_dict() if len(ws.cases) else {}
    ev("complaints", f"{len(ws.cases)} complaints (1930 / NCRP) matched to the complainant's own payments to the "
       f"accounts they name; every payment re-scored as RUKO saw it at the time ({ws.scored.scorer} + the real policy)",
       refs={"source": f"{world}/reports.parquet", "code": "breach.py"}, data={"cases": len(ws.cases)})
    for s, meaning in (("missed", "no payment interrupted (highest tier below T2): the shield broke"),
                       ("unnamed", "interrupted, but no playbook named the scam: a generic warning"),
                       ("held", "interrupted and named, yet the victim still paid: checked for a wrong name")):
        ids = ws.cases.loc[ws.cases["status"] == s, "case_id"].tolist()
        ev("breaches", f"{len(ids)} {s}: {meaning}", kind="decision",
           refs={"rule": f"breach.interrupt_tiers {cfg['breach']['interrupt_tiers']}", "cases": ids})
    (out / "cases.json").write_text(json.dumps(cases_json(ws), default=str, ensure_ascii=False), encoding="utf-8")

    cc = cfg["cluster"]
    br = [c for c in ws.clusters.clusters if c.kind != "misnamed"]
    ev("hdbscan", f"HDBSCAN over {len(ws.clusters.breaches)} missed + unnamed cases (token n-grams {cc['ngram_range']}, "
       f"TF-IDF, SVD {cc['svd_components']}, min_cluster_size {cc['min_cluster_size']}, min_samples {cc['min_samples']}, "
       f"{cc['selection']}): {len(br)} groups, {len(ws.clusters.noise)} one-off cases left as noise",
       refs={"config": "cluster.*", "code": "cluster.py run()", "noise": ws.clusters.noise})
    for c in br:
        ev("hdbscan", f"{c.cluster_id} ({len(c.case_ids)} cases): {c.reason}", kind="decision",
           refs={"cluster": c.cluster_id, "cases": c.case_ids, "top_tokens": [t for t, _ in c.top_tokens[:6]]})
    mis = [c for c in ws.clusters.clusters if c.kind == "misnamed"]
    ev("misnamed", f"Held complaints clustered per playbook (at least {cfg['misnamed']['min_cases']} each): "
       f"{len(mis)} subgroups do not fit the playbook RUKO named them with", refs={"code": "cluster.py misnamed()"})
    for c in mis:
        ev("misnamed", f"{c.cluster_id} ({len(c.case_ids)} cases): {c.reason}", kind="decision",
           refs={"cluster": c.cluster_id, "cases": c.case_ids, "top_tokens": [t for t, _ in c.top_tokens[:6]]})
    (out / "clusters.json").write_text(json.dumps(clusters_json(ws), default=str), encoding="utf-8")
    (out / "cluster_map.json").write_text(json.dumps(ws.clusters.maps, default=str), encoding="utf-8")

    todo = [c for c in ws.clusters.clusters if c.kind in ("new", "misnamed")]
    rt, model = connect(provider, lambda m: ev("agents", m), model, region)
    ev("agents", f"Agents: {'Amazon Bedrock ' + model if rt else 'offline (deterministic drafts, no LLM)'}; "
       f"{len(todo)} groups to investigate", kind="decision",
       refs={"config": "agents.models", "groups": [c.cluster_id for c in todo]})

    taken = {pb.name for pb in playbook_db.load(("known", "review", "approved"), playbook_root)}
    candidates = []
    for c in todo:
        cid = c.cluster_id
        stream = (lambda stage: (lambda kind, text, data: ev(stage, text, kind=kind, refs={"cluster": cid}, data=data)))
        ev("generator", f"Generator agent investigates {cid} ({len(c.case_ids)} complaints, {c.kind})",
           refs={"cluster": cid, "task": investigator.task_for(ws, cid)})
        draft = (investigator.investigate(ws, cid, rt, model, taken, on_event=stream("generator")) if rt
                 else investigator.investigate_offline(ws, cid, taken))
        card, bt = draft["card"], draft["backtest"] or {}
        taken.add(card["name"])
        ev("generator", f"Drafted '{card['name']}' ({draft['drafted_by']}): rule names {bt.get('cluster_case_recall', 0):.0%} "
           f"of the complaints and {bt.get('legit_payments_named_per_1000')} legit payments per 1,000; gates "
           + ("pass" if not draft["gate_failures"] else "FAIL: " + "; ".join(draft["gate_failures"])), kind="decision",
           refs={"cluster": cid, "card": card["name"], "rule": bt.get("rule_in_words"),
                 "evidence": card.get("evidence", []), "gates": "config gates.*"})

        ev("analyst", f"Analyst agent reviews '{card['name']}' independently", refs={"cluster": cid})
        rev = (analyst.review(ws, cid, draft, rt, model, on_event=stream("analyst")) if rt
               else analyst.review_offline(ws, cid, draft))
        ev("analyst", f"Verdict on '{card['name']}': {rev['verdict']}"
           + (f" (nearest {rev['nearest_playbook']})" if rev.get("nearest_playbook") else "")
           + f" by {rev.get('reviewed_by')}: {rev.get('rationale', '')[:300]}", kind="decision",
           refs={"cluster": cid, "card": card["name"], "evidence": rev.get("evidence", [])})

        cand = {"run_id": run_id, "cluster": c.__dict__, "overview": ws.overview(cid), "draft": draft, "analyst": rev,
                "examples": [ws.case(i) for i in c.case_ids[:3]], "mules": ws.mules(cid), "labels": ws.labels(cid)}
        (out / "candidates" / f"{cid}_{card['name']}.json").write_text(
            json.dumps(cand, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
        path = playbook_db.write(queue_card(cand, scorer=ws.scored.scorer), "review", playbook_root)
        ev("database", f"Queued '{card['name']}' for two human analysts", kind="decision",
           refs={"cluster": cid, "card": card["name"], "file": str(path)})
        candidates.append({"cluster_id": cid, "kind": c.kind, "name": card["name"], "cases": len(c.case_ids),
                           "drafted_by": draft["drafted_by"], "gate_failures": draft["gate_failures"],
                           "verdict": rev["verdict"], "nearest_playbook": rev.get("nearest_playbook"), "queued": str(path)})

    summary = {
        "run_id": run_id, "table": str(table), "world": str(world), "scorer": ws.scored.scorer,
        "agents": model or "offline", "as_of": None if as_of is None else str(as_of),
        "cases": int(len(ws.cases)), "status": st,
        "clusters": [{"cluster_id": c.cluster_id, "kind": c.kind, "cases": len(c.case_ids), "nearest": c.nearest_playbook,
                      "similarity": c.similarity, "named_share": c.named_share, "top_tokens": c.top_tokens[:6]}
                     for c in ws.clusters.clusters],
        "noise": len(ws.clusters.noise), "candidates": candidates,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    (out / "report.md").write_text(report.markdown(summary, ws, out), encoding="utf-8")
    ev("done", f"Run finished: {len(candidates)} playbooks waiting for two human analysts", kind="decision",
       refs={"dir": str(out)})
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
                     "nearest_known": cand["cluster"]["nearest_playbook"], "similarity": cand["cluster"]["similarity"],
                     "cited": card.get("evidence", [])},
        "backtest": {k: v for k, v in (d["backtest"] or {}).items() if k != "rule_in_words"},
        "rule_in_words": (d["backtest"] or {}).get("rule_in_words"),
        "gate_failures": d["gate_failures"],
        "drafted_by": d["drafted_by"],
        "analyst": {k: cand["analyst"].get(k) for k in ("verdict", "nearest_playbook", "rationale", "required_changes",
                                                       "confidence", "reviewed_by", "evidence")},
        "mule_accounts": cand["mules"],
        "label_tx_ids": cand["labels"],
        "reviews": [],
    }


if __name__ == "__main__":
    sys.exit("use: python -m blue_team run ...")
