"""The transaction database: every payment check, its full decision and what happened after.

In memory by default (SQLite ":memory:"): fast, nothing on disk, empty on every start, and every
test gets its own. Pass a file path to keep a run (e.g. for `python -m store.export`). All SQL lives
here, in plain SQL that Postgres also accepts, so a real database later means changing this module.

Privacy (rules 2, 4, 7): users are stored as `pseudonym(user_id)`; payees stay plain because they
must be looked up. `decision_details` holds every input value and every score: it is for the
analyst console and training only, never for the app.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from evidence.store import pseudonym

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    payment_id     TEXT PRIMARY KEY,   -- the /v1/decide request_id
    user_hash      TEXT NOT NULL,
    payee_upi      TEXT NOT NULL,
    amount_inr     REAL NOT NULL,
    entry_method   TEXT,
    ts             TEXT NOT NULL,      -- ISO 8601 with offset
    tier           TEXT NOT NULL,
    reasons        TEXT NOT NULL,      -- JSON list
    message_key    TEXT,
    playbook       TEXT,
    stage          TEXT,
    pause_minutes  INTEGER,
    scorer_version TEXT,
    policy_version TEXT,
    evidence_id    TEXT,
    fail_open      INTEGER NOT NULL,
    latency_ms     REAL,
    status         TEXT NOT NULL,      -- checked | completed | cancelled
    outcome_ts     TEXT
);
CREATE INDEX IF NOT EXISTS payments_user ON payments(user_hash, ts);
CREATE INDEX IF NOT EXISTS payments_payee ON payments(payee_upi, ts);
CREATE INDEX IF NOT EXISTS payments_tier ON payments(tier, ts);

CREATE TABLE IF NOT EXISTS decision_details (
    payment_id     TEXT PRIMARY KEY REFERENCES payments(payment_id),
    features       TEXT NOT NULL,      -- JSON: every input value
    p_scam         REAL,
    family_scores  TEXT,               -- JSON {C, L, P, B}
    lit_families   TEXT,               -- JSON list
    policy_steps   TEXT,               -- JSON list of policy rules that changed the tier
    intel_status   TEXT,               -- JSON {source: ok | timeout | ...}
    stage_path     TEXT,               -- JSON [[stage, ts], ...]
    signals        TEXT,               -- JSON [{family, reason, strength}], every signal that fired
    steps          TEXT,               -- JSON {seen: [step], unmeasured: [step]} (contracts/steps.json)
    playbook_search TEXT,              -- JSON [{name, similarity, matched, missing, unmeasured}], best first
    explanation    TEXT                -- JSON, filled by the explainable layer
);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id      TEXT PRIMARY KEY,
    payment_id       TEXT NOT NULL,
    user_hash        TEXT NOT NULL,
    action           TEXT NOT NULL,
    why              TEXT,
    dwell_ms         INTEGER,
    trusted_accepted INTEGER,
    ts               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS feedback_payment ON feedback(payment_id);

CREATE TABLE IF NOT EXISTS watch_events (
    event_id   TEXT PRIMARY KEY,
    user_hash  TEXT NOT NULL,
    kind       TEXT NOT NULL,
    detail     TEXT,                   -- JSON
    ts         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episode_events (
    event_id   TEXT PRIMARY KEY,
    user_hash  TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    trigger    TEXT NOT NULL,
    risk       TEXT,
    accounts   TEXT,                   -- JSON list of UPI IDs
    case_id    TEXT,
    ts         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    case_id    TEXT PRIMARY KEY,
    user_hash  TEXT,
    body       TEXT NOT NULL,          -- JSON, as the console shows it
    opened_ts  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trusted_payees (
    user_hash  TEXT NOT NULL,
    payee_upi  TEXT NOT NULL,
    source     TEXT NOT NULL,          -- app | feedback
    ts         TEXT NOT NULL,
    PRIMARY KEY (user_hash, payee_upi)
);

CREATE TABLE IF NOT EXISTS pattern_reviews (
    pattern_id TEXT PRIMARY KEY,       -- an emerging pattern (patterns/emerging.py)
    status     TEXT NOT NULL,          -- named | dismissed
    name       TEXT,                   -- the analyst's name for the new scam type
    analyst    TEXT NOT NULL,
    draft      TEXT,                   -- draft playbook YAML for the data folder
    ts         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS received (
    event_id    TEXT PRIMARY KEY,      -- POST /v1/payment/received (c2-0.11), one per credit
    user_hash   TEXT NOT NULL,         -- the receiver
    sender_upi  TEXT,                  -- null when the bank SMS named no UPI ID
    amount_inr  REAL NOT NULL,
    ts          TEXT NOT NULL,         -- when the bank SMS arrived
    source      TEXT NOT NULL,         -- bank_sms
    sender_name TEXT                   -- c2-0.12: the account holder's name the bank gave, if any
);
CREATE INDEX IF NOT EXISTS received_user ON received(user_hash, ts);
CREATE INDEX IF NOT EXISTS received_sender ON received(sender_upi, ts);

CREATE TABLE IF NOT EXISTS reviews (
    payee_upi  TEXT NOT NULL,
    reviewer   TEXT NOT NULL,
    decision   TEXT NOT NULL,          -- approve | reject
    ts         TEXT NOT NULL,
    PRIMARY KEY (payee_upi, reviewer)
);
"""

TIER_RANK = {"T0": 0, "T1": 1, "T2": 2, "T3": 3, "T4": 4}
_JSON_PAYMENT = ("reasons",)
_JSON_DETAILS = ("features", "family_scores", "lit_families", "policy_steps", "intel_status", "stage_path",
                 "signals", "steps", "playbook_search", "explanation")


def _iso(ts: datetime | str | None) -> Optional[str]:
    return ts.isoformat() if isinstance(ts, datetime) else ts


def _dumps(v: Any) -> str:
    return json.dumps(v, default=str, sort_keys=True)


class TxnStore:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
            # A database file from c2-0.11 has no sender_name column yet.
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(received)")}
            if "sender_name" not in cols:
                self.db.execute("ALTER TABLE received ADD COLUMN sender_name TEXT")
            # ... and one from before plan v3 step 3 has no steps / playbook_search columns.
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(decision_details)")}
            for c in ("steps", "playbook_search"):
                if c not in cols:
                    self.db.execute(f"ALTER TABLE decision_details ADD COLUMN {c} TEXT")

    # ---------- writes ----------

    def record_decision(self, payment: dict, details: dict) -> None:
        """One /v1/decide. `payment` has the payments columns (user_id plain, pseudonymised here)."""
        p = {**payment, "user_hash": pseudonym(payment.pop("user_id")), "ts": _iso(payment["ts"]),
             "reasons": _dumps(payment.get("reasons") or []), "fail_open": int(bool(payment.get("fail_open"))),
             "status": "checked"}
        cols = ("payment_id", "user_hash", "payee_upi", "amount_inr", "entry_method", "ts", "tier", "reasons",
                "message_key", "playbook", "stage", "pause_minutes", "scorer_version", "policy_version",
                "evidence_id", "fail_open", "latency_ms", "status")
        d = {k: (_dumps(details.get(k)) if k in _JSON_DETAILS else details.get(k)) for k in
             ("features", "p_scam", "family_scores", "lit_families", "policy_steps", "intel_status", "stage_path",
              "signals", "steps", "playbook_search", "explanation")}
        if d["features"] is None or d["features"] == "null":
            d["features"] = "{}"
        with self.lock, self.db:
            # A repeated request_id (the phone retried) keeps the first decision's row but its newest outcome.
            self.db.execute(
                f"INSERT INTO payments ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                "ON CONFLICT(payment_id) DO NOTHING", [p.get(c) for c in cols])
            self.db.execute(
                "INSERT INTO decision_details (payment_id, features, p_scam, family_scores, lit_families, "
                "policy_steps, intel_status, stage_path, signals, steps, playbook_search, explanation) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(payment_id) DO NOTHING",
                [p["payment_id"], d["features"], d["p_scam"], d["family_scores"], d["lit_families"],
                 d["policy_steps"], d["intel_status"], d["stage_path"], d["signals"], d["steps"],
                 d["playbook_search"], d["explanation"]])

    def record_outcome(self, payment_id: str, status: str, ts: datetime | str) -> bool:
        """Completed or cancelled; the first final status wins (as in the payment graph)."""
        with self.lock, self.db:
            cur = self.db.execute(
                "UPDATE payments SET status = ?, outcome_ts = ? WHERE payment_id = ? AND status = 'checked'",
                [status, _iso(ts), payment_id])
            return cur.rowcount == 1

    def record_feedback(self, row: dict) -> None:
        r = {**row, "user_hash": pseudonym(row.pop("user_id")), "ts": _iso(row["ts"]),
             "trusted_accepted": None if row.get("trusted_accepted") is None else int(row["trusted_accepted"])}
        cols = ("feedback_id", "payment_id", "user_hash", "action", "why", "dwell_ms", "trusted_accepted", "ts")
        with self.lock, self.db:
            self.db.execute(f"INSERT OR IGNORE INTO feedback ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            [r.get(c) for c in cols])

    def record_watch(self, event_id: str, user_id: str, kind: str, detail: dict, ts: datetime | str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO watch_events VALUES (?,?,?,?,?)",
                            [event_id, pseudonym(user_id), kind, _dumps(detail), _iso(ts)])

    def record_episode(self, event_id: str, user_id: str, episode_id: str, trigger: str, risk: str | None,
                       accounts: list[str], case_id: str | None, ts: datetime | str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO episode_events VALUES (?,?,?,?,?,?,?,?)",
                            [event_id, pseudonym(user_id), episode_id, trigger, risk, _dumps(accounts), case_id,
                             _iso(ts)])

    def record_received(self, event_id: str, user_id: str, sender_upi: str | None, amount_inr: float,
                        ts: datetime | str, source: str, sender_name: str | None = None) -> bool:
        """Money a user received (c2-0.11). The sender stays plain (name and UPI ID, it must be looked
        up); the receiver is pseudonymised (rule 7). False for a repeated event_id."""
        with self.lock, self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO received (event_id, user_hash, sender_upi, amount_inr, ts, source, sender_name) "
                "VALUES (?,?,?,?,?,?,?)",
                [event_id, pseudonym(user_id), sender_upi.strip().lower() if sender_upi else None, amount_inr,
                 _iso(ts), source, " ".join(sender_name.split()) if sender_name else None])
            return cur.rowcount == 1

    def record_case(self, case: dict) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO cases VALUES (?,?,?,?)",
                            [case["case_id"], case.get("user_hash"), _dumps(case), case.get("opened_at", "")])

    def record_trusted(self, user_id: str, payee: str, source: str, ts: datetime | str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO trusted_payees VALUES (?,?,?,?)",
                            [pseudonym(user_id), payee.strip().lower(), source, _iso(ts)])

    def record_review(self, payee: str, reviewer: str, decision: str, ts: datetime | str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO reviews VALUES (?,?,?,?)",
                            [payee.strip().lower(), reviewer, decision, _iso(ts)])

    def record_pattern_review(self, pattern_id: str, status: str, name: str | None, analyst: str,
                              draft: str | None, ts: datetime | str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO pattern_reviews VALUES (?,?,?,?,?,?)",
                            [pattern_id, status, name, analyst, draft, _iso(ts)])

    def pattern_reviews(self) -> dict[str, dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM pattern_reviews").fetchall()
        return {r["pattern_id"]: dict(r) for r in rows}

    def set_explanation(self, payment_id: str, explanation: dict) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE decision_details SET explanation = ? WHERE payment_id = ?",
                            [_dumps(explanation), payment_id])

    def reset(self) -> None:
        with self.lock, self.db:
            for t in ("payments", "decision_details", "feedback", "watch_events", "episode_events", "cases",
                      "trusted_payees", "reviews", "pattern_reviews", "received"):
                self.db.execute(f"DELETE FROM {t}")

    # ---------- reads ----------

    @staticmethod
    def _payment(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["reasons"] = json.loads(d["reasons"])
        d["fail_open"] = bool(d["fail_open"])
        return d

    @staticmethod
    def _details(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in _JSON_DETAILS:
            if d.get(k) is not None:
                d[k] = json.loads(d[k])
        return d

    def payment(self, payment_id: str) -> Optional[dict]:
        with self.lock:
            row = self.db.execute("SELECT * FROM payments WHERE payment_id = ?", [payment_id]).fetchone()
        return self._payment(row) if row else None

    def details(self, payment_id: str) -> Optional[dict]:
        with self.lock:
            row = self.db.execute("SELECT * FROM decision_details WHERE payment_id = ?", [payment_id]).fetchone()
        return self._details(row) if row else None

    def transactions(self, user_hash: str | None = None, payee: str | None = None, min_tier: str = "T0",
                     status: str | None = None, since: str | None = None, until: str | None = None,
                     limit: int = 200) -> list[dict]:
        """Payments newest first, filtered. Times compare as ISO strings (all stored with an offset)."""
        where, args = ["1=1"], []
        if user_hash:
            where.append("user_hash = ?"), args.append(user_hash)
        if payee:
            where.append("payee_upi = ?"), args.append(payee.strip().lower())
        if TIER_RANK.get(min_tier, 0) > 0:
            where.append("tier IN (%s)" % ",".join("?" * sum(r >= TIER_RANK[min_tier] for r in TIER_RANK.values())))
            args += [t for t, r in TIER_RANK.items() if r >= TIER_RANK[min_tier]]
        if status:
            where.append("status = ?"), args.append(status)
        if since:
            where.append("ts >= ?"), args.append(since)
        if until:
            where.append("ts <= ?"), args.append(until)
        sql = f"SELECT * FROM payments WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ?"
        with self.lock:
            rows = self.db.execute(sql, [*args, max(1, min(limit, 1000))]).fetchall()
        return [self._payment(r) for r in rows]

    def received(self, user_hash: str | None = None, sender: str | None = None, since: str | None = None,
                 until: str | None = None, limit: int = 200) -> list[dict]:
        """Money users received (c2-0.11), newest first, filtered like transactions()."""
        where, args = ["1=1"], []
        if user_hash:
            where.append("user_hash = ?"), args.append(user_hash)
        if sender:
            where.append("sender_upi = ?"), args.append(sender.strip().lower())
        if since:
            where.append("ts >= ?"), args.append(since)
        if until:
            where.append("ts <= ?"), args.append(until)
        sql = f"SELECT * FROM received WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ?"
        with self.lock:
            rows = self.db.execute(sql, [*args, max(1, min(limit, 1000))]).fetchall()
        return [dict(r) for r in rows]

    def payments_of(self, user_id: str, limit: int = 100) -> list[dict]:
        """One user's own payments (for the app): plain words only, no scores."""
        keep = ("payment_id", "payee_upi", "amount_inr", "ts", "tier", "reasons", "message_key", "playbook",
                "status", "outcome_ts")
        return [{k: p[k] for k in keep} for p in self.transactions(user_hash=pseudonym(user_id), limit=limit)]

    def timeline(self, user_hash: str, limit: int = 200) -> list[dict]:
        """Everything about one (pseudonymous) user in time order: payments, outcomes, money received,
        feedback, phone events."""
        items: list[dict] = []
        for p in self.transactions(user_hash=user_hash, limit=limit):
            items.append({"ts": p["ts"], "kind": "payment", **p})
            if p["outcome_ts"]:
                items.append({"ts": p["outcome_ts"], "kind": "outcome", "payment_id": p["payment_id"],
                              "status": p["status"]})
        with self.lock:
            fb = self.db.execute("SELECT * FROM feedback WHERE user_hash = ?", [user_hash]).fetchall()
            we = self.db.execute("SELECT * FROM watch_events WHERE user_hash = ?", [user_hash]).fetchall()
            ee = self.db.execute("SELECT * FROM episode_events WHERE user_hash = ?", [user_hash]).fetchall()
        items += [{"kind": "feedback", **dict(r)} for r in fb]
        items += [{**dict(r), "watch_kind": r["kind"], "kind": "watch", "detail": json.loads(r["detail"] or "null")}
                  for r in we]
        items += [{"kind": "episode", **{**dict(r), "accounts": json.loads(r["accounts"] or "[]")}} for r in ee]
        items += [{"kind": "received", **r} for r in self.received(user_hash=user_hash, limit=limit)]
        return sorted(items, key=lambda i: i["ts"])[-limit:]

    def lure_counts(self) -> dict:
        """Scam messages the phones reported (watch events), and how many looked AI-written."""
        with self.lock:
            seen = self.db.execute("SELECT COUNT(*) FROM watch_events WHERE kind = 'lure_seen'").fetchone()[0]
            ai = self.db.execute("SELECT COUNT(*) FROM watch_events WHERE kind = 'lure_seen' "
                                 "AND detail LIKE '%\"ai_written\": true%'").fetchone()[0]
        return {"lures_seen": seen, "ai_written": ai}

    def watch_counts(self) -> dict:
        """Early warnings the phones sent (POST /v1/watch), by kind."""
        with self.lock:
            rows = self.db.execute("SELECT kind, COUNT(*) FROM watch_events GROUP BY kind").fetchall()
        return {k: n for k, n in rows}

    def feedback_for(self, payment_id: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM feedback WHERE payment_id = ? ORDER BY ts", [payment_id]).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        with self.lock:
            return {t: self.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("payments", "decision_details", "feedback", "watch_events", "episode_events", "cases",
                              "trusted_payees", "reviews", "received")}

    def rows_for_export(self) -> list[dict]:
        """Payments joined with their details, one flat row each (for training data, later)."""
        with self.lock:
            rows = self.db.execute("SELECT p.*, d.features, d.p_scam, d.family_scores, d.lit_families, "
                                   "d.policy_steps, d.intel_status FROM payments p "
                                   "LEFT JOIN decision_details d USING (payment_id) ORDER BY p.ts").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            feats = json.loads(d.pop("features") or "{}")
            fam = json.loads(d.pop("family_scores") or "{}")
            d["reasons"] = json.loads(d["reasons"])
            out.append({**d, **{f"f_{k}": v for k, v in feats.items()},
                        **{f"family_{k}": v for k, v in fam.items()}})
        return out
