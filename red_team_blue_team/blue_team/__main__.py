"""Blue team commands. From the repo root, with PYTHONPATH=backend;ml;data;red_team_blue_team:

    python -m blue_team probe                                   # which Bedrock models answer
    python -m blue_team run --table ml/data/tables/breach.parquet --data data/sim_v2_out/breach [--llm offline]
    python -m blue_team queue                                   # candidates waiting for analysts
    python -m blue_team show <name>
    python -m blue_team approve <name> --analyst <you> [--note ...]
    python -m blue_team reject  <name> --analyst <you> --note "why"
    python -m blue_team retest  <name> --table ... --data ...   # after editing a queued matcher
    python -m blue_team evaluate --run <runs/run_id> --data <world>   # ground truth, scoring only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m blue_team", description="RUKO blue team: find and name the scams the shield missed")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="which Bedrock models this key can call")
    r = sub.add_parser("run", help="breaches -> clusters -> agents -> review queue")
    r.add_argument("--table", type=Path, required=True, help="a replayed table (ml/dataset/replay.py)")
    r.add_argument("--data", type=Path, required=True, help="the world folder with reports.parquet")
    r.add_argument("--scorer", choices=["ml", "rules"], default="ml")
    r.add_argument("--llm", choices=["bedrock", "offline", "auto"], default=None, help="default: config.yaml agents.provider")
    r.add_argument("--as-of", default=None, help="only complaints filed by this time (ISO), to replay discovery over time")
    sub.add_parser("queue", help="candidates waiting for analysts")
    s = sub.add_parser("show")
    s.add_argument("name")
    for cmd in ("approve", "reject"):
        d = sub.add_parser(cmd)
        d.add_argument("name")
        d.add_argument("--analyst", required=True)
        d.add_argument("--note", default="")
    t = sub.add_parser("retest", help="backtest a queued card again after editing its matcher")
    t.add_argument("name")
    t.add_argument("--table", type=Path, required=True)
    t.add_argument("--data", type=Path, required=True)
    t.add_argument("--scorer", choices=["ml", "rules"], default="ml")
    e = sub.add_parser("evaluate")
    e.add_argument("--run", type=Path, required=True)
    e.add_argument("--data", type=Path, required=True)
    a = p.parse_args()

    if a.cmd == "probe":
        from blue_team import config, llm
        for model, status in llm.probe(config.load()["agents"]["models"]):
            print(f"{model:50s} {status}")
    elif a.cmd == "run":
        from blue_team import pipeline
        as_of = pd.Timestamp(a.as_of, tz="UTC") if a.as_of and pd.Timestamp(a.as_of).tzinfo is None else (
            pd.Timestamp(a.as_of) if a.as_of else None)
        pipeline.run(a.table, a.data, a.scorer, a.llm, as_of)
    elif a.cmd == "queue":
        from blue_team import review
        q = review.queue()
        if not q:
            print("nothing waiting")
        for c in q:
            print(f"{c['name']:40s} {c['cases']:3d} cases  analyst agent: {c['analyst_agent']:22s} gates {c['gates']:4s} "
                  f"approvals {c['approvals']}  {c['title'][:60]}")
    elif a.cmd == "show":
        from blue_team import review
        card, state = review.load_card(a.name)
        print(f"# {state}")
        print(yaml.safe_dump({k: v for k, v in card.items() if k not in ("label_tx_ids",)}, sort_keys=False,
                             allow_unicode=True, width=110))
    elif a.cmd in ("approve", "reject"):
        from blue_team import review
        try:
            print(json.dumps(review.decide(a.name, a.analyst, a.cmd, a.note), indent=1))
        except review.ReviewError as err:
            sys.exit(f"error: {err}")
    elif a.cmd == "retest":
        from blue_team import pipeline, playbook_db, review
        card, state = review.load_card(a.name)
        if state != "review":
            sys.exit(f"error: {a.name} is {state}")
        ws = pipeline.workspace(a.table, a.data, a.scorer)
        cid = card["evidence"]["cluster_id"]
        if cid not in ws.cluster_by_id:
            sys.exit(f"error: cluster {cid} is not in this table/world; retest on the run's own data")
        bt = ws.test_matcher(card["match"][0]["rule"], cid)
        card["backtest"] = {k: v for k, v in bt.items() if k != "rule_in_words"}
        card["rule_in_words"] = bt.get("rule_in_words")
        card["gate_failures"] = bt.get("gate_failures", bt.get("errors", []))
        playbook_db.write(card, "review")
        print(json.dumps(bt, indent=1))
    elif a.cmd == "evaluate":
        from blue_team import evaluate
        print(json.dumps(evaluate.evaluate(a.run, a.data), indent=1))


if __name__ == "__main__":
    main()
