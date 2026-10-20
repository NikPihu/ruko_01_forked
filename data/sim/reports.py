"""Reports are the only way list systems (FRI, Suspect Registry) learn anything.

They are built from what victims and bystanders *report*, with lag and noise, never from the
ground-truth mule labels. This keeps the mocks as blind as the real systems.
"""
from __future__ import annotations

from datetime import timedelta

from .accounts import DEMO_KIRANA_UPI, DEMO_MEENA, DEMO_MULE_UPI
from .world import World


def _row(w: World, rid: str, id_type: str, ident: str, filed, source: str,
         journey_id: str | None, is_false: bool) -> dict:
    listed = filed + timedelta(days=w.rng.uniform(*w.cfg.listing_lag_days))
    return {"report_id": rid, "identifier_type": id_type, "identifier": ident,
            "journey_id": journey_id, "filed_at": filed, "listed_at": listed,
            "source": source, "is_false": is_false}


def build_reports(w: World) -> None:
    cfg, rng = w.cfg, w.rng
    n = 0

    def next_id() -> str:
        nonlocal n
        n += 1
        return f"rep_{n:06d}"

    for j in w.journeys:
        if j["n_payments"] == 0 or j["is_demo"]:
            continue  # demo journeys stay unreported: the fresh-mule gap RUKO must cover
        # Bystander reports on Chakshu: other people the same campaign called.
        if j["caller_number"] and rng.random() < cfg.chakshu_report_rate:
            filed = j["started_at"] + timedelta(days=rng.uniform(0, 2))
            w.reports.append(_row(w, next_id(), "mobile", j["caller_number"], filed, "chakshu", None, False))
        if rng.random() >= cfg.report_rate:
            continue
        j["reported"] = True
        filed = j["last_payment_at"] + timedelta(days=rng.uniform(*cfg.report_lag_days))
        rid = next_id()
        source = rng.choice(("1930", "ncrp"))
        for mule in j["mule_upi_ids"].split(","):
            w.reports.append(_row(w, rid, "upi_id", mule, filed, source, j["journey_id"], False))
        if j["caller_number"]:
            w.reports.append(_row(w, rid, "mobile", j["caller_number"], filed, source, j["journey_id"], False))

    # Outside victims report too. Older mules pile up reports; fresh ones are not listed yet.
    for row in w.external_scam_rows:
        if row["to_upi"] == DEMO_MULE_UPI or rng.random() >= cfg.report_rate:
            continue
        filed = row["ts"] + timedelta(days=rng.uniform(*cfg.report_lag_days))
        rid, source = next_id(), rng.choice(("1930", "ncrp"))
        w.reports.append(_row(w, rid, "upi_id", row["to_upi"], filed, source, None, False))
        if rng.random() < 0.5:
            w.reports.append(_row(w, rid, "mobile", rng.choice(w.scam_numbers), filed, source, None, False))

    # False or malicious reports against honest accounts (never the demo actors).
    protected = {DEMO_KIRANA_UPI, w.users_by_id[DEMO_MEENA]["upi_id"]}
    honest = [a for a in w.accounts if not a["is_mule"] and a["upi_id"] not in protected]
    for acct in rng.sample(honest, k=round(len(honest) * cfg.false_entry_share)):
        filed = cfg.start + timedelta(minutes=rng.uniform(0, cfg.n_days * 1440))
        w.reports.append(_row(w, next_id(), "upi_id", acct["upi_id"], filed, "ncrp", None, True))
