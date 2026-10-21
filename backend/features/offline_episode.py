"""Rebuild every user's task-scam episode from the ledger, as the phone would have seen it.

    PYTHONPATH=backend:ml:data python -m features.offline_episode --data data/
    -> data/episode_features.parquet: one row per payment a RUKO user made, keyed by tx_id, with the
       episode_* features as of that moment (before the payment). Join it into the training table.

What the phone sees (docs/task-scam-watcher.md §7):
- money in only for users with SMS consent, through bank SMS. Cashback alerts are ignored by the
  phone's parser, so they are skipped here too. Without consent the bait fields stay null.
- money out from this app's own history, with the exact payee.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from features.bank_sms import Txn
from features.episode import STATE_CODE, EpisodeTracker, load_rules

IGNORED_BY_PARSER = {"cashback"}   # BankSms.SKIP drops these alerts on the phone
# The phone backfills 30 days of history when the watcher is switched on. The simulated world has
# no history before day 1, so the first days only build history: no bait counts, no rows are kept.
WARMUP_DAYS = 7


def rebuild(ledger: pd.DataFrame, users: pd.DataFrame, rules: dict | None = None,
            warmup_days: float = WARMUP_DAYS) -> pd.DataFrame:
    rules = rules or load_rules()
    upi_to_user = dict(zip(users.upi_id, users.user_id))
    consent = dict(zip(users.user_id, users.sms_consent)) if "sms_consent" in users else {}
    led = ledger.sort_values("ts", kind="stable")
    warm_until = led.ts.min().timestamp() + warmup_days * 86_400 if len(led) else 0
    rows = []
    trackers: dict[str, EpisodeTracker] = {}

    def tracker(uid: str) -> EpisodeTracker:
        if uid not in trackers:
            trackers[uid] = EpisodeTracker(rules, sms_read=bool(consent.get(uid, False)))
        return trackers[uid]

    for r in led.itertuples(index=False):
        ts = r.ts.timestamp()
        payer, payee = upi_to_user.get(r.from_upi), upi_to_user.get(r.to_upi)
        warm = ts < warm_until
        if payee is not None and r.flow not in IGNORED_BY_PARSER and not warm:
            tracker(payee).add(Txn(ts, float(r.amount), "in", r.from_upi, from_sms=True))
        if payer is not None and warm:
            tracker(payer).add(Txn(ts, float(r.amount), "out", r.to_upi.lower()))
        elif payer is not None:
            tr = tracker(payer)
            s = tr.summary(ts, payee=r.to_upi)
            steps = s["escalation_steps"]
            if s["last_out_inr"]:
                steps = steps + 1 if r.amount >= rules["escalation_factor"] * s["last_out_inr"] else 0
            rows.append({
                "tx_id": r.tx_id, "user_id": payer,
                "episode_state": STATE_CODE[s["state"]],
                "episode_age_days": s["age_days"],
                "episode_bait_credits": s["bait_credits"],
                "episode_new_payees": s["new_payees"],
                "episode_out_to_in": s["out_to_in_ratio"],
                "episode_escalation_steps": steps,
                "episode_payee_seen": s["payee_seen_in_episode"],
            })
            tr.add(Txn(ts, float(r.amount), "out", r.to_upi.lower()))
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=Path("data"))
    a = p.parse_args()
    ledger = pd.read_parquet(a.data / "ledger.parquet")
    users = pd.read_parquet(a.data / "users.parquet")
    out = rebuild(ledger, users)
    out.to_parquet(a.data / "episode_features.parquet", index=False)
    by_state = out.episode_state.value_counts().sort_index().to_dict()
    print(f"{len(out):,} payments; episode state at payment time {by_state} (0 none, 1 watching, 2 active)")


if __name__ == "__main__":
    main()
