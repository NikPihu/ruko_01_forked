"""Same scam, many phones (#1): the money handles shared by scam messages on different phones.

AI crews reword their messages endlessly, but every version must carry the thing that moves money:
the UPI ID to pay, the link to open, the number to call back. When a phone's scam check flags a
message, it sends those handles with its `lure_seen` early warning (c2-0.13), never the text
(rule 2): the UPI ID plain, like payees (rule 7); link hosts and call-back numbers as salted SHA-256
pseudonyms. This store counts the distinct users each handle reached in a sliding window; one that
reached `min_users` different users is "spreading". Numbers in policy.yaml `campaign:` (rule 6).

The phone normalises and hashes exactly like `normalise()` / `wire_value()` here; both are checked
against `contracts/examples/handle_vectors.json`.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml

from graph.store import user_node

_ROOT = Path(__file__).resolve().parents[2]
_RULES = json.loads((_ROOT / "contracts" / "watch_rules.json").read_text(encoding="utf-8"))
SALT: str = _RULES.get("handle_salt", "ruko-handles-v1")       # pseudonymisation, not a secret
MAX_HANDLES: int = _RULES.get("max_handles", 10)
_CFG = (yaml.safe_load((_ROOT / "backend" / "api" / "policy.yaml").read_text()) or {}).get("campaign") or {}
CAMPAIGN = {"window_minutes": 60, "min_users": 3, "keep_hours": 24, **_CFG}

KINDS = ("upi", "link", "phone")
_VPA = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}@[a-z]{2,20}$")
_HOST = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


def normalise(kind: str, raw: str) -> Optional[str]:
    """One canonical form per handle, or None if it is not one (the phone does the same)."""
    s = (raw or "").strip().lower()
    if kind == "upi":
        return s if _VPA.match(s) else None
    if kind == "link":
        s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)          # scheme
        s = re.split(r"[/?#]", s, maxsplit=1)[0]              # path, query, fragment
        s = s.split("@")[-1].split(":")[0].rstrip(".")       # user info, port
        s = s[4:] if s.startswith("www.") else s
        return s if _HOST.match(s) else None
    if kind == "phone":
        d = re.sub(r"\D", "", s)
        if len(d) == 10 and d[0] in "6789":
            return "+91" + d
        if len(d) == 11 and d.startswith("0") and d[1] in "6789":
            return "+91" + d[1:]
        if len(d) == 12 and d.startswith("91") and d[2] in "6789":
            return "+" + d
        return "+" + d if 8 <= len(d) <= 15 else None
    return None


def hashed(kind: str, value: str, salt: str = SALT) -> str:
    return "sha256:" + hashlib.sha256(f"{salt}|{kind}|{value}".encode("utf-8")).hexdigest()


def wire_value(kind: str, raw: str, salt: str = SALT) -> Optional[str]:
    """What the phone sends for a raw handle: the UPI ID plain, link hosts and numbers hashed."""
    v = normalise(kind, raw)
    if v is None:
        return None
    return v if kind == "upi" else hashed(kind, v, salt)


class CampaignStore:
    def __init__(self, window_minutes: float = CAMPAIGN["window_minutes"], min_users: int = CAMPAIGN["min_users"],
                 keep_hours: float = CAMPAIGN["keep_hours"]) -> None:
        self.window = timedelta(minutes=window_minutes)
        self.min_users = min_users
        self.keep = timedelta(hours=keep_hours)
        self.seen: dict[tuple[str, str], dict[str, tuple[datetime, datetime]]] = defaultdict(dict)

    def reset(self) -> None:
        self.seen.clear()

    def record(self, user_id: str, handles: list[tuple[str, str]], ts: datetime) -> int:
        """Handles from one flagged message on one phone. Returns how many were kept."""
        u, kept = user_node(user_id), 0
        for kind, value in handles[:MAX_HANDLES]:
            if kind not in KINDS or not value:
                continue
            key = (kind, value.strip().lower() if kind == "upi" else value)
            first, _ = self.seen[key].get(u, (ts, ts))
            self.seen[key][u] = (min(first, ts), ts)
            kept += 1
        return kept

    def users(self, kind: str, value: Optional[str], now: datetime) -> int:
        """Distinct users this handle reached within the window up to `now`."""
        if not value:
            return 0
        key = (kind, value.strip().lower() if kind == "upi" else value)
        return sum(1 for _, last in self.seen.get(key, {}).values() if now - self.window <= last <= now)

    def spreading(self, kind: str, value: Optional[str], now: datetime) -> bool:
        return self.users(kind, value, now) >= self.min_users

    def top(self, now: datetime, limit: int = 20) -> list[dict]:
        """Handles spreading now, most people first (console "Spreading now"). Hashed ones stay hidden."""
        out = []
        for (kind, value), by_user in self.seen.items():
            recent = [(f, l) for f, l in by_user.values() if now - self.window <= l <= now]
            if len(recent) < 2:
                continue
            out.append({"kind": kind, "value": value if kind == "upi" else None,
                        "users": len(recent), "spreading": len(recent) >= self.min_users,
                        "first_seen": min(f for f, _ in recent).isoformat(),
                        "last_seen": max(l for _, l in recent).isoformat()})
        return sorted(out, key=lambda x: (-x["users"], x["last_seen"]))[:limit]

    def latest(self) -> Optional[datetime]:
        """When the newest handle was seen, or None."""
        return max((last for by_user in self.seen.values() for _, last in by_user.values()), default=None)

    def expire(self, now: datetime) -> None:
        for key in list(self.seen):
            users = {u: t for u, t in self.seen[key].items() if now - t[1] <= self.keep}
            if users:
                self.seen[key] = users
            else:
                del self.seen[key]
