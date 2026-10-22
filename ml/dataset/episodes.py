"""The phone's background task-scam watcher for every simulated user (contracts c2-0.3, c2-0.4).

Uses the backend's own state machine (features.episode, the same rules as EpisodeTracker.kt) and
feeds it the way the phone does: credits arrive as bank SMS (cashback alerts are skipped by the
parser) and payments out come from this app's history, all in time order. The watcher needs SMS
checks, so users without them have no episode (`context.episode: null`). Like
features/offline_episode.py, the first days only build history: the world has none before day 1,
so every early credit would look like it came from a stranger.

It also queues the episode events (POST /v1/episode) that phones with "Share suspicious accounts"
on would send, with the same triggers as the team's evaluation (data/eval/episode_eval.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from eval.episode_eval import _event as queue_event_if_triggered
from features.bank_sms import Txn
from features.episode import EpisodeTracker, load_rules
from features.offline_episode import IGNORED_BY_PARSER, WARMUP_DAYS


class EpisodeFeed:
    def __init__(self, traits: dict, world_start: datetime, rules: dict | None = None):
        self.rules = rules or load_rules()
        self.trackers = {uid: EpisodeTracker(self.rules, sms_read=True) for uid, tr in traits.items() if tr.sms}
        self.sharing = {uid for uid, tr in traits.items() if tr.sms and tr.share_accounts}
        self.warm_until = (world_start + timedelta(days=WARMUP_DAYS)).timestamp()
        self.events: list[dict] = []  # queued episode events, oldest first
        self._sent = 0

    def credit(self, uid: str, ts: datetime, amount: float, sender: str, flow: str) -> None:
        t = self.trackers.get(uid)
        if t is None or flow in IGNORED_BY_PARSER or ts.timestamp() < self.warm_until:
            return
        before = (t.ep.state, len(t.ep.bait), {b.counterparty for b in t.ep.bait})
        t.add(Txn(ts.timestamp(), float(amount), "in", sender, from_sms=True))
        self._maybe_event(uid, t, before, ts)

    def debit(self, uid: str, ts: datetime, amount: float, payee: str) -> None:
        t = self.trackers.get(uid)
        if t is None:
            return
        before = (t.ep.state, len(t.ep.outs), None)
        t.add(Txn(ts.timestamp(), float(amount), "out", payee.lower()))
        if ts.timestamp() >= self.warm_until:
            self._maybe_event(uid, t, before, ts)

    def summary(self, uid: str, t: float, payee: str) -> dict | None:
        """`context.episode` just before a payment, or None when this user has no watcher."""
        tr = self.trackers.get(uid)
        return tr.summary(t, payee=payee) if tr else None

    def due(self, ts: datetime) -> list[dict]:
        """Episode events queued up to `ts` that have not been handed out yet."""
        out = []
        while self._sent < len(self.events) and self.events[self._sent]["ts"] <= ts:
            out.append(self.events[self._sent]["body"])
            self._sent += 1
        return out

    def _maybe_event(self, uid: str, t: EpisodeTracker, before: tuple, ts: datetime) -> None:
        if uid in self.sharing:
            queue_event_if_triggered(self.events, uid, t, before, ts, self.rules["version"])
