"""Which Bedrock model makes the better blue-team agents: the same complaint groups, both agents (generator
and analyst), one model at a time.

    python -m blue_team.compare_models --table ml/data/tables/redteam.parquet --data data/sim_v2_out/redteam \
        --models openai.gpt-oss-120b-1:0 qwen.qwen3-235b-a22b-2507-v1:0 --groups 6

Per model and group: does the draft pass the gates, how much of its group the rule names, honest payments it
would name per 1,000, whether the agent's own rule had to be replaced by the code search, whether the
analyst's verdict matches the answer key (a group dominated by an attack playbook is a new scam, one by a
known scam a variant), turns, seconds and tokens. The answer key grades only (CLAUDE.md rule 9); the
agents never see it. Nothing is queued for review: drafts go to a scratch playbook folder.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from collections import Counter
from pathlib import Path

import pandas as pd

from blue_team import analyst, investigator, llm, pipeline

KNOWN = {"digital_arrest", "fake_customer_care", "fake_kyc_apk", "refund_qr", "task_job", "trading_group"}


def expected_verdicts(ws, world: Path) -> dict[str, str]:
    """Answer key, for grading: the playbook most of a group's complaints came from."""
    rep = pd.read_parquet(world / "reports.parquet", columns=["report_id", "journey_id"]).dropna().drop_duplicates("report_id")
    jr = pd.read_parquet(world / "journeys.parquet", columns=["journey_id", "playbook"])
    pb_of = dict(zip(rep.merge(jr, on="journey_id")["report_id"], rep.merge(jr, on="journey_id")["playbook"]))
    out = {}
    for c in ws.clusters.clusters:
        top = Counter(pb_of.get(i) for i in c.case_ids if pb_of.get(i)).most_common(1)
        if top:
            out[c.cluster_id] = "variant_of_known" if top[0][0] in KNOWN else "new_scam"
    return out


def one(ws, cid: str, rt, model: str, expect: str | None) -> dict:
    t0 = time.perf_counter()
    taken: set[str] = set()
    try:
        draft = investigator.investigate(ws, cid, rt, model, taken)
    except Exception as e:  # noqa: BLE001 (a model failing is a result)
        return {"group": cid, "error": f"generator: {type(e).__name__}: {e}"[:300]}
    t1 = time.perf_counter()
    try:
        rev = analyst.review(ws, cid, draft, rt, model)
    except Exception as e:  # noqa: BLE001
        rev = {"verdict": None, "error": f"analyst: {type(e).__name__}: {e}"[:300]}
    t2 = time.perf_counter()
    bt, card = draft.get("backtest") or {}, draft.get("card") or {}
    u_g, u_a = draft.get("usage") or {}, rev.get("usage") or {}
    return {"group": cid, "cases": len(ws._cluster(cid).case_ids), "drafted_by": draft.get("drafted_by"),
            "fell_back_offline": str(draft.get("drafted_by", "")).startswith("offline"),
            "gates_pass": not draft.get("gate_failures"), "rule_replaced": bool(card.get("drafted_matcher")),
            "recall": bt.get("cluster_case_recall"), "legit_per_1000": bt.get("legit_payments_named_per_1000"),
            "warns": bt.get("warns"), "verdict": rev.get("verdict"), "expected": expect,
            "verdict_right": (rev.get("verdict") == expect) if expect and rev.get("verdict") else None,
            "turns": (u_g.get("turns") or 0) + (u_a.get("turns") or 0),
            "tokens": sum((u.get("tokens_in") or 0) + (u.get("tokens_out") or 0) for u in (u_g, u_a)),
            "seconds": {"generator": round(t1 - t0, 1), "analyst": round(t2 - t1, 1)}, "error": rev.get("error")}


def summary(rows: list[dict]) -> dict:
    ok = [r for r in rows if not r.get("error", "").startswith("generator")] if rows else []
    n = len(rows) or 1
    graded = [r for r in ok if r.get("verdict_right") is not None]
    return {"groups": len(rows), "errors": sum(1 for r in rows if r.get("error")),
            "fell_back_offline": sum(1 for r in ok if r["fell_back_offline"]),
            "gates_pass": sum(1 for r in ok if r["gates_pass"]), "own_rule_kept": sum(1 for r in ok if not r["rule_replaced"]),
            "verdicts_right": f"{sum(r['verdict_right'] for r in graded)}/{len(graded)}",
            "mean_recall": round(sum(r["recall"] or 0 for r in ok) / max(1, len(ok)), 3),
            "mean_legit_per_1000": round(sum(r["legit_per_1000"] or 0 for r in ok) / max(1, len(ok)), 3),
            "seconds_per_group": round(sum(sum(r["seconds"].values()) for r in ok) / max(1, len(ok)), 1),
            "tokens_per_group": round(sum(r["tokens"] for r in ok) / max(1, len(ok))), "share": round(len(ok) / n, 2)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--table", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--models", nargs="+", required=True)
    p.add_argument("--groups", type=int, default=6, help="the largest new groups to compare on")
    p.add_argument("--out", type=Path, default=Path("ml/runs/compare_models.json"))
    a = p.parse_args()
    if not llm.has_credentials():
        raise SystemExit(llm.NO_KEY)
    root = Path(tempfile.mkdtemp(prefix="cmp_playbooks_"))
    import shutil

    from blue_team import config
    shutil.copytree(config.PLAYBOOKS / "known", root / "known")
    ws = pipeline.workspace(a.table, a.data, "ml", None, root)
    new = sorted((c for c in ws.clusters.clusters if c.kind in ("new", "misnamed")), key=lambda c: -len(c.case_ids))[: a.groups]
    expect = expected_verdicts(ws, a.data)
    print(f"{len(ws.cases)} complaints, {len(ws.clusters.clusters)} groups; comparing on {len(new)}: "
          + ", ".join(f"{c.cluster_id} ({len(c.case_ids)})" for c in new), flush=True)
    res = {}
    for m in a.models:
        rt, model = pipeline.connect("bedrock", print, m)
        rows = []
        for c in new:
            r = one(ws, c.cluster_id, rt, model, expect.get(c.cluster_id))
            rows.append(r)
            print(f"  {m:34s} {c.cluster_id}: gates {'pass' if r.get('gates_pass') else 'FAIL'} · recall {r.get('recall')} · "
                  f"honest/1k {r.get('legit_per_1000')} · verdict {r.get('verdict')} (expected {r.get('expected')}) · "
                  f"{r.get('seconds')} · {r.get('error') or ''}", flush=True)
        res[m] = {"summary": summary(rows), "groups": rows}
        print(f"== {m}: {json.dumps(res[m]['summary'])}", flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
