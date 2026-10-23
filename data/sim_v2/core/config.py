"""Load world.yaml, assumptions.yaml, playbooks/, lookalikes.yaml and scenarios/ into one Config."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from sim_v2.core.rng import stream

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@dataclass
class Config:
    seed: int
    users: int
    days: int
    end: datetime
    world: str
    victim_rate: float
    randomise: bool
    users_per_locality: int
    localities_per_crew: int
    a: dict                       # assumptions: section -> key -> value (ranges already resolved)
    a_meta: dict                  # the raw assumption entries (value, range, src, conf)
    playbooks: dict
    lookalikes: dict
    demo: dict
    raw_world: dict = field(default_factory=dict)

    @property
    def start(self) -> datetime:
        return self.end - timedelta(days=self.days)

    def get(self, dotted: str):
        sec, key = dotted.split(".", 1)
        return self.a[sec][key]

    def fingerprint(self) -> str:
        blob = json.dumps({"world": self.raw_world, "a": self.a, "pb": self.playbooks, "la": self.lookalikes,
                           "demo": self.demo}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]


def load(config_dir: Path = CONFIG_DIR, **overrides) -> Config:
    w = _read(config_dir / "world.yaml")
    w.update({k: v for k, v in overrides.items() if v is not None})
    raw_a = _read(config_dir / "assumptions.yaml")
    seed, randomise = int(w["seed"]), bool(w.get("randomise", False))
    a: dict = {}
    for sec, items in raw_a.items():
        a[sec] = {}
        for key, entry in items.items():
            v = entry["v"]
            if randomise and "range" in entry:   # domain randomisation: a new value per world seed
                v = stream(seed, "assumption", sec, key).uniform(*entry["range"])
            a[sec][key] = v
    playbooks = {p.stem: _read(p) for p in sorted((config_dir / "playbooks").glob("*.yaml"))}
    if w.get("exclude_emerging"):   # held-out scams for the discovery test (ml/PLAN.md section 7)
        playbooks = {k: v for k, v in playbooks.items() if not v.get("emerging")}
    return Config(
        seed=seed, users=int(w["users"]), days=int(w["days"]), end=datetime.fromisoformat(str(w["end"])),
        world=w["world"], victim_rate=float(w["victim_rate"][w["world"]]), randomise=randomise,
        users_per_locality=int(w["users_per_locality"]), localities_per_crew=int(w["localities_per_crew"]),
        a=a, a_meta=raw_a, playbooks=playbooks, lookalikes=_read(config_dir / "lookalikes.yaml"),
        demo=_read(config_dir / "scenarios" / "demo.yaml"), raw_world=w)
