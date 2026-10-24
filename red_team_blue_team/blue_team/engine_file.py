"""The engine's playbook list (data/playbooks/playbooks.yaml, format in backend/api/playbooks.py) in
the blue team's matcher format, and back.

- `known()` reads the live file, so the blue team always judges against what the engine names
  today (no second copy to drift). Its entries become rules with priorities 10, 20, ... in file order.
- `export_entry(card)` turns an approved card into an entry for that file, with where it goes
  (before the playbook it corrects, or at the end) and what the file format cannot express yet.

The file format (playbooks-0.2) is a subset of ours: `feature: true` (set), `feature: false` (not set
or unknown), a value (equal), a list (one of), a comparison map (`{gte: 1000, lt: 10000}`), `any:`
(one of several maps), the derived `unknown_caller`, and the request fields `entry_method` /
`payer_says`. An approved entry carries `approved_by`, which makes policy raise its payments to a
warning (backend/api/policy.yaml approved_playbooks) when its conditions span two families.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from features.build import FAMILY

from blue_team import matcher, tokens

STEP = 10
OPS = {">=": "gte", ">": "gt", "<=": "lte", "<": "lt"}
OPS_BACK = {v: k for k, v in OPS.items()}
REQUEST_FIELDS = ("entry_method", "payer_says")


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
        if isinstance(want, dict):
            cmp = [{"feature": key, "op": OPS_BACK[op], "value": v} for op, v in want.items()]
            parts.extend(cmp)
            continue
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
    if f not in FAMILY and f not in REQUEST_FIELDS:
        problems.append(f"{matcher.describe(node)}: '{f}' is neither an engine feature nor a request field")
        return None
    if op == "is" and v is True:
        return {f: True}
    if op == "eq":
        return {f: v}
    if op == "in":
        return {f: list(v)}
    if op in OPS and isinstance(v, (int, float)) and not isinstance(v, bool):
        return {f: {OPS[op]: v}}
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
                if k in out and isinstance(out[k], dict) and isinstance(v, dict) and not set(out[k]) & set(v):
                    out[k] = {**out[k], **v}           # amount >= 1000 AND amount < 10000 -> one range
                    continue
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
    if card.get("approved_by"):
        entry["approved_by"] = list(card["approved_by"])
    head = [f"# Blue-team playbook '{card['name']}', approved by {', '.join(card.get('approved_by', []))}",
            f"# Put it {where}.",
            f"# App text: add '<tier>_{card['name']}' to AlertText.kt (advice_en / advice_hi are in the approved card)."]
    if m is not None and card.get("approved_by"):
        from api.playbooks import families
        fam = sorted(families(m))
        head.append(f"# Policy: its payments are raised to a warning (T2+), conditions span {'+'.join(fam)}." if len(fam) >= 2
                    else f"# Policy: it only NAMES the scam: its conditions are all family {''.join(fam) or '?'}, and "
                         "raising a payment needs two families (rule 5).")
    if problems:
        head.append("# NOT EXPRESSIBLE in playbooks-0.2 (see blue_team/README.md):")
        head += [f"#   - {p}" for p in problems]
    return "\n".join(head) + "\n" + yaml.safe_dump([entry], sort_keys=False, allow_unicode=True), problems
