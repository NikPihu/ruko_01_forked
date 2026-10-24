"""One run: playbook -> world -> records -> server -> verdict -> files on disk.

The chain is four steps, each in its own file, so a later stage (the blue team) only has to read
the files this writes, or add a sink in sinks.py:

    scenario.build()   a world where this playbook is the only scam
    records.stream()   the records a phone would send, in time order
    server.Server      the real engine, in this process or over HTTP
    judge.Verdict      threat score -> normal or not; the playbook's share decides a breakthrough
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pandas as pd
import yaml

from interface_script import records, scenario, server as server_mod, sinks
from interface_script.judge import Verdict


def scoring_users(sc, cfg: dict) -> set[str]:
    """Everyone the playbook attacked, plus a fixed number of honest users.

    The honest ones give the false-alarm rate. Users nobody scores are left out: sending their
    payments only cost time, because each scored user already sends all of their own history.
    """
    victims = set(sc.victims)
    n = int(cfg["scenario"].get("honest_users", 40))
    others = sorted(set(sc.tables["users"].user_id) - victims)
    rng = random.Random(cfg["world"]["seed"])
    return victims | set(rng.sample(others, min(n, len(others))))


def run(playbook_ref: str, cfg: dict, out: Path, log=print) -> Verdict:
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    log(f"playbook: {playbook_ref}")

    sc = scenario.build(playbook_ref, cfg, out=out / "world", log=log)
    srv = server_mod.open_server(cfg["server"]["target"], sc.world_dir,
                                 cfg["server"].get("timeout_s", 20), cfg["server"].get("scorer", "ml"))
    health = srv.health()
    scorer = health.get("model_version") or health.get("error") or "?"
    log(f"  server: {srv.label}  scorer={scorer}")

    v = Verdict(playbook=sc.name, scorer=str(scorer),
                normal_max_score=cfg["judge"]["normal_max_score"],
                breakthrough_share=cfg["judge"]["breakthrough_share"])
    who = scoring_users(sc, cfg)
    total = records.payments_for(sc.world_dir, who)
    log(f"  sending {total:,} payments from {len(who):,} users "
        f"({len(sc.victims)} attacked, {len(who) - len(sc.victims)} honest)")
    rows: list[dict] = []
    sent = {"pay": 0, "episode": 0}
    try:
        with (out / "requests.jsonl").open("w", encoding="utf-8") as freq, \
             (out / "responses.jsonl").open("w", encoding="utf-8") as fres:
            for rec in records.stream(sc.world_dir, seed=cfg["world"]["seed"],
                                      warmup_days=cfg["world"]["warmup_days"],
                                      normal_sample=cfg["scenario"]["normal_sample"],
                                      only_users=who):
                if rec["body"].get("ts"):
                    srv.clock(rec["body"]["ts"])  # the mock services answer as of this message's time
                if rec["kind"] == "episode":
                    srv.post("/v1/episode", rec["body"])
                    sent["episode"] += 1
                    continue
                body, label = rec["body"], rec["label"]
                status, reply = srv.post("/v1/decide", body)
                sent["pay"] += 1
                freq.write(json.dumps(body, default=str) + "\n")
                fres.write(json.dumps({"request_id": body["request_id"], "status": status, "reply": reply},
                                      default=str) + "\n")
                rows.append(v.add(label, reply, status))
                # The phone reports the payment went through, so "paid here before" counts (c2-0.6).
                srv.post("/v1/payment/outcome", {"request_id": body["request_id"], "user_id": body["user_id"],
                                                 "payee_upi_id": body["payee_upi_id"],
                                                 "amount_inr": body["amount_inr"], "status": "completed",
                                                 "ts": body["ts"]})
                if sent["pay"] % 100 == 0 or sent["pay"] == total:
                    # A line a UI can parse for a real progress bar: PROGRESS <sent> <total> <scam judged>
                    log(f"PROGRESS {sent['pay']} {total} {v.scam_judged}")
                if sent["pay"] % 500 == 0:
                    done = sent["pay"] / total if total else 1.0
                    el = time.perf_counter() - t0
                    log(f"  {sent['pay']:,}/{total:,} payments sent ({done:.0%}), {v.scam_judged} scam judged "
                        f"({el:.0f}s, about {el / max(done, 1e-9) - el:.0f}s left)")
    finally:
        srv.close()

    df = pd.DataFrame(rows)
    df.to_csv(out / "results.csv", index=False)
    (out / "verdict.json").write_text(json.dumps(v.summary(), indent=2), encoding="utf-8")
    (out / "summary.txt").write_text(
        f"{v.text()}\n\n  payments sent         {sent['pay']:,}\n"
        f"  episode events sent   {sent['episode']:,}\n  seconds               {time.perf_counter() - t0:.0f}\n",
        encoding="utf-8")
    # The playbook exactly as it was run (from the library, a file anywhere, or another folder).
    (out / "playbook.yaml").write_text(yaml.safe_dump(sc.playbook, sort_keys=False, allow_unicode=True),
                                       encoding="utf-8")

    sinks.emit(v, sc, df, out, log=log)
    log("")
    log(v.text())
    log(f"\n  results -> {out}")
    return v
