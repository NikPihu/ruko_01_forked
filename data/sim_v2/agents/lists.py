"""Reports and the lists built from them (I4C registry, DoT FRI read these rows with their lags).

Lists only ever learn from *reports*: victims, outside victims, bystanders (Chakshu) and false
reports. Never from the ground-truth mule labels, so the mocks stay as blind as the real systems.
"""
from __future__ import annotations

from datetime import timedelta

from sim_v2 import rails
from sim_v2.world import World


def _report(w: World, r, key: str, rows: list[tuple], filed, source: str, journey_id, is_false=False) -> None:
    lo, hi = w.cfg.get("reports.listing_lag_days")
    listed = filed + timedelta(days=r.uniform(lo, hi))
    w.reports.append({"key": key, "rows": rows, "filed_at": filed, "listed_at": listed, "source": source,
                      "journey_id": journey_id, "is_false": is_false})


def journey_reports(w: World, j: dict) -> None:
    """The victim may report after the journey ends (a logged decision); bystanders report the caller."""
    cfg, a = w.cfg, w.cfg.a["victim"]
    if j["is_demo"]:
        return   # demo journeys stay unreported: the fresh-mule gap RUKO must cover
    r = w.r("report", j["journey_id"])
    if j["caller_number"] and r.chance(cfg.get("reports.chakshu_rate")):
        _report(w, r, f"chakshu:{j['journey_id']}", [("mobile", j["caller_number"])],
                j["started_at"] + timedelta(days=r.uniform(0, 2)), "chakshu", None)
    if j["complied_steps"] == 0:   # hung up / ignored the first approach: nothing to report
        return
    p = a["report_if_paid"] if j["n_payments"] else a["report_if_not_paid"]
    out = rails.decide(w, r, decision_id=f"D_{j['journey_id']}_report", ts=j["last_activity"], agent=j["user_id"],
                       kind="report", journey_id=j["journey_id"], step="report", p=p,
                       inputs={"paid_inr": j["total_paid"], "p_report": p})
    if out != "yes":
        return
    j["reported"] = True
    lo, hi = cfg.get("reports.report_lag_days")
    filed = j["last_activity"] + timedelta(days=r.uniform(lo, hi))
    ids = [("upi_id", m) for m in j["mule_upi_ids"].split(",") if m]
    if j["caller_number"]:
        ids.append(("mobile", j["caller_number"]))
    if ids:
        _report(w, r, f"victim:{j['journey_id']}", ids, filed, r.choice(("1930", "ncrp")), j["journey_id"])


def other_reports(w: World) -> None:
    cfg = w.cfg
    demo_mule = cfg.demo["demo_mule"]["upi_id"]
    lo, hi = cfg.get("reports.report_lag_days")
    for t, mule, crew in w.external_reports:
        r = w.r("ext_report", mule, t.isoformat())
        if mule == demo_mule or not r.chance(cfg.get("reports.external_report_rate")):
            continue
        rows = [("upi_id", mule)] + ([("mobile", r.choice(crew.numbers)[0])] if r.chance(0.5) else [])
        _report(w, r, f"ext:{mule}:{t.isoformat()}", rows, t + timedelta(days=r.uniform(lo, hi)), r.choice(("1930", "ncrp")), None)
    protected = {cfg.demo["kirana"]["upi_id"], cfg.demo["meena"]["upi_id"], demo_mule}
    for upi, acct in w.accounts.items():
        if acct["is_mule"] or upi in protected:
            continue
        r = w.r("false_report", upi)
        if r.chance(cfg.get("reports.false_report_share")):
            filed = w.start + timedelta(days=r.uniform(0, cfg.days))
            _report(w, r, f"false:{upi}", [("upi_id", upi)], filed, "ncrp", None, is_false=True)


def report_rows(w: World) -> list[dict]:
    """Flatten to the data/sim reports table: one row per identifier, report ids in filing order."""
    out = []
    for n, rep in enumerate(sorted(w.reports, key=lambda x: (x["filed_at"], x["key"])), start=1):
        for id_type, ident in rep["rows"]:
            out.append({"report_id": f"rep_{n:06d}", "identifier_type": id_type, "identifier": ident,
                        "journey_id": rep["journey_id"], "filed_at": rep["filed_at"], "listed_at": rep["listed_at"],
                        "source": rep["source"], "is_false": rep["is_false"]})
    return out
