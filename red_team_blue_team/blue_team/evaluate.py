"""Score a blue-team run against the simulator's ground truth. Evaluation only: nothing in the
pipeline reads what this file reads (CLAUDE.md rule 9).

    python -m blue_team evaluate --run red_team_blue_team/blue_team/runs/<run_id> --data data/sim_v2_out/breach

For every cluster: the true scam types of its cases and its purity. For every scam type: how many of
its breaches were clustered, whether a *new* candidate was drafted for it, and the analyst agent's
verdict. A verdict is right when it says new_scam for a type RUKO has no playbook for, or
variant_of_known for one it has.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd

KNOWN_TYPES = {"digital_arrest", "fake_customer_care", "fake_kyc_apk", "refund_qr", "task_job", "trading_group"}


def truth(world: Path) -> dict[str, str]:
    rep = pd.read_parquet(world / "reports.parquet")[["report_id", "journey_id"]].dropna().drop_duplicates("report_id")
    jr = pd.read_parquet(world / "journeys.parquet")[["journey_id", "playbook"]]
    m = rep.merge(jr, on="journey_id")
    return dict(zip(m["report_id"], m["playbook"]))


def evaluate(run_dir: Path, world: Path) -> dict:
    t = truth(world)
    clusters = {}
    for p in sorted((run_dir / "candidates").glob("*.json")):
        cand = json.loads(p.read_text(encoding="utf-8"))
        cid = cand["cluster"]["cluster_id"]
        types = Counter(t.get(c, "?") for c in cand["cluster"]["case_ids"])
        main, n = types.most_common(1)[0]
        kind, ruko = cand["cluster"]["kind"], cand["cluster"]["nearest_playbook"]
        verdict, said = cand["analyst"]["verdict"], cand["analyst"].get("nearest_playbook")
        if kind == "misnamed" and main == ruko:        # RUKO's name was right
            right = verdict == "variant_of_known" and said == ruko
        elif kind == "misnamed" and main in KNOWN_TYPES:   # really another known scam
            right = verdict == "variant_of_known" and said != ruko
        else:
            right = (verdict == "new_scam") == (main not in KNOWN_TYPES)
        clusters[cid] = {"kind": kind, "ruko_named": ruko if kind == "misnamed" else None,
                         "name": cand["draft"]["card"]["name"], "cases": sum(types.values()), "true_types": dict(types),
                         "main_type": main, "purity": round(n / sum(types.values()), 2),
                         "analyst_verdict": cand["analyst"]["verdict"], "verdict_right": right,
                         "gates_pass": not cand["draft"]["gate_failures"]}
    by_type: dict[str, dict] = {}
    new_types = {v["main_type"] for v in clusters.values() if v["analyst_verdict"] == "new_scam"}
    for typ in sorted(set(t.values())):
        by_type[typ] = {"known_to_ruko": typ in KNOWN_TYPES,
                        "drafted_as_new": any(v["main_type"] == typ for v in clusters.values()),
                        "analyst_said_new": typ in new_types}
    verdicts = [v["verdict_right"] for v in clusters.values()]
    return {"run": str(run_dir), "clusters_drafted": clusters, "by_type": by_type,
            "analyst_verdict_accuracy": round(sum(verdicts) / len(verdicts), 2) if verdicts else None,
            "mean_purity": round(sum(v["purity"] for v in clusters.values()) / len(clusters), 2) if clusters else None,
            "emerging_types_found_new": sorted(t_ for t_, v in by_type.items() if not v["known_to_ruko"] and v["analyst_said_new"]),
            "emerging_types_missed": sorted(t_ for t_, v in by_type.items() if not v["known_to_ruko"] and not v["analyst_said_new"])}
