"""How well the playbook search (backend/api/playbook_search.py) finds scams on a replay table.

    PYTHONPATH=backend;ml;data python -m model.search_eval --table ml/data/tables/dev_test_v3.parquet

Per scam type (ground truth `playbook`, scoring only, rule 9): share of scam payments with any match,
with the right playbook on top, and the median similarity; for honest payments: share with any match
and per 1,000 above each similarity bar. Writes model/artifacts/search_eval.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from api import playbook_search as ps
from model.steps_table import table_steps

OUT = Path(__file__).resolve().parent / "artifacts" / "search_eval.json"
BARS = (0.3, 0.5, 0.7, 0.9)


def run(df: pd.DataFrame) -> dict:
    steps = table_steps(df)
    tops = []
    for rec in steps.to_dict("records"):
        seen = {k: (None if np.isnan(v) else bool(v)) for k, v in rec.items()}
        hit = ps.search(seen, ps.PLAYBOOKS, top=1)
        tops.append((hit[0]["name"], hit[0]["similarity"]) if hit else (None, 0.0))
    top = pd.DataFrame(tops, columns=["name", "sim"], index=df.index)
    scam = df["label_is_scam"].astype(bool)
    out: dict = {"payments": int(len(df)), "scam_payments": int(scam.sum()), "playbooks": ps.SOURCE, "by_scam": {}}
    for pb, g in df[scam].groupby(df["playbook"].fillna("unknown")):
        t = top.loc[g.index]
        out["by_scam"][pb] = {"n": int(len(g)), "any_match": round(float((t.sim > 0).mean()), 3),
                              "right_on_top": round(float((t.name == pb).mean()), 3),
                              "median_similarity": round(float(t.sim.median()), 3),
                              "top_names": t.name.fillna("-").value_counts().head(3).to_dict()}
    legit = top[~scam]
    out["honest"] = {"n": int(len(legit)), "any_match": round(float((legit.sim > 0).mean()), 4),
                     "per_1000_at_or_above": {str(b): round(1000 * float((legit.sim >= b).mean()), 2) for b in BARS},
                     "top_names": legit.name.dropna().value_counts().head(6).to_dict()}
    out["scam_at_or_above"] = {str(b): round(float((top[scam].sim >= b).mean()), 3) for b in BARS}
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--table", nargs="+", required=True)
    p.add_argument("--out", default=str(OUT))
    a = p.parse_args()
    res = {Path(t).stem: run(pd.read_parquet(t)) for t in a.table}
    Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
