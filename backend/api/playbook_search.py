"""Playbook search (plan v3, step 3): which known scam does this payment's journey look like, and how
much, from the steps it showed (contracts/steps.json, features/steps.py).

The playbooks file (data/playbooks/playbooks.yaml, `search:` section, playbooks-0.3) writes each scam
as weighted steps:

    search:
      - name: digital_arrest
        title: "A fake officer on a call; the victim pays under threat"
        steps:
          - {any: [unknown_call, lure:arrest_threat], weight: 2, required: true}
          - {any: [remote_control, video_call, dictated_amount, lure:arrest_threat], weight: 2, required: true}
          - {step: long_call, weight: 1}
        approved_by: [...]          # blue-team playbooks (two analysts)

An item is one step, or `any` of several (seen if one is seen, not seen if all were measured and none
seen, else unknown). The score of a playbook:

- every required item must be seen. Measured and not seen -> 0, `blocked_by` names it (the scam needs
  it); not measured -> 0 too, listed in `unmeasured`: an unknown is no evidence either way (CLAUDE.md
  rule 1), and counting it would match every QR payment from a phone that shares no call to refund_qr;
- then similarity = seen weight / (measured weight + UNMEASURED_SHARE x unmeasured optional weight):
  an unknown optional step counts half against the playbook, neither proof nor absence;
- every weight is multiplied by the step's IDF over the playbooks (log(1 + N / df)), so a step most
  scams share (new payee) tells less than one only a few have (video call).

Deterministic, no network, well under a millisecond per payment. `search()` returns the top playbooks
with their matched, missing and unmeasured steps, which is the explanation the analyst sees.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from features.steps import STEP_IDS

PATH = Path(os.environ.get("RUKO_PLAYBOOKS", Path(__file__).resolve().parents[2] / "data" / "playbooks" / "playbooks.yaml"))
UNMEASURED_SHARE = 0.5
TOP = 3


class SearchError(ValueError):
    pass


@dataclass
class Item:
    steps: tuple[str, ...]          # one step, or the options of an `any`
    weight: float
    required: bool
    idf: float = 1.0

    @property
    def label(self) -> str:
        return self.steps[0] if len(self.steps) == 1 else "any(" + ", ".join(self.steps) + ")"

    def reading(self, seen: dict[str, bool | None]) -> bool | None:
        vals = [seen.get(s) for s in self.steps]
        if True in vals:
            return True
        return False if vals and all(v is False for v in vals) else None


@dataclass
class Playbook:
    name: str
    title: str
    items: list[Item] = field(default_factory=list)
    approved_by: list[str] = field(default_factory=list)


def parse(doc: dict) -> list[Playbook]:
    """The `search:` section of a playbooks file. Raises SearchError on anything it does not understand."""
    out = []
    for i, p in enumerate((doc or {}).get("search") or []):
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not p.get("steps"):
            raise SearchError(f"search playbook {i}: needs a name and steps")
        unknown = set(p) - {"name", "title", "steps", "approved_by"}
        if unknown:
            raise SearchError(f"search playbook {p['name']}: unknown keys {sorted(unknown)}")
        items = []
        for it in p["steps"]:
            steps = tuple(it["any"]) if "any" in it else (it.get("step"),)
            bad = [s for s in steps if s not in STEP_IDS]
            if bad or not steps:
                raise SearchError(f"search playbook {p['name']}: unknown steps {bad} (contracts/steps.json)")
            w = float(it.get("weight", 1))
            if w <= 0:
                raise SearchError(f"search playbook {p['name']}: weights must be positive")
            items.append(Item(steps, w, bool(it.get("required", False))))
        if not any(it.required for it in items):
            raise SearchError(f"search playbook {p['name']}: at least one step must be required")
        out.append(Playbook(p["name"], " ".join(str(p.get("title", p["name"])).split()), items, list(p.get("approved_by") or [])))
    _idf(out)
    return out


def _idf(pbs: list[Playbook]) -> None:
    n = len(pbs) or 1
    df: dict[str, int] = {}
    for pb in pbs:
        for s in {s for it in pb.items for s in it.steps}:
            df[s] = df.get(s, 0) + 1
    for pb in pbs:
        for it in pb.items:
            it.idf = sum(math.log(1 + n / df[s]) for s in it.steps) / len(it.steps)


def load(path: Path = PATH) -> tuple[list[Playbook], str]:
    """(playbooks, source). A missing or broken search section turns the search off, never the engine."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        pbs = parse(doc)
        return pbs, f"file:{doc.get('version', '?')}" if pbs else "none"
    except (FileNotFoundError, OSError, yaml.YAMLError, SearchError, KeyError, TypeError):
        return [], "none"


def score(pb: Playbook, seen: dict[str, bool | None]) -> dict:
    matched, missing, unmeasured = [], [], []
    got = measured = unknown_w = 0.0
    complete = True
    for it in pb.items:
        w = it.weight * it.idf
        r = it.reading(seen)
        if r is True:
            matched.append(it.label)
            got += w
            measured += w
        elif r is False:
            missing.append(it.label)
            measured += w
            if it.required:
                return {"name": pb.name, "similarity": 0.0, "matched": matched, "missing": missing,
                        "unmeasured": unmeasured, "blocked_by": it.label}
        else:
            unmeasured.append(it.label)
            unknown_w += w
            complete &= not it.required
    sim = 0.0 if not complete else got / (measured + UNMEASURED_SHARE * unknown_w)
    return {"name": pb.name, "similarity": round(sim, 4), "matched": matched, "missing": missing,
            "unmeasured": unmeasured, "blocked_by": None}


def search(seen: dict[str, bool | None], pbs: list[Playbook], top: int = TOP) -> list[dict]:
    """The best `top` playbooks with a similarity above 0, best first (ties by name)."""
    scored = [score(pb, seen) for pb in pbs]
    return sorted((s for s in scored if s["similarity"] > 0), key=lambda s: (-s["similarity"], s["name"]))[:top]


PLAYBOOKS, SOURCE = load()
