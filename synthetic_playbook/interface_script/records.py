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


def stream(world_dir: str | Path, *, seed: int = 0, warmup_days: float = 7,
           normal_sample: float = 0.25, device_model: str | Path | None = DEVICE_MODEL) -> Iterator[dict]:
    """Every record of the world, in order. Payments before the warm-up end are marked
    `judge: False`: they build the user's history, and the server's answers about them are not scored."""
    tables, manifest = load_world(world_dir)
    a = load_assumptions()
    view = PhoneView(tables, a, seed)
    start = world_start(manifest)
    feed = EpisodeFeed(view.traits, start)
    keep_from = (start + timedelta(days=warmup_days)).timestamp()
    dm = device_score.load(device_model) if device_model and Path(device_model).exists() else None

    for item in phone_stream(tables, view, feed, seed, dm):
        if item[0] == "episode":
            yield {"kind": "episode", "body": item[1]}
            continue
        _, req, info = item
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
