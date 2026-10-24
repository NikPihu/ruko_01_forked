"""Build a world in which one playbook is the only scam running.

Nothing in data/sim_v2 is edited. We copy its config folder to a temp folder, drop the chosen
playbook in as the only one, and change a few numbers there (world size, how many users the crews
approach, and in "comply" mode the victim weights). sim_v2 then builds the world as usual.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "backend", ROOT / "ml", ROOT / "data"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SIM_V2_CONFIG = ROOT / "data" / "sim_v2" / "config"
LIBRARY = SIM_V2_CONFIG / "playbooks"


@dataclass
class Scenario:
    name: str
    playbook: dict
    world_dir: Path
    config_dir: Path
    tables: dict
    victims: list[str]          # user ids the playbook was run against
    journeys: list[str]


def load_playbook(ref: str | Path) -> tuple[str, dict]:
    """A path to a YAML file, or the name of one of sim_v2's playbooks."""
    path = Path(ref)
    if not path.exists():
        path = LIBRARY / f"{ref}.yaml"
    if not path.exists():
        names = ", ".join(sorted(p.stem for p in LIBRARY.glob("*.yaml")))
        raise SystemExit(f"No playbook at {ref}. Library: {names}")
    pb = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(pb, dict) or "steps" not in pb:
        raise SystemExit(f"{path} is not a playbook: it needs a 'steps' list "
                         "(see data/sim_v2/config/playbooks/README.md).")
    pb.setdefault("name", path.stem)
    pb.setdefault("weight", 1.0)
    pb.setdefault("targets", {})
    pb.setdefault("start_hours", [9, 21])
    pb.setdefault("confidence", "unknown")
    return path.stem, pb


def _victim_rate(victims: int, users: int, days: int) -> float:
    """sim_v2 reads victim_rate as 'share of users approached per 60 days', pro-rated to the run."""
    if users <= 0 or days <= 0:
        return 0.0
    return min(0.95, (victims / users) / (days / 60))


def _always_comply(assumptions: dict) -> dict:
    """Victim weights that make every step a 'yes', so the server is asked about every step.

    p_comply = logistic(base + ...), so a large base pins it at ~1 and the other terms stop mattering.
    """
    v = assumptions["victim"]
    v["base"]["v"] = {k: 12.0 for k in v["base"]["v"]}
    for key in ("sunk_cost", "doubt_per_refusal", "big_ask"):
        v[key]["v"] = 0.0
    v["delay_share"]["v"] = 0.0
    return assumptions


def build(playbook_ref: str | Path, cfg: dict, out: Path | None = None, log=print) -> Scenario:
    """Build the world and return it with the list of users the playbook was run against."""
    from sim_v2.core.config import load as load_config
    from sim_v2.export import write
    from sim_v2.run import build as build_world

    name, pb = load_playbook(playbook_ref)
    w, s = cfg["world"], cfg["scenario"]
    tmp = Path(tempfile.mkdtemp(prefix=f"pbrun_{name}_"))
    config_dir = tmp / "config"
    shutil.copytree(SIM_V2_CONFIG, config_dir)

    # Only this playbook runs, so every journey in the world is the one under test.
    for old in (config_dir / "playbooks").glob("*.yaml"):
        old.unlink()
    (config_dir / "playbooks" / f"{name}.yaml").write_text(yaml.safe_dump(pb, sort_keys=False), encoding="utf-8")

    # sim_v2 always builds its three scripted demo journeys, and looks up a crew for them by
    # playbook name. Point that at the playbook under test and ask for none of them, so the world
    # holds only the journeys this run is about.
    demo = yaml.safe_load((SIM_V2_CONFIG / "scenarios" / "demo.yaml").read_text(encoding="utf-8"))
    demo["demo_journeys"] = {**demo["demo_journeys"], "playbook": name, "count": 0}
    (config_dir / "scenarios" / "demo.yaml").write_text(yaml.safe_dump(demo, sort_keys=False), encoding="utf-8")

    rate = _victim_rate(s["victims"], w["users"], w["days"])
    world_yaml = yaml.safe_load((SIM_V2_CONFIG / "world.yaml").read_text(encoding="utf-8"))
    world_yaml.update({"seed": w["seed"], "users": w["users"], "days": w["days"], "world": "train",
                       "victim_rate": {"train": rate, "eval": rate}, "exclude_emerging": False})
    (config_dir / "world.yaml").write_text(yaml.safe_dump(world_yaml, sort_keys=False), encoding="utf-8")

    if s["victims_mode"] == "comply":
        a = yaml.safe_load((SIM_V2_CONFIG / "assumptions.yaml").read_text(encoding="utf-8"))
        (config_dir / "assumptions.yaml").write_text(
            yaml.safe_dump(_always_comply(a), sort_keys=False), encoding="utf-8")

    sim_cfg = load_config(config_dir)
    log(f"  world: {sim_cfg.users} users x {sim_cfg.days} days, playbook '{name}', "
        f"victims_mode={s['victims_mode']}")
    tables = build_world(sim_cfg, log=lambda *_: None)

    world_dir = Path(out) if out else tmp / "world"
    write(tables, sim_cfg, world_dir)

    j = tables["journeys"]
    real = j[~j.is_demo] if "is_demo" in j else j
    real = real[real.playbook == name]
    log(f"  scam journeys: {len(real)} ({int((real.n_payments > 0).sum())} reached a payment)")
    return Scenario(name=name, playbook=pb, world_dir=world_dir, config_dir=config_dir, tables=tables,
                    victims=real.user_id.tolist(), journeys=real.journey_id.tolist())
