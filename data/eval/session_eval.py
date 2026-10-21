"""Coached-session evaluation (contract c2-0.5): does the Pay-screen behaviour help?

    PYTHONPATH=backend:ml:data python -m eval.session_eval
    -> data/eval/session_results.json and data/eval/charts/session_eval.svg

Builds a world with many call-driven scams in a temp folder and replays payments through the real
engine (the same replay as eval/episode_eval.py) in two setups:
    A  the existing stack: phone context (calls, device, lures) + payee intel
    B  A + the Pay-screen session (dictated amount, paste after switching apps, app switches, ...)
twice each: known mules (today's intel answers) and fresh mules (no list or bank knows the payee,
so every payee lookup is unknown -- the case RUKO exists for).

Reports scam rupees interrupted (T2+) and paused (T3+), split into coached call scams and the rest,
false interruptions on a sample of honest payments, the same false-alarm rate per age band (age is
never an engine input; this is the fairness check), and an ablation that blanks one sign at a time.
Ground truth is used for scoring only.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import pandas as pd

from eval.episode_eval import replay
from sim.config import SimConfig
from sim.generate import build_world, write_world
from sim.session import COACHED_CALL

OUT = Path(__file__).resolve().parent
SETUPS = {"A": "existing stack", "B": "+ coached session"}
CONDITIONS = {"known_mules": "today's payee intel answers", "fresh_mules": "no list or bank knows the payee yet"}
ABLATIONS = {
    "dictated": ("amount_digits", "amount_median_gap_s", "amount_max_gap_s", "amount_gap_vs_usual"),
    "pasted_after_switch": ("payee_pasted", "pasted_within_s_of_return"),
    "app_switches": ("app_switches",),
    "abandoned": ("abandoned_flows_30m",),
    "hesitation": ("pay_screen_s",),
}


def eval_config(seed: int) -> SimConfig:
    return SimConfig(seed=seed, n_users=1500, n_days=30, scam_rate=0.05, playbook_weights={
        "digital_arrest": 0.3, "fake_customer_care": 0.2, "refund_qr": 0.15,
        "task_job": 0.15, "trading_group": 0.1, "fake_kyc_apk": 0.1})


def score(rows: pd.DataFrame, journeys: pd.DataFrame, users: pd.DataFrame, label: str) -> dict:
    sc = rows[rows.label_is_scam].merge(journeys[["journey_id", "playbook"]], on="journey_id")
    nm = rows[~rows.label_is_scam].merge(users[["user_id", "age_band"]], on="user_id")
    share = lambda d, t: round(float(d[d.tier >= t].amount.sum() / max(d.amount.sum(), 1)), 3)  # noqa: E731
    call = sc[sc.playbook.isin(COACHED_CALL)]
    return {
        "label": label,
        "inr_interrupted_t2": float(sc[sc.tier >= "T2"].amount.sum()),
        "share_inr_interrupted": share(sc, "T2"),
        "share_inr_paused": share(sc, "T3"),
        "call_scams_share_inr_interrupted": share(call, "T2"),
        "other_scams_share_inr_interrupted": share(sc[~sc.playbook.isin(COACHED_CALL)], "T2"),
        "journeys_alerted": int((sc.groupby("journey_id").tier.max() >= "T2").sum()),
        "journeys": int(sc.journey_id.nunique()),
        "false_interruptions_t2": int((nm.tier >= "T2").sum()),
        "false_interruptions_per_1000": round(1000 * float((nm.tier >= "T2").mean()), 2),
        "false_alerts_t1_per_1000": round(1000 * float((nm.tier >= "T1").mean()), 2),
        "false_per_1000_by_age_band": {b: round(1000 * float((g.tier >= "T2").mean()), 2)
                                       for b, g in nm.groupby("age_band")},
        "errors": int((rows.tier == "ERR").sum()),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=13)
    p.add_argument("--normal-sample", type=int, default=2000)
    a = p.parse_args()

    cfg = eval_config(a.seed)
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        write_world(build_world(cfg), cfg, data)
        ledger, users = pd.read_parquet(data / "ledger.parquet"), pd.read_parquet(data / "users.parquet")
        journeys, events = pd.read_parquet(data / "journeys.parquet"), pd.read_parquet(data / "context_events.parquet")
        # The engine's baseline must not contain the scam being judged (as in episode_eval).
        engine_data = data / "engine"
        engine_data.mkdir()
        users.to_parquet(engine_data / "users.parquet", index=False)
        ledger[~ledger.label_is_scam & (ledger.flow != "scam_bait")].to_parquet(engine_data / "ledger.parquet", index=False)

        ledger["user_id"] = ledger.from_upi.map(dict(zip(users.upi_id, users.user_id)))
        mine = ledger[ledger.user_id.notna()]
        scam = mine[mine.label_is_scam]
        normal = mine[~mine.label_is_scam].sample(min(a.normal_sample, (~mine.label_is_scam).sum()), random_state=a.seed)
        rows = pd.concat([scam, normal]).sort_values("ts", kind="stable")
        events = events.sort_values("ts", kind="stable")

        results = {"world": {"seed": a.seed, "users": cfg.n_users, "journeys": int(len(journeys)),
                             "scam_payments": int(len(scam)), "scam_inr": float(scam.amount.sum()),
                             "playbooks": journeys.playbook.value_counts().to_dict(),
                             "normal_sample": int(len(normal))},
                   "conditions": {}, "ablation_fresh_mules": {}}
        for cond in CONDITIONS:
            fresh = cond == "fresh_mules"
            results["conditions"][cond] = {}
            for s, label in SETUPS.items():
                rows["tier"] = replay(data, engine_data, rows, events, {}, "A", fresh, session=s == "B")
                res = score(rows, journeys, users, label)
                results["conditions"][cond][s] = res
                print(cond, s, json.dumps(res))
        for name, fields in ABLATIONS.items():
            rows["tier"] = replay(data, engine_data, rows, events, {}, "A", True, session=True, drop=fields)
            res = score(rows, journeys, users, f"B without {name}")
            results["ablation_fresh_mules"][name] = res
            print("ablation", name, json.dumps(res))

    (OUT / "session_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (OUT / "charts").mkdir(exist_ok=True)
    (OUT / "charts" / "session_eval.svg").write_text(chart(results), encoding="utf-8")
    print(f"wrote {OUT / 'session_results.json'} and charts/session_eval.svg")


def chart(r: dict) -> str:
    """Share of scam rupees interrupted (T2+), with and without the session, known vs fresh mules."""
    w, left, bar_h, gap = 760, 250, 30, 12
    colours = {"A": "#9ca3af", "B": "#0f766e"}
    y, parts = 84, []
    for cond, setups in r["conditions"].items():
        parts.append(f'<text x="20" y="{y}" font-size="14" font-weight="bold" fill="#1f2937">'
                     f'{cond.replace("_", " ")}: {CONDITIONS[cond]}</text>')
        y += 14
        for k, s in setups.items():
            share = s["share_inr_interrupted"]
            bw = (w - left - 90) * share
            parts += [f'<text x="20" y="{y + 15}" font-size="12" fill="#1f2937">{k}: {s["label"]}</text>',
                      f'<text x="20" y="{y + 28}" font-size="10" fill="#6b7280">false alarms {s["false_interruptions_per_1000"]} per 1,000 honest payments</text>',
                      f'<rect x="{left}" y="{y}" width="{w - left - 90}" height="{bar_h}" fill="#f3f4f6"/>',
                      f'<rect x="{left}" y="{y}" width="{bw:.1f}" height="{bar_h}" fill="{colours[k]}"/>',
                      f'<text x="{left + bw + 8:.1f}" y="{y + 20}" font-size="13" font-weight="bold" fill="#1f2937">{share:.0%}</text>']
            y += bar_h + gap
        y += 26
    head = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {y}" font-family="sans-serif">',
            f'<rect width="{w}" height="{y}" fill="#ffffff"/>',
            '<text x="20" y="32" font-size="18" font-weight="bold" fill="#1f2937">Scam rupees interrupted (T2 or higher)</text>',
            f'<text x="20" y="54" font-size="12" fill="#6b7280">{r["world"]["journeys"]} scam journeys, '
            f'Rs {r["world"]["scam_inr"]:,.0f} paid; false alarms on {r["world"]["normal_sample"]} honest payments</text>']
    return "\n".join(head + parts + ["</svg>"])


if __name__ == "__main__":
    main()
