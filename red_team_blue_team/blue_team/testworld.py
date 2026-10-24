"""Build a world with enough breaches to test the blue team, from sim_v2's own config (no edits there).

    PYTHONPATH=backend;ml;data;red_team_blue_team python -m blue_team.testworld --out data/sim_v2_out/breach

sim_v2 marks the scams RUKO has never seen as `emerging` (collect_request, electricity_disconnection,
loan_fee, lottery_prize, marketplace_buyer, relative_emergency). In a normal train world they are rare
(2 to 6 journeys in 3,000 users x 30 days), too few to cluster. This world approaches more users and
makes the emerging scams `--emerging-boost` times more likely, so each forms a group the blue team
can find. Everything else (victim decisions, mules, report lags) is sim_v2 unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def build(out: Path, users: int, days: int, seed: int, victim_rate: float, emerging_boost: float) -> None:
    from sim_v2.core.config import load
    from sim_v2.export import write
    from sim_v2.run import build as run_build

    cfg = load(users=users, days=days, seed=seed, world="train", victim_rate={"train": victim_rate, "eval": 0.01})
    for pb in cfg.playbooks.values():
        if pb.get("emerging"):
            pb["weight"] = float(pb.get("weight", 0.05)) * emerging_boost
    emerging = sorted(k for k, v in cfg.playbooks.items() if v.get("emerging"))
    print(f"breach test world: {users:,} users x {days} days, victim rate {victim_rate}, "
          f"emerging x{emerging_boost} ({', '.join(emerging)}) -> {out}")
    write(run_build(cfg), cfg, out)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=Path("data/sim_v2_out/breach"))
    p.add_argument("--users", type=int, default=3000)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--seed", type=int, default=21)
    p.add_argument("--victim-rate", type=float, default=0.5, help="share approached per 60 days (train default 0.08)")
    p.add_argument("--emerging-boost", type=float, default=4.0)
    p.add_argument("--red-team", action="store_true",
                   help="attack with red_team/playbooks (Nikunj's 50) instead of sim_v2's own emerging scams")
    p.add_argument("--red-boost", type=float, default=2.0, help="red-team playbook weights x this")
    p.add_argument("--red-dir", type=Path, default=None,
                   help="playbooks to attack with (default red_team/playbooks; the console passes the inbox's breakthroughs)")
    a = p.parse_args()
    if a.red_team:
        from blue_team import redteam
        redteam.build_world(a.out, a.users, a.days, a.seed, a.victim_rate, a.red_boost,
                            red_dir=a.red_dir or redteam.RED_DIR)
    else:
        build(a.out, a.users, a.days, a.seed, a.victim_rate, a.emerging_boost)


if __name__ == "__main__":
    main()
