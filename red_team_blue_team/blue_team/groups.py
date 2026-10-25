"""Scam groups for the console: the red team's attacks per kind of scam, never one grand total.

A group is a scam type. Each red-team playbook joins one (docs/design/red-blue-console/README.md):

1. its blue-team cluster (the group of complaints it has most of, from a run's scorecard) drafted a
   playbook the analyst agent judged a **new scam** -> a new group, named after that playbook;
2. otherwise that cluster's closest known playbook (a known scam that slipped past, or a variant);
3. no cluster yet (no complaints, or too few to group): the known scam its main lure points to,
   marked "not grouped yet"; no lure at all -> "Not grouped yet".

The scorecard behind step 1-2 uses the simulator's answer key (which journey ran which playbook):
grading only, never read by the pipeline (CLAUDE.md rule 9). The runner's numbers (got through,
called normal) come from the attack runner's own verdicts, one small world per playbook.
"""
from __future__ import annotations

from collections import Counter

LURE_TO_KNOWN = {"arrest_threat": "digital_arrest", "kyc": "fake_kyc_apk", "task_job": "task_job",
                 "trading_tip": "trading_group", "refund": "refund_qr"}
UNGROUPED = "not_grouped"


def main_lure(script: dict) -> str | None:
    tags = Counter(e["tag"] for s in script.get("steps", []) for e in s.get("events", [])
                   if e.get("type") in ("sms_lure", "notification_lure") and e.get("tag"))
    return tags.most_common(1)[0][0] if tags else None


def place(name: str, script: dict, score_row: dict | None, clusters: dict[str, dict]) -> tuple[str, str, str | None]:
    """(group key, kind new|known, why) for one red-team playbook."""
    groups = sorted((score_row or {}).get("groups") or [], key=lambda g: -g["complaints"])
    if groups:
        g = groups[0]
        if g.get("verdict") == "new_scam" and g.get("playbook"):
            return g["playbook"], "new", f"most of its complaints are in {g['group']}, judged a new scam"
        near = (clusters.get(g["group"]) or {}).get("nearest_playbook")
        if near:
            return near, "known", f"most of its complaints are in {g['group']}, closest to {near}"
    lure = LURE_TO_KNOWN.get(main_lure(script) or "")
    if lure:
        return lure, "known", "not grouped yet: placed by its main lure"
    return UNGROUPED, "known", "not grouped yet and no lure"


def build(playbooks: list[dict], verdicts: dict[str, dict], scorecard: dict | None, clusters: list[dict],
          cards: dict[str, list[dict]], known_titles: dict[str, str]) -> list[dict]:
    """`playbooks`: redteam.load() rows (with "playbook", the script); `cards`: webapp /api/cards."""
    rows = {r["playbook"]: r for r in (scorecard or {}).get("rows", [])}
    by_cluster = {c["cluster_id"]: c for c in clusters}
    card_of = {c["name"]: c for state in ("review", "approved", "rejected") for c in cards.get(state, [])}
    out: dict[str, dict] = {}
    for pb in playbooks:
        key, kind, why = place(pb["name"], pb["playbook"], rows.get(pb["name"]), by_cluster)
        g = out.setdefault(key, {"group": key, "kind": kind, "members": [], "attacks": 0, "judged": 0, "got_through": 0,
                                 "scam_payments": 0, "called_normal": 0, "complaints": 0, "grouped": 0})
        v, r = verdicts.get(pb["name"]), rows.get(pb["name"]) or {}
        g["attacks"] += 1
        g["complaints"] += int(r.get("complaints") or 0)
        g["grouped"] += bool(r.get("groups"))
        if v:
            g["judged"] += 1
            g["got_through"] += bool(v["breakthrough"])
            g["scam_payments"] += int(v["scam_payments_judged"])
            g["called_normal"] += int(v["scam_called_normal"])
        g["members"].append({"playbook": pb["name"], "title": pb.get("title"), "techniques": pb.get("techniques", []),
                             "why": why, "judged": bool(v),
                             "called_normal": v["miss_rate"] if v else None,
                             "scam_payments": v["scam_payments_judged"] if v else None,
                             "breakthrough": v["breakthrough"] if v else None,
                             "complaints": int(r.get("complaints") or 0)})
    for key, g in out.items():
        g["called_normal_share"] = round(g["called_normal"] / g["scam_payments"], 3) if g["scam_payments"] else None
        g["members"].sort(key=lambda m: -(m["called_normal"] or 0))
        if g["kind"] == "new":
            c = card_of.get(key) or {}
            g["title"] = c.get("title") or key
            g["playbook"], g["playbook_state"] = key, _card_state(c)
        elif key == UNGROUPED:
            g["title"], g["playbook"], g["playbook_state"] = "Not grouped yet", None, None
        else:
            g["title"] = known_titles.get(key, key.replace("_", " ").capitalize())
            g["playbook"], g["playbook_state"] = key, "built-in"
        g["status"] = ("not judged" if not g["judged"] else
                       "leaking" if g["got_through"] / g["judged"] >= 0.75 else
                       "partly caught" if g["got_through"] / g["judged"] >= 0.34 else "mostly caught")
    return sorted(out.values(), key=lambda g: (g["group"] == UNGROUPED, g["kind"] != "new", -(g["got_through"]), g["group"]))


def _card_state(c: dict) -> str | None:
    if not c:
        return None
    if c.get("state") in ("approved", "rejected"):
        return c["state"]
    return f"{len(c.get('approvals') or [])} of {c.get('needed', 2)}"
