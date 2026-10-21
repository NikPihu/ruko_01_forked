"""Payment-graph evaluation: how early does RUKO flag mules? (docs/task-scam-watcher.md §9.8)

    PYTHONPATH=backend:ml:data python -m eval.graph_eval
    -> data/eval/graph_results.json and data/eval/charts/graph_eval.svg

Replays what RUKO would have seen in the task-scam-heavy eval world: only consenting users' episode
events, sent at their own time, and only the bank flows the visibility setting allows. Discovery
runs once a simulated day. A mule counts as flagged the first time it is a discovery suspect, has
crowd evidence, or is flagged in an episode by its bank's features (never by a registry hit).
Ground truth (is_mule, registry listing times) is used only to score.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from statistics import median

import httpx
import pandas as pd
from fastapi.testclient import TestClient

from api.main import create_app as create_engine
from eval.episode_eval import episodes_at, eval_config
from intel_mock.app import create_app as create_mock
from sim.generate import build_world, write_world

OUT = Path(__file__).resolve().parent
VISIBILITY = ("none", "partner", "dpip")


def replay(data: Path, events: list, visibility: str, days: list) -> dict:
    """First time each account was flagged, and the last discovery run's suspects."""
    mock = create_mock(data)
    mc = TestClient(mock)
    mc.post("/sim/settings", json={"visibility": visibility})
    intel = httpx.AsyncClient(transport=httpx.ASGITransport(app=mock), base_url="http://mock")
    engine = TestClient(create_engine(data, intel_client=intel, intel_cache_ttl_s=0, log_path=None, evidence_async=False))
    g = engine.app.state.graph
    first: dict[str, object] = {}
    suspects: list[dict] = []
    pending = list(days)

    def run_day(day) -> None:
        nonlocal suspects
        mc.post("/sim/clock", json={"set": day.isoformat()})
        suspects = engine.get("/v1/graph/suspects?min_band=low").json()["suspects"]
        for s in suspects:
            first.setdefault(s["upi_id"], day)
        for acc in list(g.marks):
            m = g.marks[acc]
            if (m.get("flagged") and not m.get("listed")) or g.account_signals(acc, day)["crowd"]:
                first.setdefault(acc, day)

    for e in events:
        while pending and pending[0] <= e["ts"]:
            run_day(pending.pop(0))
        mc.post("/sim/clock", json={"set": e["ts"].isoformat()})
        engine.post("/v1/episode", json=e["body"])
    for day in pending:
        run_day(day)
    return {"first": first, "suspects": suspects}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=11)
    a = p.parse_args()
    cfg = eval_config(a.seed)
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        tables = build_world(cfg)
        write_world(tables, cfg, data)
        ledger, users = tables["ledger"], tables["users"]
        accounts, reports = tables["accounts"], tables["reports"]
        events: list = []
        episodes_at(ledger, users, set(), events)
        events.sort(key=lambda e: e["ts"])
        start = ledger.ts.min().normalize()
        days = [start + timedelta(days=d) for d in range(1, cfg.n_days + 1)]

        mules = set(accounts[accounts.is_mule].upi_id)
        listed = (reports[(reports.identifier_type == "upi_id") & ~reports.is_false]
                  .groupby("identifier").listed_at.min().to_dict())
        results = {"world": {"seed": a.seed, "users": cfg.n_users, "mules": len(mules),
                             "episode_events": len(events)}, "visibility": {}}
        for vis in VISIBILITY:
            r = replay(data, events, vis, days)
            first = r["first"]
            seen = {m for m in mules if any(m == acc["upi_id"] for e in events for acc in e["body"]["accounts"])}
            flagged = {m for m in mules if m in first}
            before = [m for m in flagged if m not in listed or first[m] < listed[m]]
            earlier = [(listed[m] - first[m]).total_seconds() / 86_400 for m in before if m in listed]
            sus = r["suspects"]
            res = {"mules_seen_in_episodes": len(seen), "mules_flagged": len(flagged),
                   "flagged_before_registry": len(before),
                   "share_of_mules_flagged_before_registry": round(len(before) / max(len(mules), 1), 3),
                   "median_days_before_listing": round(median(earlier), 1) if earlier else None,
                   "never_listed_but_flagged": sum(1 for m in before if m not in listed),
                   "suspects": len(sus),
                   "suspect_precision": round(sum(s["upi_id"] in mules for s in sus) / len(sus), 3) if sus else None,
                   "analyst_list": len(mh := [s for s in sus if s["band"] in ("med", "high")]),
                   "analyst_list_precision": round(sum(s["upi_id"] in mules for s in mh) / len(mh), 3) if mh else None,
                   "rings": len({s["ring_id"] for s in sus if s["ring_id"]})}
            results["visibility"][vis] = res
            print(vis, json.dumps(res))
    (OUT / "graph_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (OUT / "charts").mkdir(exist_ok=True)
    (OUT / "charts" / "graph_eval.svg").write_text(chart(results), encoding="utf-8")
    print(f"wrote {OUT / 'graph_results.json'} and charts/graph_eval.svg")


def chart(r: dict) -> str:
    w, left, bar_h, gap, y = 720, 200, 34, 18, 80
    parts = []
    colours = {"none": "#9ca3af", "partner": "#7c3aed", "dpip": "#4c1d95"}
    for vis, s in r["visibility"].items():
        share = s["share_of_mules_flagged_before_registry"]
        bw = (w - left - 90) * share
        days = s["median_days_before_listing"]
        parts += [f'<text x="20" y="{y + 16}" font-size="13" fill="#1f2937">bank visibility: {vis}</text>',
                  f'<text x="20" y="{y + 30}" font-size="10" fill="#6b7280">median {days if days is not None else "-"} days early, '
                  f'analyst list precision {s["analyst_list_precision"] if s["analyst_list_precision"] is not None else "-"} '
                  f'({s["analyst_list"]} medium or high suspects)</text>',
                  f'<rect x="{left}" y="{y}" width="{w - left - 90}" height="{bar_h}" fill="#f3f4f6"/>',
                  f'<rect x="{left}" y="{y}" width="{bw:.1f}" height="{bar_h}" fill="{colours[vis]}"/>',
                  f'<text x="{left + bw + 8:.1f}" y="{y + 22}" font-size="13" font-weight="bold" fill="#1f2937">{share:.0%}</text>']
        y += bar_h + gap
    head = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {y + 10}" font-family="sans-serif">',
            f'<rect width="{w}" height="{y + 10}" fill="#ffffff"/>',
            '<text x="20" y="32" font-size="18" font-weight="bold" fill="#1f2937">Mules flagged before their first registry listing</text>',
            f'<text x="20" y="54" font-size="12" fill="#6b7280">{r["world"]["mules"]} mules; '
            f'{r["world"]["episode_events"]} episode events from consenting users</text>']
    return "\n".join(head + parts + ["</svg>"])


if __name__ == "__main__":
    main()
