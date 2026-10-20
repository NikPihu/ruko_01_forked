"""Build the synthetic UPI world and write it as Parquet.

    PYTHONPATH=backend:ml:data python -m sim.generate --users 2000 --days 30 --seed 7 --out data/

Output tables (one Parquet file each):
    handles         handle -> bank, app, partner flag (the NPCI routing table)
    accounts        every account behind a UPI ID, with ground-truth mule labels
    users           app users (payers); age_band/language are audit-only, never model inputs
    ledger          every UPI payment, labelled scam / normal / mule flows
    context_events  phone-side signals: calls, installs, lures (derived flags only)
    journeys        one row per scam journey (ground truth)
    reports         victim, bystander and false reports; filed_at/listed_at may fall after
                    the window end -- the mock services decide visibility with their clock
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .accounts import build_accounts
from .config import HANDLES, SimConfig
from .extras import build_hard_negatives
from .mules import build_external_victims, build_mule_forwarding, build_mule_grooming
from .normal_life import build_normal_life
from .reports import build_reports
from .scams import build_scams
from .world import World

USER_COLS = ["user_id", "account_id", "upi_id", "mobile", "region", "age_band", "language", "sms_consent"]


def build_world(cfg: SimConfig) -> dict[str, pd.DataFrame]:
    w = World(cfg=cfg, rng=random.Random(cfg.seed), aux=random.Random(cfg.seed + 1000))
    build_accounts(w)
    build_normal_life(w)
    build_mule_grooming(w)
    build_scams(w)
    build_external_victims(w)
    build_mule_forwarding(w)
    build_reports(w)
    build_hard_negatives(w)

    ledger = pd.DataFrame(w.ledger).sort_values("ts", kind="stable").reset_index(drop=True)
    ledger.insert(0, "tx_id", [f"t_{i:07d}" for i in range(len(ledger))])
    events = pd.DataFrame(w.context_events).sort_values("ts", kind="stable").reset_index(drop=True)
    accounts = pd.DataFrame(w.accounts).drop(columns=["_active_from"]).sort_values("account_id")
    return {
        "handles": pd.DataFrame([asdict(h) for h in HANDLES]),
        "accounts": accounts.reset_index(drop=True),
        "users": pd.DataFrame(w.users)[USER_COLS],
        "ledger": ledger,
        "context_events": events,
        "journeys": pd.DataFrame(w.journeys),
        "reports": pd.DataFrame(w.reports, columns=[
            "report_id", "identifier_type", "identifier", "journey_id", "filed_at",
            "listed_at", "source", "is_false"]),
    }


def write_world(tables: dict[str, pd.DataFrame], cfg: SimConfig, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", engine="pyarrow", compression="snappy", index=False)
    manifest = {"config": {**asdict(cfg), "end": cfg.end.isoformat()},
                "rows": {k: len(v) for k, v in tables.items()}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))


def summary(t: dict[str, pd.DataFrame]) -> str:
    led, acc, j, rep = t["ledger"], t["accounts"], t["journeys"], t["reports"]
    scam = led[led.label_is_scam]
    listed = set(rep.loc[rep.identifier_type == "upi_id", "identifier"])
    mules = acc[acc.is_mule & (acc.mule_kind != "cash_out")]
    lines = [
        f"accounts {len(acc):,} (mules {int(acc.is_mule.sum())}, merchants {int((acc.holder_type == 'merchant').sum())})",
        f"ledger {len(led):,} payments, ₹{led.amount.sum():,.0f} total",
        f"scam journeys {len(j)} ({int(j.reported.sum())} reported), "
        f"{len(scam)} scam payments, ₹{scam.amount.sum():,.0f} lost",
        f"playbooks: {j.playbook.value_counts().to_dict()}",
        f"context events {len(t['context_events']):,}",
        f"reports {len(rep)} rows ({int(rep.is_false.sum())} false); "
        f"first-layer mules never reported: {len(set(mules.upi_id) - listed)} of {len(mules)}",
    ]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--users", type=int, default=2000)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--scam-rate", type=float, default=0.01)
    p.add_argument("--out", type=Path, default=Path("data"))
    a = p.parse_args()
    cfg = SimConfig(seed=a.seed, n_users=a.users, n_days=a.days, scam_rate=a.scam_rate)
    tables = build_world(cfg)
    write_world(tables, cfg, a.out)
    print(summary(tables))
    print(f"written to {a.out.resolve()}")


if __name__ == "__main__":
    main()
