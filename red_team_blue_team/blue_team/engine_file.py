"""The engine's playbook list (data/playbooks/playbooks.yaml, format in backend/api/playbooks.py) in
the blue team's matcher format, and back.

- `known()` reads the live file, so the blue team always judges against what the engine names
  today (no second copy to drift). Its entries become rules with priorities 10, 20, ... in file order.
- `export_entry(card)` turns an approved card into an entry for that file, with where it goes
  (before the playbook it corrects, or at the end) and what the file format cannot express yet.

The file format is a subset of ours: `feature: true` (set), `feature: false` (not set or unknown),
a value (equal), a list (one of), `any:` (one of several maps), and the derived `unknown_caller`.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from features.build import FAMILY

from blue_team import matcher, tokens

STEP = 10


def _is_true(f: str) -> dict:
    return {"feature": f, "op": "is", "value": True}


def to_rule(match: dict) -> dict:
    """One file `match:` map as a matcher (exact: same answer on every feature set)."""
    parts = []
    for key, want in match.items():
        if key == "any":
            parts.append({"any": [to_rule(m) for m in want]})
            continue
        leaf = tokens.UNKNOWN_CALLER if key == "unknown_caller" else _is_true(key)
        if want is True:
            parts.append(leaf)
        elif want is False:
            parts.append({"not": leaf})
        elif isinstance(want, list):
            parts.append({"feature": key, "op": "in", "value": want})
        else:
            parts.append({"feature": key, "op": "eq", "value": want})
    return parts[0] if len(parts) == 1 else {"all": parts}


def engine_path() -> Path:
    from api.playbooks import PATH
    return PATH


def known(path: Path | None = None) -> list[tuple[str, int, dict, str]]:
    """(name, priority, matcher, why) per entry of the engine's file, in its order.
    Fails loudly on a file the engine itself would refuse."""
    from api.playbooks import parse
    doc = yaml.safe_load((path or engine_path()).read_text(encoding="utf-8"))
    parse(doc)                                   # the engine's own validation
    return [(p["name"], STEP * (i + 1), to_rule(p["match"]), p["why"]) for i, p in enumerate(doc["playbooks"])]


# ---- back to the file format -------------------------------------------------------------------

def _leaf_map(node: dict, problems: list[str]) -> dict | None:
    if node == tokens.UNKNOWN_CALLER:
        return {"unknown_caller": True}
    if "not" in node and set(node) == {"not"}:
        inner = node["not"]
        if inner == tokens.UNKNOWN_CALLER:
            return {"unknown_caller": False}
        if inner.get("op") == "is" and inner.get("value") is True and inner.get("feature") in FAMILY:
            return {inner["feature"]: False}
        problems.append(f"NOT ({matcher.describe(inner)})")
        return None
    f, op, v = node.get("feature"), node.get("op"), node.get("value")
    if f not in FAMILY:
        problems.append(f"{matcher.describe(node)}: '{f}' is a request field, not an engine feature")
        return None
    if op == "is" and v is True:
        return {f: True}
    if op == "eq":
        return {f: v}
    if op == "in":
        return {f: list(v)}
    problems.append(f"{matcher.describe(node)}: the file format has no '{op}'"
                    + (" (it reads `false` as 'not set or unknown')" if op == "is" else ""))
    return None


def to_match(node: dict, problems: list[str]) -> dict | None:
    """A matcher as a file `match:` map, or None with the reasons in `problems`."""
    if node in (tokens.UNKNOWN_CALLER, {"not": tokens.UNKNOWN_CALLER}):   # the file's derived check
        return _leaf_map(node, problems)
    if "all" in node:
        out: dict = {}
        for child in node["all"]:
            m = to_match(child, problems)
            if m is None:
                continue
            for k, v in m.items():
                if k in out and out[k] != v:
                    problems.append(f"two conditions on '{k}' in one map")
                out[k] = v
        return out if not problems else None
    if "any" in node:
        opts = [to_match(c, problems) for c in node["any"]]
        return {"any": opts} if not problems else None
    return _leaf_map(node, problems)


def export_entry(card: dict) -> tuple[str, list[str]]:
    """(YAML for data/playbooks/playbooks.yaml, problems). Empty problems: paste it as it is."""
    rule = matcher.normalize(card["match"][0]["rule"])
    problems: list[str] = []
    m = to_match(rule, problems)
    where = (f"just BEFORE the first '{card['misnamed_as']}' entry (it corrects payments RUKO called "
             f"{card['misnamed_as']})" if card.get("misnamed_as") else "at the END of the list")
    why = " ".join(str(card.get("title", card["name"])).split())
    entry = {"name": card["name"], "why": why, "match": m if m is not None else {"TODO": "see problems above"}}
    head = [f"# Blue-team playbook '{card['name']}', approved by {', '.join(card.get('approved_by', []))}",
            f"# Put it {where}.",
            f"# App text: add '<tier>_{card['name']}' to AlertText.kt (advice_en / advice_hi are in the approved card)."]
    if problems:
        head.append("# NOT EXPRESSIBLE in playbooks-0.1 yet (needs the format extended, see blue_team/README.md):")
        head += [f"#   - {p}" for p in problems]
    return "\n".join(head) + "\n" + yaml.safe_dump([entry], sort_keys=False, allow_unicode=True), problems
