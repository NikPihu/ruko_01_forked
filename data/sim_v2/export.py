"""Assemble and write the tables. The 7 data/sim tables keep their columns and order (the contract
read by backend/ and ml/); sim_v2 adds columns at the end and two extra tables (decisions, crews)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from sim_v2.agents.lists import report_rows
from sim_v2.agents.session import sessions
from sim_v2.core.tables import SCHEMAS
from sim_v2.world import HANDLES, World, hash_key

USER_COLS = ["user_id", "account_id", "upi_id", "mobile", "region", "age_band", "language", "sms_consent",
             # sim_v2 extras
             "persona", "income_month", "savings_months", "call_consent", "app_consent", "locality"]
ACCOUNT_COLS = ["account_id", "upi_id", "mobile", "handle", "bank", "partner_bank", "holder_name", "holder_type",
                "merchant_kind", "mcc", "verified", "created_at", "kyc_at", "region", "is_mule", "mule_kind"]
JOURNEY_COLS = ["journey_id", "user_id", "playbook", "started_at", "last_payment_at", "caller_number", "mule_upi_ids",
                "n_payments", "total_paid", "is_demo", "reported", "variant", "outcome", "crew_id", "complied_steps"]
REPORT_COLS = ["report_id", "identifier_type", "identifier", "journey_id", "filed_at", "listed_at", "source", "is_false"]
TABLES = ["handles", "accounts", "users", "ledger", "context_events", "journeys", "reports", "decisions", "crews"]


def _sort(t: pa.Table, keys: list[str]) -> pa.Table:
    return t.take(pc.sort_indices(t, sort_keys=[(k, "ascending") for k in keys]))


def assemble(w: World) -> dict[str, pd.DataFrame]:
    ledger = _sort(w.ledger.table(), ["ts", "from_upi", "to_upi", "amount"])
    users_by_upi = {u["upi_id"]: u for u in w.users}
    playbook_of = {j["journey_id"]: j["playbook"] for j in w.journeys}
    hospitals = {h for loc in w.localities.values() for h in loc["hospital"]}
    mine = ledger.filter(pc.is_in(ledger["from_upi"], value_set=pa.array(list(users_by_upi))))
    for row in sessions(w, mine.to_pylist(), users_by_upi, playbook_of, hospitals):
        w.events.add(*row)
    events = _sort(w.events.table(), ["ts", "user_id", "event_type"]).to_pandas()
    led = ledger.to_pandas()
    led.insert(0, "tx_id", [f"t_{i:07d}" for i in range(len(led))])

    acc = pd.DataFrame(w.accounts.values())
    acc = acc.assign(_k=acc.upi_id.map(lambda u: hash_key((w.seed, "account_id", u)))).sort_values("_k")
    acc["account_id"] = [f"a_{i:06d}" for i in range(len(acc))]
    acc = acc.drop(columns="_k").sort_values("account_id")[ACCOUNT_COLS].reset_index(drop=True)
    aid = dict(zip(acc.upi_id, acc.account_id))
    users = pd.DataFrame([{**u, "account_id": aid[u["upi_id"]]} for u in w.users])[USER_COLS]
    journeys = pd.DataFrame(w.journeys, columns=JOURNEY_COLS + ["last_activity"])[JOURNEY_COLS]
    reports = pd.DataFrame(report_rows(w), columns=REPORT_COLS)
    handles = pd.DataFrame([{"handle": h, "bank": v[0], "app": v[1], "partner": v[2]} for h, v in HANDLES.items()])
    crews = pd.DataFrame([{"crew_id": c.crew_id, "playbook": c.playbook, "group": c.group, "region": c.region,
                           "slot": s, "mule_upi_id": upi, "mule_kind": kind, "active_from": a, "active_to": b}
                          for c in w.crews.values() for s, sched in enumerate(c.slots) for a, b, upi, kind in sched])
    decisions = _sort(w.decisions.table(), ["ts", "decision_id"]).to_pandas()
    return {"handles": handles, "accounts": acc, "users": users, "ledger": led, "context_events": events,
            "journeys": journeys, "reports": reports, "decisions": decisions, "crews": crews}


def write(tables: dict[str, pd.DataFrame], cfg, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        schema = None
        if name in SCHEMAS and name != "decisions":
            schema = pa.schema([pa.field("tx_id", pa.string())] + list(SCHEMAS[name])) if name == "ledger" else SCHEMAS[name]
        pq.write_table(pa.Table.from_pandas(df, schema=schema, preserve_index=False), out / f"{name}.parquet")
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = None
    # data/sim's keys too (n_users, n_days, seed, end), which backend/intel_mock and ml/dataset read
    compat = {"seed": cfg.seed, "n_users": cfg.users, "n_days": cfg.days, "scam_rate": cfg.victim_rate}
    manifest = {"generator": "sim_v2", "config": {**cfg.raw_world, **compat, "end": cfg.end.isoformat()},
                "config_fingerprint": cfg.fingerprint(), "git_commit": commit,
                "rows": {k: len(v) for k, v in tables.items()}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
