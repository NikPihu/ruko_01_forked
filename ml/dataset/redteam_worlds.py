"""Red-team worlds for lgbm-0.3, built with data/sim_v2: Nikunj's 50 red-team playbooks split in two
halves BY PLAYBOOK, so the model is judged on scams it never trained on. Output: ml/data/worlds/<name>/

    PYTHONPATH=backend;ml;data python -m dataset.redteam_worlds rt_train rt_test

Each world has RUKO's six known scams (sim_v2's playbooks the engine names) plus one half of the red
team's, at a high victim rate so each red playbook has victims. The halves alternate over the sorted
playbook names; `split()` is the one place that decides which half a playbook is in.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1] / "data" / "worlds"
RED_DIR = Path(__file__).resolve().parents[2] / "red_team_blue_team" / "red_team" / "playbooks"

PRESETS: dict[str, dict] = {
    "rt_train": dict(half="train", users=3_000, days=30, seed=61, victim_rate=0.8, red_boost=2.0),
    "rt_test": dict(half="test", users=3_000, days=30, seed=62, victim_rate=0.8, red_boost=2.0),
}


def split(red_dir: Path = RED_DIR) -> dict[str, list[Path]]:
    """{'train': [...], 'test': [...]}: the red-team playbooks alternately, by sorted name."""
    files = sorted(red_dir.glob("*.yaml"), key=lambda p: yaml.safe_load(p.read_text(encoding="utf-8"))["name"])
    return {"train": files[0::2], "test": files[1::2]}


def build(name: str, log=print) -> Path:
    from api.playbooks import load as load_playbooks
    from sim_v2.core.config import load
    from sim_v2.export import write
    from sim_v2.run import build as run_build

    p = PRESETS[name]
    cfg = load(users=p["users"], days=p["days"], seed=p["seed"], world="train",
               victim_rate={"train": p["victim_rate"], "eval": 0.01})
    known = {n for n, _, _ in load_playbooks()[0]}
    cfg.playbooks = {k: v for k, v in cfg.playbooks.items() if k in known}
    red = {}
    for f in split()[p["half"]]:
        pb = yaml.safe_load(f.read_text(encoding="utf-8"))
        pb["weight"] = float(pb.get("weight", 0.07)) * p["red_boost"]
        pb["red_team"] = True
        red[pb["name"]] = pb
    cfg.playbooks.update(red)
    out = ROOT / name
    log(f"{name}: {p['users']:,} users x {p['days']} days, {len(red)} red-team playbooks ({p['half']} half) "
        f"+ {len(cfg.playbooks) - len(red)} known -> {out}")
    write(run_build(cfg, log=log), cfg, out)
    (out / "red_team.json").write_text(json.dumps({"half": p["half"], "red_team": sorted(red), **p}, indent=1), encoding="utf-8")
    return out


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("names", nargs="+", choices=sorted(PRESETS))
    for name in a.parse_args().names:
        t0 = time.perf_counter()
        build(name)
        print(f"  {name} in {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    main()
