"""Scam playbooks the engine names (Step 6): which scam type a payment looks like.

The list lives in `data/playbooks/playbooks.yaml` (the data folder owns its contents; this module
owns the format). It is read once at start. If the file is missing or wrong, the engine logs it and
uses BUILTIN below, the same rules, so a bad edit can never stop payments being checked.
`tests/test_playbooks.py` checks that the file and BUILTIN agree.

File format (checked in order; the first playbook whose `match` holds names the payment):

    version: playbooks-0.1
    playbooks:
      - name: refund_qr                     # snake_case; the app's message key is "<tier>_<name>"
        why: "an unknown caller on the line + a payee that was not typed (QR or picked)"
        match:                              # every condition must hold
          on_call: true                     # true: the feature is set; false: it is not (or unknown)
          unknown_caller: true              # a derived check, see DERIVED
          entry_typed: false
          lure_tag: kyc                     # any other value: equal; a list: one of them
          any:                              # at least one of these condition maps holds
            - {remote_control: true}
            - {session_dictated: true}

Feature names are those of `features/build.py` (`FAMILY`) plus DERIVED. An unknown name is an
error, so a typo cannot silently turn a playbook off.

playbooks-0.2 adds, for playbooks the blue team drafts and analysts approve
(red_team_blue_team/blue_team):

          amount_inr: {gte: 1000, lt: 10000}  # number comparisons: gte, gt, lte, lt; unknown never matches
          entry_method: qr                    # the request's own fields (REQUEST_FIELDS), not features
        approved_by: [asha, ravi]             # two different analysts approved it (blue-team review)

A playbook with `approved_by` does more than name the scam: policy raises the payment to at least
`approved_playbooks.min_tier` (api/policy.yaml), so the user is warned. Rule 5 still holds: its own
conditions must come from at least `min_condition_families` families (`families()` below), and
amount caps, trusted payees and the alert budget apply after it.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Callable

import yaml

from features.build import FAMILY

log = logging.getLogger("ruko.playbooks")

PATH = Path(os.environ.get("RUKO_PLAYBOOKS", Path(__file__).resolve().parents[2] / "data" / "playbooks" / "playbooks.yaml"))

Rule = tuple[str, str, Callable[[dict], bool]]


def unknown_caller(f: dict) -> bool:
    """A caller not in contacts, or a VoIP call whose number the phone cannot see (null is not safe)."""
    return bool(f["caller_unknown"]) or (bool(f["voip_call"]) and f["caller_unknown"] is None)


DERIVED: dict[str, Callable[[dict], Any]] = {"unknown_caller": unknown_caller}
DERIVED_FAMILY = {"unknown_caller": "C"}
# Fields of the /v1/decide request a playbook may match on (main.py adds them before naming).
REQUEST_FIELDS = {"entry_method": "B", "payer_says": "B"}
COMPARE: dict[str, Callable[[Any, Any], bool]] = {"gte": lambda a, b: a >= b, "gt": lambda a, b: a > b,
                                                  "lte": lambda a, b: a <= b, "lt": lambda a, b: a < b}
MIN_APPROVERS = 2

# The same rules as the shipped file, used when it cannot be read.
BUILTIN: list[Rule] = [
    # An active task-scam episode beats any older message on the phone.
    ("task_job", "the phone's task-scam watcher is ACTIVE (rewards in, bigger payments out)",
     lambda f: f["episode_state"] == 2),
    ("fake_kyc_apk", "an app installed from outside the store + a KYC message",
     lambda f: bool(f["sideloaded_last_24h"]) and f["lure_tag"] == "kyc"),
    ("fake_customer_care", "the user called an unknown number + screen control or dictated typing",
     lambda f: bool(f["outgoing_to_unknown"]) and bool(f["remote_control"] or f["session_dictated"])),
    ("otp_takeover", "a one-time code (OTP) for UPI or a bank arrived during a call with an unknown number",
     lambda f: bool(f.get("otp_on_call"))),
    ("digital_arrest", "an arrest-threat message",
     lambda f: f["lure_tag"] == "arrest_threat"),
    ("digital_arrest", "an unknown caller on the line + screen control, a video call, a story mismatch or dictated typing",
     lambda f: bool(f["on_call"]) and unknown_caller(f)
     and bool(f["remote_control"] or f.get("video_call") or f["story_mismatch"] or f["session_dictated"])),
    ("trading_group", "a trading-tip message",
     lambda f: f["lure_tag"] == "trading_tip"),
    ("task_job", "a task or job message",
     lambda f: f["lure_tag"] == "task_job"),
    ("refund_qr", "an unknown caller on the line + a payee that was not typed (QR or picked)",
     lambda f: bool(f["on_call"]) and unknown_caller(f) and not f["entry_typed"]),
]

NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class PlaybookError(ValueError):
    pass


def _value(f: dict, key: str) -> Any:
    return DERIVED[key](f) if key in DERIVED else f.get(key)


def _condition(key: str, want: Any) -> Callable[[dict], bool]:
    if key == "any":
        if not isinstance(want, list) or not want or not all(isinstance(m, dict) for m in want):
            raise PlaybookError("'any' needs a list of condition maps")
        options = [_all(m) for m in want]
        return lambda f: any(o(f) for o in options)
    if key not in FAMILY and key not in DERIVED and key not in REQUEST_FIELDS:
        raise PlaybookError(f"unknown feature '{key}'")
    if isinstance(want, dict):
        if not want or set(want) - set(COMPARE) or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in want.values()):
            raise PlaybookError(f"'{key}': a comparison map takes numbers under {sorted(COMPARE)}")
        tests = [(COMPARE[op], v) for op, v in want.items()]

        def compare(f: dict) -> bool:
            x = _value(f, key)
            if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
                return False                          # unknown is never inside a range (rule 1)
            return all(fn(x, v) for fn, v in tests)
        return compare
    if want is True:
        return lambda f: bool(_value(f, key))
    if want is False:
        return lambda f: not _value(f, key)
    if isinstance(want, list):
        return lambda f: _value(f, key) in want
    if isinstance(want, (str, int, float)):
        return lambda f: _value(f, key) == want
    raise PlaybookError(f"'{key}': cannot match {want!r}")


def _all(match: dict) -> Callable[[dict], bool]:
    if not isinstance(match, dict) or not match:
        raise PlaybookError("'match' needs at least one condition")
    conds = [_condition(k, v) for k, v in match.items()]
    return lambda f: all(c(f) for c in conds)


def parse(doc: dict) -> list[Rule]:
    """The rules in a playbooks file, in order. Raises PlaybookError on anything it does not understand."""
    if not isinstance(doc, dict) or not isinstance(doc.get("playbooks"), list) or not doc["playbooks"]:
        raise PlaybookError("expected a non-empty 'playbooks' list")
    rules: list[Rule] = []
    for i, p in enumerate(doc["playbooks"]):
        if not isinstance(p, dict):
            raise PlaybookError(f"playbook {i}: expected a map")
        name, why = p.get("name"), p.get("why")
        if not isinstance(name, str) or not NAME.match(name):
            raise PlaybookError(f"playbook {i}: 'name' must be snake_case")
        if not isinstance(why, str) or not why.strip():
            raise PlaybookError(f"playbook {name}: 'why' is required (the analyst console shows it)")
        unknown = set(p) - {"name", "why", "match", "title", "approved_by"}
        if unknown:
            raise PlaybookError(f"playbook {name}: unknown keys {sorted(unknown)}")
        if "approved_by" in p:
            who = p["approved_by"]
            if not isinstance(who, list) or len({str(a).strip().lower() for a in who if str(a).strip()}) < MIN_APPROVERS:
                raise PlaybookError(f"playbook {name}: 'approved_by' needs {MIN_APPROVERS} different analysts")
        try:
            rules.append((name, why, _all(p.get("match"))))
        except PlaybookError as e:
            raise PlaybookError(f"playbook {name}: {e}") from None
    return rules


def families(match: dict) -> set[str]:
    """The evidence families (C, L, P, B) a match map's conditions come from; an `any` counts only the
    families all its options share. Stage (S) is not evidence of its own."""
    out: set[str] = set()
    for key, want in match.items():
        if key == "any":
            opts = [families(m) for m in want]
            out |= set.intersection(*opts) if opts else set()
        else:
            out.add(FAMILY.get(key) or DERIVED_FAMILY.get(key) or REQUEST_FIELDS[key])
    return out & {"C", "L", "P", "B"}


def approved(doc: dict) -> dict[str, list[str]]:
    """{name: families of its conditions} for playbooks two analysts approved. A name counts only if
    every entry with it is approved; its families are those of its weakest entry."""
    out: dict[str, list[str]] = {}
    entries: dict[str, list[dict]] = {}
    for p in doc["playbooks"]:
        entries.setdefault(p["name"], []).append(p)
    for name, ps in entries.items():
        if all("approved_by" in p for p in ps):
            out[name] = sorted(min((families(p["match"]) for p in ps), key=len))
    return out


def uses_request_fields(doc: dict) -> bool:
    def walk(m: dict) -> bool:
        return any(k in REQUEST_FIELDS or (k == "any" and any(walk(x) for x in v)) for k, v in m.items())
    return any(walk(p["match"]) for p in doc["playbooks"])


def load_approved(path: Path = PATH) -> tuple[dict[str, list[str]], bool]:
    """(approved playbooks with their condition families, whether any rule reads request fields);
    ({}, False) whenever load() would fall back to BUILTIN."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        parse(doc)
        return approved(doc), uses_request_fields(doc)
    except (FileNotFoundError, PlaybookError, yaml.YAMLError, OSError):
        return {}, False


def load(path: Path = PATH) -> tuple[list[Rule], str]:
    """The playbooks and where they came from ("file:<version>" or "builtin")."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        rules = parse(doc)
        return rules, f"file:{doc.get('version', '?')}"
    except FileNotFoundError:
        log.warning("no playbooks file at %s, using the built-in playbooks", path)
    except (PlaybookError, yaml.YAMLError, OSError) as e:
        log.error("playbooks file %s not used (%s), using the built-in playbooks", path, e)
    return BUILTIN, "builtin"
