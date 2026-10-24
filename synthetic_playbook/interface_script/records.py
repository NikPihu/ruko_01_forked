"""Turn a built world into the records a phone would send to the server, in time order.

This reuses ml/dataset/replay.py's phone view, so a payment becomes exactly the request the app
would have sent (same context, same on-device verdict). Nothing new is invented here.

Yields dicts the sender can post as-is:
    {"kind": "episode", "body": {...}}
    {"kind": "watch",   "body": {...}}
    {"kind": "pay",     "body": {...}, "label": {...}}   label = ground truth, never sent
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Iterator

from dataset.episodes import EpisodeFeed
from dataset.phone_view import PhoneView, keyed_rng, load_assumptions
from dataset.replay import DEVICE_MODEL, load_world, phone_stream, world_start
from model.device import score as device_score


def _json(model) -> dict:
    return json.loads(model.model_dump_json(exclude_none=True))


def payments_for(world_dir: str | Path, only_users: set[str] | None = None) -> int:
    """How many payments `stream` will yield, so a caller can show real progress."""
    tables, _ = load_world(world_dir)
    users, led = tables["users"], tables["ledger"]
    if only_users is not None:
        users = users[users.user_id.isin(only_users)]
    return int(led.from_upi.isin(set(users.upi_id)).sum())


def stream(world_dir: str | Path, *, seed: int = 0, warmup_days: float = 7,
           normal_sample: float = 0.25, device_model: str | Path | None = DEVICE_MODEL,
           only_users: set[str] | None = None) -> Iterator[dict]:
    """Every record of the world, in order. Payments before the warm-up end are marked
    `judge: False`: they build the user's history, and the server's answers about them are not scored.

    `only_users` keeps just those users' records. Each kept user still sends **all** of their own
    payments, so their history and baseline at the server are exactly right; users nobody scores
    are left out, which is where most of the time went.
    """
    tables, manifest = load_world(world_dir)
    a = load_assumptions()
    view = PhoneView(tables, a, seed)
    start = world_start(manifest)
    feed = EpisodeFeed(view.traits, start)
    keep_from = (start + timedelta(days=warmup_days)).timestamp()
    dm = device_score.load(device_model) if device_model and Path(device_model).exists() else None

    for item in phone_stream(tables, view, feed, seed, dm):
        if item[0] == "episode":
            body = item[1]
            if only_users is None or body.get("user_id") in only_users:
                yield {"kind": "episode", "body": body}
            continue
        _, req, info = item
        if only_users is not None and req.user_id not in only_users:
            continue
        judged = info["t"] >= keep_from
        if not info["is_scam"]:
            # Honest payments are sampled: they measure false alarms, and we do not need all of them.
            if not judged or keyed_rng(seed, "keep", info["tx"]).random() >= normal_sample:
                judged = False
        yield {"kind": "pay", "body": _json(req), "label": {
            "tx_id": info["tx"], "user_id": req.user_id, "payee_upi": req.payee_upi_id,
            "amount_inr": req.amount_inr, "ts": req.ts.isoformat(), "flow": info["flow"],
            "journey_id": info["journey_id"], "playbook": info["playbook"],
            "is_scam": bool(info["is_scam"]), "stage": info["stage"],
            "journey_pay_index": info["pay_index"], "judge": judged,
            "device_level": (info["verdict"] or {}).get("level"),
            "device_class": (info["verdict"] or {}).get("fraud_class")}}
