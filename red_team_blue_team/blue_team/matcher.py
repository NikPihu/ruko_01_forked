"""Playbook matchers: a small, fixed rule format that an LLM may draft and only code evaluates.

A matcher is a tree of conditions over one payment's engine features (backend/features/build.py
FAMILY) plus two request fields (`entry_method`, `payer_says`):

    {"all": [{"feature": "on_call", "op": "is", "value": true},
             {"any": [{"feature": "payer_says", "op": "eq", "value": "family"},
                      {"feature": "amount_inr", "op": ">=", "value": 10000}]},
             {"not": {"feature": "payee_verified_merchant", "op": "is", "value": true}}]}

No code, no free text, no network: an LLM can only choose features, operators and values, so a
drafted playbook cannot run anything (CLAUDE.md rule 13). An unmeasured feature (None) never
satisfies a comparison; `is_null` asks for it explicitly. A matcher only names a scam; it never
sets a tier.
"""
from __future__ import annotations

from typing import Any

from features.build import FAMILY

REQUEST_FIELDS = {"entry_method", "payer_says"}
FIELDS = set(FAMILY) | REQUEST_FIELDS
OPS = {"is", "eq", "ne", "in", "not_in", ">=", "<=", ">", "<", "is_null", "not_null"}
MAX_DEPTH = 4
MAX_LEAVES = 12


def validate(node: Any) -> list[str]:
    """Problems with a matcher, in words; empty when it is valid."""
    errors: list[str] = []
    leaves = _check(node, 1, errors)
    if leaves > MAX_LEAVES:
        errors.append(f"too many conditions ({leaves}; at most {MAX_LEAVES})")
    if leaves == 0 and not errors:
        errors.append("a matcher needs at least one condition")
    return errors


def _check(node: Any, depth: int, errors: list[str]) -> int:
    if depth > MAX_DEPTH:
        errors.append(f"nested deeper than {MAX_DEPTH}")
        return 0
    if not isinstance(node, dict):
        errors.append(f"a condition must be an object, got {type(node).__name__}")
        return 0
    keys = set(node)
    if keys & {"all", "any"}:
        if len(keys) != 1:
            errors.append(f"'all'/'any' must be alone in their object, got {sorted(keys)}")
            return 0
        children = node.get("all", node.get("any"))
        if not isinstance(children, list) or not children:
            errors.append("'all'/'any' needs a non-empty list")
            return 0
        return sum(_check(c, depth + 1, errors) for c in children)
    if keys == {"not"}:
        return _check(node["not"], depth + 1, errors)
    if not {"feature", "op"} <= keys or keys - {"feature", "op", "value"}:
        errors.append(f"a leaf needs feature, op and value, got {sorted(keys)}")
        return 0
    feature, op, value = node["feature"], node["op"], node.get("value")
    if feature not in FIELDS:
        errors.append(f"unknown feature {feature!r}")
    if op not in OPS:
        errors.append(f"unknown op {op!r} (use one of {sorted(OPS)})")
    elif op == "is" and not isinstance(value, bool):
        errors.append(f"{feature}: 'is' needs true or false")
    elif op in {"in", "not_in"} and not isinstance(value, list):
        errors.append(f"{feature}: '{op}' needs a list")
    elif op in {">=", "<=", ">", "<"} and (isinstance(value, bool) or not isinstance(value, (int, float))):
        errors.append(f"{feature}: '{op}' needs a number")
    elif op in {"eq", "ne"} and isinstance(value, (list, dict)):
        errors.append(f"{feature}: '{op}' needs a single value")
    return 1


def matches(node: dict, f: dict) -> bool:
    """Whether one payment (engine features + request fields) satisfies the matcher."""
    if "all" in node:
        return all(matches(c, f) for c in node["all"])
    if "any" in node:
        return any(matches(c, f) for c in node["any"])
    if "not" in node:
        return not matches(node["not"], f)
    x, op, v = f.get(node["feature"]), node["op"], node.get("value")
    if op == "is_null":
        return x is None
    if op == "not_null":
        return x is not None
    if x is None:
        return False
    if op == "is":
        return bool(x) is v
    if op == "eq":
        return x == v
    if op == "ne":
        return x != v
    if op == "in":
        return x in v
    if op == "not_in":
        return x not in v
    x = float(x)
    return {">=": x >= v, "<=": x <= v, ">": x > v, "<": x < v}[op]


def features_used(node: dict) -> set[str]:
    if "all" in node or "any" in node:
        return set().union(*(features_used(c) for c in node.get("all", node.get("any"))))
    if "not" in node:
        return features_used(node["not"])
    return {node["feature"]}


def describe(node: dict) -> str:
    """The matcher in one readable line, for analysts."""
    if "all" in node:
        return "(" + " AND ".join(describe(c) for c in node["all"]) + ")"
    if "any" in node:
        return "(" + " OR ".join(describe(c) for c in node["any"]) + ")"
    if "not" in node:
        return "NOT " + describe(node["not"])
    op, v = node["op"], node.get("value")
    if op in {"is_null", "not_null"}:
        return f"{node['feature']} {op.replace('_', ' ')}"
    return f"{node['feature']} {op} {v}"
