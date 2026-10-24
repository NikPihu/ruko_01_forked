"""A3: does the lure model catch scam messages written the way AI writes them?

    PYTHONPATH=backend;ml;data python -m evalsuite.ai_lures
    -> backend/evalsuite/ai_lures_results.json (served by /v1/eval, shown on the console's Evaluation page)

`ai_lures.jsonl` holds polished, personalised, urgent scam messages in English, Hindi and Hinglish
with phrasings the model never saw, plus honest look-alikes (real OTPs, real bank and RBI notices,
real refunds, family and work messages). Scoring reuses the model's own Python scorer
(ml/model/lure_train.py: score_json + scam_hit, the phone's rule) and the phone's send threshold,
so this measures exactly what the app would send. The model itself is in ml/.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from model.lure_train import SEND_THRESHOLD, scam_hit, score_json

HERE = Path(__file__).resolve().parent
TEST_SET = HERE / "ai_lures.jsonl"
OUT = HERE / "ai_lures_results.json"
MODEL = HERE.parents[1] / "ml" / "model" / "artifacts" / "lure.json"
BASELINE_CAUGHT = 0.84   # ml/PLAN.md: unseen templates, today's lure model


def run(model_path: Path = MODEL, test_set: Path = TEST_SET) -> dict:
    model = json.loads(model_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in test_set.read_text(encoding="utf-8").splitlines() if line.strip()]
    by: dict[str, dict] = defaultdict(lambda: {"n": 0, "flagged": 0, "right_tag": 0})
    misses, false_alarms = [], []
    for r in rows:
        _, _, probs = score_json(model, r["text"])
        tag, conf = scam_hit(model, probs)
        flagged = tag != "normal" and conf >= SEND_THRESHOLD
        for key in (r["tag"] if r["tag"] == "normal" else "scam", f"lang:{r['lang']}", f"tag:{r['tag']}"):
            by[key]["n"] += 1
            by[key]["flagged"] += flagged
            by[key]["right_tag"] += flagged and tag == r["tag"]
        if r["tag"] != "normal" and not flagged:
            misses.append({"tag": r["tag"], "lang": r["lang"], "got": tag, "conf": round(conf, 3), "text": r["text"][:90]})
        if r["tag"] == "normal" and flagged:
            false_alarms.append({"lang": r["lang"], "got": tag, "conf": round(conf, 3), "text": r["text"][:90]})
    scam, normal = by["scam"], by["normal"]
    langs = {k[5:]: v for k, v in by.items() if k.startswith("lang:")}
    return {
        "model_version": model.get("version"),
        "test_set": test_set.name, "messages": len(rows), "scam_messages": scam["n"], "honest_messages": normal["n"],
        "caught": round(scam["flagged"] / scam["n"], 3) if scam["n"] else None,
        "right_scam_type": round(scam["right_tag"] / scam["n"], 3) if scam["n"] else None,
        "false_alarms": round(normal["flagged"] / normal["n"], 3) if normal["n"] else None,
        "baseline_caught_unseen_templates": BASELINE_CAUGHT,
        "send_threshold": SEND_THRESHOLD,
        "by_scam_type": {k[4:]: round(v["flagged"] / v["n"], 3) for k, v in by.items() if k.startswith("tag:") and k != "tag:normal"},
        "by_language": {lang: {"messages": v["n"], "flagged": v["flagged"]} for lang, v in langs.items()},
        "missed": misses, "false_alarm_examples": false_alarms,
    }


def main() -> None:
    res = run()
    OUT.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"AI-written scam messages caught: {res['caught']:.0%} (unseen templates baseline {BASELINE_CAUGHT:.0%}), "
          f"right scam type {res['right_scam_type']:.0%}, false alarms on honest messages {res['false_alarms']:.0%}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
