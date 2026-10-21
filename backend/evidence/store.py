"""Tamper-evident evidence log: each row stores the hash of the previous one.

hash = sha256(prev_hash + canonical_json(row without hash)). Changing any old row breaks every
hash after it, which /v1/evidence/verify detects. Identifiers are stored only as salted hashes.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

GENESIS = "0" * 64
SALT = os.environ.get("PAYEE_SALT") or "ruko-dev-salt"  # team salt from .env

COLUMNS = ("id", "ts", "user_hash", "payee_hash", "caller_hash", "tier", "p_scam", "reasons",
           "playbook", "family_scores", "features", "intel_status", "stage_path",
           "model_version", "policy_version", "prev_hash", "hash")
JSON_COLS = {"reasons", "family_scores", "features", "intel_status", "stage_path"}


def pseudonym(value: str | None) -> str | None:
    return hashlib.sha256((SALT + value.strip().lower()).encode()).hexdigest() if value else None


def _digest(prev_hash: str, row: dict) -> str:
    body = {k: v for k, v in row.items() if k != "hash"}
    return hashlib.sha256((prev_hash + json.dumps(body, sort_keys=True, default=str)).encode()).hexdigest()


class EvidenceStore:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        self.db.execute(f"CREATE TABLE IF NOT EXISTS evidence ({', '.join(c + ' TEXT' for c in COLUMNS)},"
                        " seq INTEGER PRIMARY KEY AUTOINCREMENT)")
        self.db.commit()

    def _last_hash(self) -> str:
        r = self.db.execute("SELECT hash FROM evidence ORDER BY seq DESC LIMIT 1").fetchone()
        return r[0] if r else GENESIS

    def write(self, row: dict) -> dict:
        with self.lock:
            # Normalise to plain JSON types first so the hash is identical when re-read later.
            row = json.loads(json.dumps({**row, "prev_hash": self._last_hash()}, default=str))
            row["hash"] = _digest(row["prev_hash"], row)
            self.db.execute(f"INSERT INTO evidence ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                            [json.dumps(row[c], sort_keys=True, default=str) if c in JSON_COLS else
                             None if row[c] is None else str(row[c]) for c in COLUMNS])
            self.db.commit()
            return row

    def _rows(self, where: str = "", args: tuple = ()) -> list[dict]:
        cur = self.db.execute(f"SELECT {', '.join(COLUMNS)} FROM evidence {where} ORDER BY seq", args)
        out = []
        for r in cur.fetchall():
            d = dict(zip(COLUMNS, r))
            for c in JSON_COLS:
                d[c] = json.loads(d[c])
            # Episode records carry no score (p_scam None); keep it None so the hash still matches.
            d["p_scam"] = None if d["p_scam"] is None else float(d["p_scam"])
            out.append(d)
        return out

    def get(self, evidence_id: str) -> dict | None:
        rows = self._rows("WHERE id = ?", (evidence_id,))
        return rows[0] if rows else None

    def verify(self) -> dict:
        prev = GENESIS
        rows = self._rows()
        for row in rows:
            if row["prev_hash"] != prev or _digest(prev, row) != row["hash"]:
                return {"ok": False, "rows_checked": len(rows), "first_bad_id": row["id"]}
            prev = row["hash"]
        return {"ok": True, "rows_checked": len(rows), "first_bad_id": None}

    def clear(self) -> None:
        with self.lock:
            self.db.execute("DELETE FROM evidence")
            self.db.commit()
