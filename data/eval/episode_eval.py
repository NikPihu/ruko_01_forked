"""Task-scam evaluation for the episode watcher (docs/task-scam-watcher.md §7).

    PYTHONPATH=backend:ml:data python -m eval.episode_eval
    -> data/eval/episode_results.json and data/eval/charts/episode_eval.svg

Builds a task-scam-heavy world in a temp folder, then replays payments through the real engine
(in-process, mock intel at each payment's own time) in three setups:
    A  the existing stack: phone context (calls, device, lures) + today's payee intel
    B  A + the phone's episode summary (c2-0.3)
    C  B + the payment graph's crowd and money-loop signals (c2-0.4, §9)
Each setup runs twice: with known mules (today's intel answers) and with fresh mules (no list or
bank knows the payee yet, so every payee lookup is unknown). Reports task-scam rupees interrupted
(T2+) and paused (T3+), the payment number of the first alert, and the false interruption rate on
a sample of normal payments. Ground truth is used for scoring
only; the engine sees what a phone and a PSP could see.
"""
from __future__ import annotations

import argparse
import json
import random
import tempfile
from datetime import timedelta
from pathlib import Path

import httpx
import pandas as pd
from fastapi.testclient import TestClient

from api.main import create_app as create_engine
from features.bank_sms import Txn
from features.episode import EpisodeTracker, load_rules
from features.offline_episode import IGNORED_BY_PARSER, WARMUP_DAYS
from intel_mock.app import create_app as create_mock
from sim.config import SimConfig
from sim.generate import build_world, write_world

OUT = Path(__file__).resolve().parent
TASK_PLAYBOOKS = {"task_job"}
SETUPS = {"A": "existing stack", "B": "+ episode (phone)", "C": "+ episode + payment graph"}
CONDITIONS = {"known_mules": "today's payee intel answers", "fresh_mules": "no list or bank knows the payee yet"}


def eval_config(seed: int) -> SimConfig:
    return SimConfig(seed=seed, n_users=1500, n_days=30, scam_rate=0.05, playbook_weights={
        "digital_arrest": 0.15, "trading_group": 0.1, "task_job": 0.5,
        "fake_kyc_apk": 0.1, "refund_qr": 0.08, "fake_customer_care": 0.07})


# ---------- what the phone would have sent ----------

def phone_context(events: pd.DataFrame, ts, session: bool = False) -> dict:
    """call / device / lures as the phone saw them at `ts` (no episode). With `session`, also the
    Pay-screen behaviour of the payment at `ts` (c2-0.5, from its `pay_session` event)."""
    ctx: dict = {"call": None, "device": None, "lures": []}
    if session:
        ses = events[(events.event_type == "pay_session") & (events.ts == ts)]
        ctx["session"] = json.loads(ses["attrs"].iloc[-1]) if len(ses) else None
    calls = events[events.event_type.isin(["call_started", "call_ended"])]
    started = calls[(calls.event_type == "call_started") & (calls.ts <= ts)]
    if len(started):
        last = started.iloc[-1]
        a = json.loads(last["attrs"])
        ended = calls[(calls.event_type == "call_ended") & (calls.ts >= last.ts)]
        end_ts = ended.ts.iloc[0] if len(ended) else None
        live = end_ts is None or end_ts >= ts
        if live or (ts - end_ts) <= timedelta(minutes=30):
            ctx["call"] = {"active": bool(live), "kind": a.get("call_kind"), "direction": a.get("direction"),
                           "caller_number": None if a.get("in_contacts") else a.get("caller_number"),
                           "caller_in_contacts": a.get("in_contacts"),
                           "started_min_ago": round((ts - last.ts).total_seconds() / 60, 1),
                           "ended_min_ago": None if live else round((ts - end_ts).total_seconds() / 60, 1)}
    inst = events[(events.event_type == "app_installed") & (events.ts <= ts) & (events.ts >= ts - timedelta(hours=24))]
    remote = [json.loads(x) for x in inst[inst["attrs"].str.contains('"is_remote_access": true')]["attrs"]]
    side = inst["attrs"].str.contains('"sideloaded": true').any()
    rem_ts = inst[inst["attrs"].str.contains('"is_remote_access": true')].ts
    ctx["device"] = {"remote_access_active": None,
                     "remote_app_installed_min_ago": round((ts - rem_ts.iloc[-1]).total_seconds() / 60, 1) if remote else None,
                     "untrusted_accessibility": bool((events[(events.event_type == "accessibility_enabled") & (events.ts <= ts)]).shape[0]) or None,
                     "sideloaded_last_24h": bool(side)}
    lures = events[events.event_type.isin(["sms_lure", "notification_lure"]) & (events.ts <= ts)
                   & (events.ts >= ts - timedelta(hours=72))]
    for r in lures.itertuples():
        a = json.loads(r.attrs)
        ctx["lures"].append({"tag": a["tag"], "conf": a["conf"], "min_ago": round((ts - r.ts).total_seconds() / 60, 1)})
    return ctx


def episodes_at(ledger: pd.DataFrame, users: pd.DataFrame, wanted: set[str],
                events_out: list | None = None) -> dict[str, dict]:
    """The phone's episode summary just before each wanted payment (same rules as the phone).

    With `events_out`, also collects the episode events (c2-0.4) a phone with "Share suspicious
    accounts" on would send: one per state change, with the episode's accounts."""
    rules = load_rules()
    u2u = dict(zip(users.upi_id, users.user_id))
    consent = dict(zip(users.user_id, users.sms_consent))
    warm_until = ledger.ts.min() + timedelta(days=WARMUP_DAYS)
    trackers: dict[str, EpisodeTracker] = {}
    out: dict[str, dict] = {}
    for r in ledger.sort_values("ts", kind="stable").itertuples(index=False):
        ts, payer, payee = r.ts.timestamp(), u2u.get(r.from_upi), u2u.get(r.to_upi)
        if payee and r.flow not in IGNORED_BY_PARSER and r.ts >= warm_until:
            t = trackers.setdefault(payee, EpisodeTracker(rules, bool(consent[payee])))
            before = (t.ep.state, len(t.ep.bait), {b.counterparty for b in t.ep.bait})
            t.add(Txn(ts, float(r.amount), "in", r.from_upi, from_sms=True))
            if events_out is not None:
                _event(events_out, payee, t, before, r.ts, rules["version"])
        if payer:
            t = trackers.setdefault(payer, EpisodeTracker(rules, bool(consent[payer])))
            if r.tx_id in wanted:
                out[r.tx_id] = t.summary(ts, payee=r.to_upi)
            before = (t.ep.state, len(t.ep.outs), None)
            t.add(Txn(ts, float(r.amount), "out", r.to_upi.lower()))
            if events_out is not None and r.ts >= warm_until:
                _event(events_out, payer, t, before, r.ts, rules["version"])
    return out


def _event(events_out: list, user: str, t: EpisodeTracker, before: tuple, ts, version: str) -> None:
    """The c2-0.4 trigger for this change, if any (§8.1), with up to 10 of the episode's accounts."""
    ep, (state0, n0, senders0) = t.ep, before
    if ep.state not in ("watching", "active"):
        return
    if state0 != ep.state:
        trigger = ep.state
    elif ep.state == "active" and len(ep.outs) > n0 and senders0 is None:
        trigger = "out_payment"
    elif senders0 is not None and len(ep.bait) > n0 and ep.bait[-1].counterparty not in senders0:
        trigger = "bait"
    else:
        return
    accounts = []
    for b in ep.bait:
        if b.counterparty:
            accounts.append({"upi_id": b.counterparty, "role": "bait_sender", "n": 1, "inr": b.amount,
                             "first_seen_min_ago": max(0.0, (ts.timestamp() - b.ts) / 60)})
    for i, o in enumerate(ep.outs):
        if o.counterparty:
            accounts.append({"upi_id": o.counterparty, "role": "payee", "n": 1, "inr": o.amount,
                             "first_seen_min_ago": max(0.0, (ts.timestamp() - o.ts) / 60), "via": "this_app", "step": i + 1})
    events_out.append({"ts": ts, "user_id": user, "body": {
        "event_id": f"ev_{len(events_out)}", "episode_id": f"ep_{user}_{int(ep.start_ts)}", "user_id": user,
        "ts": ts.isoformat(), "trigger": trigger, "rules_version": version,
        "summary": t.summary(ts.timestamp()), "accounts": accounts[-10:]}})


# ---------- replay ----------

def replay(data: Path, engine_data: Path, rows: pd.DataFrame, events: pd.DataFrame, eps: dict,
           setup: str, fresh: bool, episode_events: list | None = None, session: bool = False,
           drop: tuple[str, ...] = ()) -> list[str]:
    mock = create_mock(data)
    mock_client = TestClient(mock)
    # Fresh mules: every payee lookup fails, so NPCI, bank, registry and FRI all count as unknown.
    transport = httpx.MockTransport(lambda req: httpx.Response(503)) if fresh else httpx.ASGITransport(app=mock)
    intel = httpx.AsyncClient(transport=transport, base_url="http://mock")
    engine = TestClient(create_engine(engine_data, intel_client=intel, intel_cache_ttl_s=0, log_path=None,
                                      evidence_async=False, intel_budget_s=5.0))
    by_user = {u: g for u, g in events.groupby("user_id")}
    pending = list(episode_events or []) if setup == "C" else []
    tiers = []
    for r in rows.itertuples(index=False):
        # Setup C: the phones' episode events up to now reach the engine first (they fill the graph).
        while pending and pending[0]["ts"] <= r.ts:
            e = pending.pop(0)
            mock_client.post("/sim/clock", json={"set": e["ts"].isoformat()})
            engine.post("/v1/episode", json=e["body"])
        mock_client.post("/sim/clock", json={"set": r.ts.isoformat()})
        ev = by_user.get(r.user_id, events.iloc[0:0])
        ctx = phone_context(ev, r.ts, session)
        if ctx.get("session"):  # ablation: these session fields count as unknown
            ctx["session"].update({k: None for k in drop})
        if setup in ("B", "C"):
            ctx["episode"] = eps.get(r.tx_id)
        body = {"request_id": r.tx_id, "user_id": r.user_id, "payee_upi_id": r.to_upi, "amount_inr": float(r.amount),
                "entry_method": r.entry_method, "ts": r.ts.isoformat(), "context": ctx}
        if r.label_is_scam:
            body["payer_says"] = "company"
        res = engine.post("/v1/decide", json=body)
        tiers.append(res.json()["tier"] if res.status_code == 200 else "ERR")
    return tiers


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--normal-sample", type=int, default=1500)
    a = p.parse_args()

    cfg = eval_config(a.seed)
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        write_world(build_world(cfg), cfg, data)
        ledger, users = pd.read_parquet(data / "ledger.parquet"), pd.read_parquet(data / "users.parquet")
        journeys, events = pd.read_parquet(data / "journeys.parquet"), pd.read_parquet(data / "context_events.parquet")
        # The engine's user baseline (largest payment, known payees) must not include the scam being
        # judged: features/user_baseline.py reads the whole ledger, so give it the honest part only.
        engine_data = data / "engine"
        engine_data.mkdir()
        users.to_parquet(engine_data / "users.parquet", index=False)
        ledger[~ledger.label_is_scam & (ledger.flow != "scam_bait")].to_parquet(engine_data / "ledger.parquet", index=False)

        u2u = dict(zip(users.upi_id, users.user_id))
        ledger["user_id"] = ledger.from_upi.map(u2u)
        warm_end = ledger.ts.min() + timedelta(days=WARMUP_DAYS)
        mine = ledger[ledger.user_id.notna() & (ledger.ts >= warm_end)]
        # Journeys that start during the warm-up lose their bait to it; leave them out.
        task_j = journeys[journeys.playbook.isin(TASK_PLAYBOOKS) & (journeys.started_at >= warm_end)].copy()
        task_j["visible"] = (task_j.variant == "rewards") & task_j.user_id.map(dict(zip(users.user_id, users.sms_consent)))
        scam = mine[mine.journey_id.isin(set(task_j.journey_id))]
        normal = mine[~mine.label_is_scam].sample(min(a.normal_sample, (~mine.label_is_scam).sum()), random_state=a.seed)
        rows = pd.concat([scam, normal]).sort_values("ts", kind="stable")
        episode_events: list = []
        eps = episodes_at(ledger, users, set(rows.tx_id), episode_events)
        episode_events.sort(key=lambda e: e["ts"])
        events = events.sort_values("ts", kind="stable")

        results = {"world": {"seed": a.seed, "users": cfg.n_users, "task_journeys": int(len(task_j)),
                             "task_payments": int(len(scam)), "task_inr": float(scam.amount.sum()),
                             "normal_sample": int(len(normal)),
                             "variants": task_j.variant.value_counts().to_dict(),
                             "visible_to_watcher": int(task_j.visible.sum()),
                             "episode_events": len(episode_events)},
                   "conditions": {}}
        for cond in CONDITIONS:
            results["conditions"][cond] = {}
            for s, label in SETUPS.items():
                if s == "C" and not graph_ready():
                    continue
                rows["tier"] = replay(data, engine_data, rows, events, eps, s, fresh=cond == "fresh_mules",
                                      episode_events=episode_events)
                sc = rows[rows.label_is_scam].merge(task_j[["journey_id", "variant", "visible"]], on="journey_id")
                seen = sc[sc.visible]
                sc["n"] = sc.groupby("journey_id").cumcount() + 1
                first = sc[sc.tier >= "T2"].groupby("journey_id").n.min()
                nm = rows[~rows.label_is_scam]
                res = {"label": label,
                       "inr_interrupted_t2": float(sc[sc.tier >= "T2"].amount.sum()),
                       "inr_paused_t3": float(sc[sc.tier >= "T3"].amount.sum()),
                       "share_inr_interrupted": round(float(sc[sc.tier >= "T2"].amount.sum() / max(sc.amount.sum(), 1)), 3),
                       "journeys_alerted": int(first.count()), "journeys": int(sc.journey_id.nunique()),
                       "median_first_alert_payment": float(first.median()) if len(first) else None,
                       "by_variant": {v: int((sc[(sc.variant == v)].groupby("journey_id").tier.max() >= "T2").sum())
                                      for v in sc.variant.dropna().unique()},
                       # Journeys the watcher can see at all: rewards first, and SMS checks allowed.
                       "visible": {"journeys": int(seen.journey_id.nunique()),
                                   "share_inr_interrupted": round(float(seen[seen.tier >= "T2"].amount.sum() / max(seen.amount.sum(), 1)), 3),
                                   "share_inr_paused": round(float(seen[seen.tier >= "T3"].amount.sum() / max(seen.amount.sum(), 1)), 3)},
                       "false_interruptions_t2": int((nm.tier >= "T2").sum()),
                       "false_interruption_rate": round(float((nm.tier >= "T2").mean()), 4),
                       "errors": int((rows.tier == "ERR").sum())}
                results["conditions"][cond][s] = res
                print(cond, s, label, json.dumps(res))

    (OUT / "episode_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (OUT / "charts").mkdir(exist_ok=True)
    (OUT / "charts" / "episode_eval.svg").write_text(chart(results), encoding="utf-8")
    print(f"wrote {OUT / 'episode_results.json'} and charts/episode_eval.svg")


def graph_ready() -> bool:
    """Setup C needs the payment graph (backend/graph, c2-0.4)."""
    try:
        import graph.store  # noqa: F401
        return True
    except ImportError:
        return False


def chart(r: dict) -> str:
    """Share of task-scam rupees interrupted (T2+) per setup, for known and fresh mules."""
    w, left, bar_h, gap = 760, 250, 30, 12
    colours = {"A": "#9ca3af", "B": "#7c3aed", "C": "#4c1d95"}
    y = 84
    parts = []
    for cond, setups in r["conditions"].items():
        parts.append(f'<text x="20" y="{y}" font-size="14" font-weight="bold" fill="#1f2937">{cond.replace("_", " ")}: {CONDITIONS[cond]}</text>')
        y += 14
        for k, s in setups.items():
            share = s["share_inr_interrupted"]
            bw = (w - left - 90) * share
            parts += [f'<text x="20" y="{y + 15}" font-size="12" fill="#1f2937">{k}: {s["label"]}</text>',
                      f'<text x="20" y="{y + 28}" font-size="10" fill="#6b7280">false alarms {s["false_interruption_rate"]:.2%}, first alert at payment {s["median_first_alert_payment"] or "-"}</text>',
                      f'<rect x="{left}" y="{y}" width="{w - left - 90}" height="{bar_h}" fill="#f3f4f6"/>',
                      f'<rect x="{left}" y="{y}" width="{bw:.1f}" height="{bar_h}" fill="{colours[k]}"/>',
                      f'<text x="{left + bw + 8:.1f}" y="{y + 20}" font-size="13" font-weight="bold" fill="#1f2937">{share:.0%}</text>']
            y += bar_h + gap
        y += 26
    head = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {y}" font-family="sans-serif">',
            f'<rect width="{w}" height="{y}" fill="#ffffff"/>',
            '<text x="20" y="32" font-size="18" font-weight="bold" fill="#1f2937">Task-scam rupees interrupted (T2 or higher)</text>',
            f'<text x="20" y="54" font-size="12" fill="#6b7280">{r["world"]["task_journeys"]} task-scam journeys '
            f'({r["world"]["visible_to_watcher"]} visible to the watcher), Rs {r["world"]["task_inr"]:,.0f} paid; '
            f'false alarms on {r["world"]["normal_sample"]} normal payments</text>']
    return "\n".join(head + parts + ["</svg>"])


if __name__ == "__main__":
    main()
