"""The playbook database. *Known* playbooks are the engine's own list, data/playbooks/playbooks.yaml
(read through blue_team/engine_file.py, so there is no second copy to drift); known/*.yaml only add
the story the agents read (summary, steps, advice). review/ holds drafts waiting for two analysts,
approved/ the ones they accepted, rejected/ the rest. One YAML file per playbook.

`name_scam(features)` is what the engine would call after its own matcher found nothing: the first
matching rule by priority. Approved playbooks have priority >= APPROVED_MIN_PRIORITY, so a new
playbook never takes a payment away from a known one; the exception is a fix for a *misnamed*
group (`misnamed_as`), which two analysts approved to run just before the playbook it corrects
(`priority_before`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from blue_team import config, matcher

APPROVED_MIN_PRIORITY = 100
STATES = ("known", "review", "approved", "rejected")


@dataclass
class Playbook:
    name: str
    status: str
    card: dict
    rules: list[tuple[int, dict]] = field(default_factory=list)   # (priority, matcher)
    path: Path | None = None

    @property
    def title(self) -> str:
        return self.card.get("title", self.name)


def _load_dir(state: str, root: Path) -> list[Playbook]:
    out = []
    for p in sorted((root / state).glob("*.yaml")):
        card = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        rules = [(int(m["priority"]), m["rule"]) for m in card.get("match", [])]
        out.append(Playbook(card["name"], state, card, rules, p))
    return out


def _load_known(root: Path) -> list[Playbook]:
    """The engine's playbooks (rules from its file) with the blue team's description cards."""
    from blue_team import engine_file
    cards = {pb.name: pb.card for pb in _load_dir("known", root)}
    by_name: dict[str, Playbook] = {}
    for name, prio, rule, why in engine_file.known():
        card = cards.get(name, {"name": name, "title": why})
        pb = by_name.setdefault(name, Playbook(name, "known", {**card, "engine_why": []}, [], engine_file.engine_path()))
        pb.card["engine_why"].append(why)
        pb.rules.append((prio, rule))
    return list(by_name.values())


def load(states: tuple[str, ...] = ("known", "approved"), root: Path | None = None) -> list[Playbook]:
    root = root or config.PLAYBOOKS
    return [pb for s in states for pb in (_load_known(root) if s == "known" else _load_dir(s, root))]


def ordered_rules(pbs: list[Playbook]) -> list[tuple[int, str, dict]]:
    return sorted(((prio, pb.name, rule) for pb in pbs for prio, rule in pb.rules), key=lambda r: (r[0], r[1]))


def name_scam(f: dict, pbs: list[Playbook] | None = None) -> str | None:
    """The first playbook (by priority) whose rule matches this payment, or None."""
    for _, name, rule in ordered_rules(pbs if pbs is not None else load()):
        if matcher.matches(rule, f):
            return name
    return None


def priority_before(name: str, root: Path | None = None) -> int:
    """A free priority just below the first rule of playbook `name`."""
    pbs = load(("known", "approved"), root)
    taken = {p for pb in pbs for p, _ in pb.rules}
    first = min((p for pb in pbs if pb.name == name for p, _ in pb.rules), default=APPROVED_MIN_PRIORITY)
    p = first - 1
    while p in taken and p > 1:
        p -= 1
    return p


def write(card: dict, state: str, root: Path | None = None) -> Path:
    assert state in STATES, state
    d = (root or config.PLAYBOOKS) / state
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{card['name']}.yaml"
    path.write_text(yaml.safe_dump(card, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
    return path


def summaries(pbs: list[Playbook]) -> list[dict]:
    """What the agents see of the database: names, titles, summaries, steps and matchers in words."""
    return [{"name": pb.name, "status": pb.status, "title": pb.title, "summary": pb.card.get("summary", "").strip(),
             "steps": pb.card.get("steps", []),
             "matchers": [matcher.describe(r) for _, r in pb.rules]} for pb in pbs]
