"""The console's Accuracy page: what RUKO gets right and wrong, measured on data it never trained on.

    PYTHONPATH=backend;ml;data python -m evalsuite.accuracy --table ml/data/tables/dev_test.parquet

Three parts, each from its own held-out source:
1. Payments: the held-out simulated world `dev_test` (seed 12, never used in training), replayed as
   the phone and engine would have seen it (ml/dataset/replay.py) and decided through the real
   policy (ml/model/evaluate.py), for the live scorer and the rules. A confusion table (scam or not
   against interrupted or not), false alarms, results per scam type, and the scams it missed, grouped.
2. Scam messages: the on-phone lure model's held-out templates (ml/model/artifacts/lure_metrics.json).
3. New scams: the red team's 50 invented playbooks, run against the engine
   (red_team_blue_team/red_team/attack_manifest.csv).

Ground truth is read here only to score (rule 9). Output: backend/evalsuite/accuracy_results.json,
served by GET /v1/accuracy. Numbers are what they are; the failure cases are written from them.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("accuracy_results.json")
LURE_METRICS = ROOT / "ml" / "model" / "artifacts" / "lure_metrics.json"
RED_TEAM = ROOT / "red_team_blue_team" / "red_team" / "attack_manifest.csv"
INTERRUPT = ("T2", "T3", "T4")


def _r(x, n=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), n)


def payments(table: Path) -> dict:
    from api import rule_scorer
    from model import predict
    from model.evaluate import raw_features, score_both, tiers

    df = pd.read_parquet(table).reset_index(drop=True)
    feats = raw_features(df)
    both = score_both(df, feats)
    y = df["label_is_scam"].to_numpy(bool)
    w = df["weight"].to_numpy(float)          # normal payments were subsampled; weights restore them
    out = {"world": "dev_test (seed 12, 5,000 users, 60 days; never used in training)",
           "rows": int(len(df)), "scam_payments": int(y.sum()),
           "legit_payments": int(round(w[~y].sum())), "scorers": {}}
    for name, scores in both.items():
        t = tiers(df, feats, scores)
        inter = np.isin(t, INTERRUPT)
        tip = t == "T1"
        legit = ~y
        conf = {
            "scam_interrupted": int(inter[y].sum()), "scam_missed": int((~inter[y]).sum()),
            "legit_interrupted": int(round(w[legit & inter].sum())),
            "legit_not_interrupted": int(round(w[legit & ~inter].sum())),
        }
        missed = df[y & ~inter]
        groups = []
        for pb, g in missed.groupby(missed["playbook"].fillna("unknown")):
            n_pb = int((df.loc[y, "playbook"].fillna("unknown") == pb).sum())
            groups.append({
                "scam_type": pb, "missed": int(len(g)), "of": n_pb,
                "median_inr": _r(g["amount"].median(), 0),
                "no_scam_message": _r((g["lure_max_conf_72h"].fillna(0) < 0.6).mean(), 3),
                "no_call_during_payment": _r((g["on_call"] != True).mean(), 3),  # noqa: E712
                "payee_older_than_90d": _r((g["payee_account_age_days"].fillna(0) > 90).mean(), 3),
                "under_2000_inr": _r((g["amount"] < 2000).mean(), 3),
            })
        out["scorers"][name] = {
            "confusion": conf,
            "scam_caught_rate": _r(inter[y].mean()),
            "scam_rupees_caught_rate": _r(df["amount"].to_numpy()[y & inter].sum() / df["amount"].to_numpy()[y].sum()),
            "false_alarms_per_1000": _r(1000 * w[legit & inter].sum() / w[legit].sum(), 2),
            "legit_tips_per_1000": _r(1000 * w[legit & tip].sum() / w[legit].sum(), 2),
            "precision": _r(inter[y].sum() / (inter[y].sum() + w[legit & inter].sum())) if inter.any() else None,
            "tiers": {k: int((t == k).sum()) for k in ("T0", "T1", "T2", "T3", "T4")},
            "by_scam_type": {pb: _r(inter[y & (df["playbook"] == pb).to_numpy()].mean(), 3)
                             for pb in sorted(df.loc[y, "playbook"].dropna().unique())},
            "missed_by_type": sorted(groups, key=lambda g: -g["missed"]),
        }
    out["live_scorer"] = predict.load().version
    out["rules_scorer"] = rule_scorer.MODEL_VERSION
    return out


def messages() -> dict:
    m = json.loads(LURE_METRICS.read_text(encoding="utf-8"))
    h = m["held_out_templates"]
    langs = {}
    for lang, x in h["by_language"].items():
        langs[lang] = {k: _r(x.get(k), 4) for k in ("messages", "scam_caught", "scam_called_normal", "scam_unclear",
                                                    "normal_false_alarm")}
    return {"model": m["version"], "held_out": "message templates never used in training",
            "messages": h["messages"], "scam_caught": _r(h["scam_caught"]), "scam_right_type": _r(h["scam_right_tag"]),
            "scam_unclear": _r(h["scam_unclear"]), "scam_called_normal": _r(h["scam_called_normal"]),
            "normal_false_alarm": _r(h["normal_false_alarm"]), "normal_unclear": _r(h["normal_unclear"]),
            "per_type_f1": {k: _r(v, 3) for k, v in h["per_class_f1"].items()}, "by_language": langs}


def new_scams() -> dict:
    with RED_TEAM.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    n = sum(int(r["n_scam_requests"]) for r in rows)
    missed = sum(float(r["ml_missed_share"]) * int(r["n_scam_requests"]) for r in rows)
    rules = sum(float(r["rules_missed_share"]) * int(r["n_scam_requests"]) for r in rows)
    shapes = {"call now, pay later (cool-off)": ("cooloff", "delayed"), "small first payment, then a big one": ("anchor",)}
    by_shape = {}
    for label, keys in shapes.items():
        rs = [r for r in rows if any(k in r["playbook_name"] for k in keys)]
        if rs:
            m = sum(float(r["ml_missed_share"]) * int(r["n_scam_requests"]) for r in rs)
            by_shape[label] = {"playbooks": len(rs), "missed": _r(m / sum(int(r["n_scam_requests"]) for r in rs), 3)}
    return {"source": "red team: 50 scams RUKO had never seen, written to evade it (attack_manifest.csv)",
            "playbooks": len(rows), "scam_payments": n, "missed": _r(missed / n, 3), "rules_missed": _r(rules / n, 3),
            "by_shape": by_shape,
            "examples": [{"name": r["playbook_name"], "title": r["title"], "missed": _r(float(r["ml_missed_share"]), 3)}
                         for r in sorted(rows, key=lambda r: -float(r["ml_missed_share"]))[:5]]}


def failure_cases(p: dict, msg: dict, new: dict) -> list[dict]:
    """Named weak spots, each with the number behind it (or marked as not measured) and the fix."""
    live = p["scorers"][p["live_scorer"]]
    worst_type = min(live["by_scam_type"].items(), key=lambda kv: kv[1]) if live["by_scam_type"] else None
    hi = msg["by_language"].get("hi", {})
    cases = [{
        "name": "New scams it has never seen",
        "measured": f"{100 * new['missed']:.0f}% of the red team's {new['scam_payments']} payments from "
                    f"{new['playbooks']} invented scams were not interrupted",
        "why": "they avoid the signals RUKO weighs most: the call ends long before the payment, the first "
               "payment is small and genuine-looking, the payee is not yet known as a mule",
        "fix": "the blue team groups the 1930 complaints these scams cause, drafts a playbook, two analysts "
               "approve it; cross-user signals (same UPI ID in many scam messages, new account paid by many) "
               "catch the money end without knowing the script",
    }, {
        "name": "Scam messages in Hindi",
        "measured": f"{100 * (hi.get('scam_caught') or 0):.0f}% of Hindi scam messages caught vs "
                    f"{100 * msg['scam_caught']:.0f}% overall; {100 * (hi.get('normal_false_alarm') or 0):.1f}% "
                    "of normal Hindi messages flagged",
        "why": "fewer Hindi training templates, and Devanagari word forms vary more",
        "fix": "more Hindi templates in the lure corpus; never let a message alone interrupt (it never does: rule 5)",
    }, {
        "name": "A call over WhatsApp or another app",
        "measured": "not measured on the simulator (it only has phone-network calls)",
        "why": "the phone sees that a VoIP call is on, not who is calling, so 'unknown caller' and the "
               "fraud-list check of the number are unknown (rule 1: unknown is never treated as safe)",
        "fix": "a VoIP call during a payment already counts for the call signal; add the chat app's contact check",
    }, {
        "name": "Many small payments over days",
        "measured": "salami and anchor patterns were added after the audit (R7); not yet re-measured on a held-out world",
        "why": "each payment alone looks ordinary and stays under the amount caps",
        "fix": "24-hour outflow to new payees against the user's usual maximum (in the engine now)",
    }]
    if worst_type:
        cases.append({
            "name": f"The weakest known scam type: {worst_type[0].replace('_', ' ')}",
            "measured": f"{100 * worst_type[1]:.0f}% of its payments interrupted on the held-out world",
            "why": "see 'Scams it missed' for what those payments had in common",
            "fix": "retrain with the new cross-user features (ML owner)",
        })
    cases.append({
        "name": "The simulated world is too easy",
        "measured": "mule account age alone separates mules almost perfectly (data/eval/realism/FINDINGS.md)",
        "why": "so the payment numbers mostly show that the pipeline works end to end; real numbers will be lower",
        "fix": "a more realistic simulator; then retrain and re-measure with the same commands",
    })
    return cases


def build(table: Path) -> dict:
    p, msg, new = payments(table), messages(), new_scams()
    return {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "command": "python -m evalsuite.accuracy --table ml/data/tables/dev_test.parquet",
            "payments": p, "messages": msg, "new_scams": new, "failure_cases": failure_cases(p, msg, new)}


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--table", type=Path, default=ROOT / "ml" / "data" / "tables" / "dev_test.parquet")
    a.add_argument("--out", type=Path, default=OUT)
    args = a.parse_args()
    res = build(args.table)
    args.out.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    live = res["payments"]["scorers"][res["payments"]["live_scorer"]]
    print(f"{res['payments']['live_scorer']}: scams caught {100 * live['scam_caught_rate']:.1f}%, "
          f"false alarms {live['false_alarms_per_1000']} per 1,000, confusion {live['confusion']}")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
