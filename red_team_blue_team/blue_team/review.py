"""Step 5: humans in the loop. Two different analysts approve a queued playbook before it counts.

    python -m blue_team queue                                  # what is waiting
    python -m blue_team show relative_voice_clone              # the card, backtest, analyst verdict
    python -m blue_team approve relative_voice_clone --analyst asha --note "matches 1930 cases"
    python -m blue_team reject  relative_voice_clone --analyst ravi --note "same as digital_arrest"

A rejection by anyone moves the card to playbooks/rejected/. With `approvals_needed` approvals from
different analysts, no rejection and no failing gate, the card moves to playbooks/approved/ and its
exports are written: the entry for the engine's data/playbooks/playbooks.yaml (where it goes, and
anything its format cannot express yet), mule accounts for the graph suspect review
(graph/discover.py, again two analysts) and the labelled payments for the next model retrain. Approval never changes a tier
directly: an approved playbook names the scam and its warning (CLAUDE.md rules 11 and 13).
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import yaml

from blue_team import config, playbook_db

EXPORTS = config.HERE / "exports"


class ReviewError(ValueError):
    pass


def _path(name: str, state: str, root: Path | None) -> Path:
    return (root or config.PLAYBOOKS) / state / f"{name}.yaml"


def load_card(name: str, root: Path | None = None) -> tuple[dict, str]:
    for state in ("review", "approved", "rejected", "known"):
        p = _path(name, state, root)
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8")), state
    raise ReviewError(f"no playbook {name!r}")


def queue(root: Path | None = None) -> list[dict]:
    out = []
    for p in sorted(((root or config.PLAYBOOKS) / "review").glob("*.yaml")):
        c = yaml.safe_load(p.read_text(encoding="utf-8"))
        approvals = sorted({r["analyst"] for r in c.get("reviews", []) if r["decision"] == "approve"})
        out.append({"name": c["name"], "title": c["title"], "cases": c["evidence"]["cases"],
                    "analyst_agent": (c.get("analyst") or {}).get("verdict"), "gates": "pass" if not c.get("gate_failures") else "FAIL",
                    "approvals": approvals})
    return out


def decide(name: str, analyst: str, decision: str, note: str = "", root: Path | None = None,
           exports: Path | None = None) -> dict:
    """Record one analyst's decision; promote or reject the card when the rule says so."""
    if decision not in ("approve", "reject"):
        raise ReviewError("decision must be approve or reject")
    analyst = analyst.strip().lower()
    if not analyst:
        raise ReviewError("an analyst name is required")
    card, state = load_card(name, root)
    if state != "review":
        raise ReviewError(f"{name} is {state}, not waiting for review")
    if decision == "reject" and not note.strip():
        raise ReviewError("a rejection needs a note saying why")
    if any(r["analyst"] == analyst for r in card["reviews"]):
        raise ReviewError(f"{analyst} already reviewed {name}")
    if decision == "approve" and card.get("gate_failures"):
        raise ReviewError(f"{name} fails the gates ({'; '.join(card['gate_failures'])}); edit its matcher and run "
                          "`python -m blue_team retest` first")
    card["reviews"].append({"analyst": analyst, "decision": decision, "note": note.strip(),
                            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    src = _path(name, "review", root)
    if decision == "reject":
        card["status"] = "rejected"
        playbook_db.write(card, "rejected", root)
        src.unlink()
        return {"name": name, "status": "rejected"}
    approvals = {r["analyst"] for r in card["reviews"] if r["decision"] == "approve"}
    need = config.load()["review"]["approvals_needed"]
    if len(approvals) < need:
        playbook_db.write(card, "review", root)
        return {"name": name, "status": "review", "approvals": sorted(approvals), "needed": need}
    return promote(card, root, exports)


def promote(card: dict, root: Path | None = None, exports: Path | None = None) -> dict:
    approved = playbook_db.load(("approved",), root)
    if card.get("misnamed_as"):     # a fix for a misnamed group runs just before the playbook it corrects
        prio = playbook_db.priority_before(card["misnamed_as"], root)
    else:
        prio = playbook_db.APPROVED_MIN_PRIORITY + 10 * len(approved)
    card["status"] = "approved"
    card["match"] = [{"priority": prio, "rule": m["rule"]} for m in card["match"]]
    card["approved_by"] = sorted({r["analyst"] for r in card["reviews"] if r["decision"] == "approve"})
    card["approved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = playbook_db.write(card, "approved", root)
    _path(card["name"], "review", root).unlink()
    d = (exports or EXPORTS) / card["name"]
    d.mkdir(parents=True, exist_ok=True)
    from blue_team import engine_file
    entry, problems = engine_file.export_entry(card)
    (d / "playbooks_entry.yaml").write_text(entry, encoding="utf-8")
    with open(d / "mule_accounts.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["upi_id", "complaints", "playbook"])
        for m in card.get("mule_accounts", []):
            w.writerow([m["upi_id"], m["cases"], card["name"]])
    with open(d / "labels.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tx_id", "playbook", "label_is_scam", "source"])
        for tx in card.get("label_tx_ids", []):
            w.writerow([tx, card["name"], True, "complaint+2_analysts"])
    return {"name": card["name"], "status": "approved", "priority": prio, "path": str(path), "exports": str(d),
            "engine_entry": "ready to paste" if not problems else f"needs the file format extended: {problems}"}
