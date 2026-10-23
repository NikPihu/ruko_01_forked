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

# The same rules as the shipped file, used when it cannot be read.
BUILTIN: list[Rule] = [
    # An active task-scam episode beats any older message on the phone.
    ("task_job", "the phone's task-scam watcher is ACTIVE (rewards in, bigger payments out)",
     lambda f: f["episode_state"] == 2),
    ("fake_kyc_apk", "an app installed from outside the store + a KYC message",
     lambda f: bool(f["sideloaded_last_24h"]) and f["lure_tag"] == "kyc"),
    ("fake_customer_care", "the user called an unknown number + screen control or dictated typing",
     lambda f: bool(f["outgoing_to_unknown"]) and bool(f["remote_control"] or f["session_dictated"])),
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
    if key not in FAMILY and key not in DERIVED:
        raise PlaybookError(f"unknown feature '{key}'")
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
        unknown = set(p) - {"name", "why", "match", "title"}
        if unknown:
            raise PlaybookError(f"playbook {name}: unknown keys {sorted(unknown)}")
        try:
            rules.append((name, why, _all(p.get("match"))))
        except PlaybookError as e:
            raise PlaybookError(f"playbook {name}: {e}") from None
    return rules


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
