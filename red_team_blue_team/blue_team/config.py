"""Paths and config.yaml for the blue team."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
PLAYBOOKS = HERE / "playbooks"          # the playbook database: known/, review/, approved/
RUNS = HERE / "runs"                    # one folder per run (git ignored)


@lru_cache(maxsize=1)
def load() -> dict:
    return yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
