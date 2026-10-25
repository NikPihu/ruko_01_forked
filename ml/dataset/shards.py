"""World shards for lgbm-0.3 (plan v3, step 4): about 200,000 simulated users in independent worlds,
each replayed into a training table. Output: ml/data/worlds/v3/<shard>/, ml/data/tables/v3/<shard>.parquet

    PYTHONPATH=backend;ml;data python -m dataset.shards status
    PYTHONPATH=backend;ml;data python -m dataset.shards build --set all --workers 4

Two simulators, so the model does not learn one generator's quirks:
- `sim`   (data/sim): RUKO's six known scams, the world lgbm-0.2 trained on;
- `v2`    (data/sim_v2): the six known scams plus one half of the attack playbooks
          (dataset/redteam_worlds.split), at a realistic victim rate.

Sets: `train` (32 shards, the attack playbooks' train half), `calib` (4, train half: thresholds, fusion,
calibration) and `test` (4: the known scams, and the attack playbooks' test half the model never sees).
Every shard has its own seed, so no user, mule or journey is shared. Resumable: a shard whose table
exists is skipped; one replay process per shard (about 12 minutes for a `sim` shard, more for `v2`).
Memory: a `v2` replay holds about 5 GB, a `sim` one about 2 GB, so at most V2_AT_ONCE `v2` shards
replay at the same time and the two kinds are interleaved.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ML = Path(__file__).resolve().parents[1]
REPO = ML.parent
WORLDS = ML / "data" / "worlds" / "v3"
TABLES = ML / "data" / "tables" / "v3"
LOGS = ML / "runs" / "shards"
USERS, DAYS = 5_000, 60
V2_AT_ONCE = 2
_V2_SLOTS = threading.BoundedSemaphore(V2_AT_ONCE)


def _shards() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(16):
        out[f"train_sim_{i:02d}"] = {"set": "train", "kind": "sim", "seed": 1001 + i}
        out[f"train_v2_{i:02d}"] = {"set": "train", "kind": "v2", "seed": 2001 + i, "half": "train"}
    for i in range(2):
        out[f"calib_sim_{i:02d}"] = {"set": "calib", "kind": "sim", "seed": 3001 + i}
        out[f"calib_v2_{i:02d}"] = {"set": "calib", "kind": "v2", "seed": 3101 + i, "half": "train"}
        out[f"test_sim_{i:02d}"] = {"set": "test", "kind": "sim", "seed": 4001 + i}
        out[f"test_v2_{i:02d}"] = {"set": "test", "kind": "v2", "seed": 4101 + i, "half": "test"}
    return out


SHARDS = _shards()
V2 = {"victim_rate": 0.25, "red_boost": 1.0}      # per 60 days; the attack playbooks at their own weights
SIM = {"scam_rate": 0.04}                         # as dataset.worlds `dev`


def build_world(name: str, log=print) -> Path:
    s, out = SHARDS[name], WORLDS / name
    if (out / "BUILT").exists():                 # written last: a half-written world is built again
        return out
    if s["kind"] == "sim":
        from sim.config import SimConfig
        from sim.generate import build_world as sim_build, write_world
        cfg = SimConfig(n_users=USERS, n_days=DAYS, scam_rate=SIM["scam_rate"], seed=s["seed"])
        write_world(sim_build(cfg), cfg, out)
    else:
        from api.playbooks import load as load_playbooks
        from sim_v2.core.config import load
        from sim_v2.export import write
        from sim_v2.run import build as run_build

        from dataset.redteam_worlds import split
        cfg = load(users=USERS, days=DAYS, seed=s["seed"], world="train",
                   victim_rate={"train": V2["victim_rate"], "eval": 0.01})
        known = {n for n, _, _ in load_playbooks()[0]}
        cfg.playbooks = {k: v for k, v in cfg.playbooks.items() if k in known}
        red = {}
        for f in split()[s["half"]]:
            pb = yaml.safe_load(f.read_text(encoding="utf-8"))
            pb["weight"] = float(pb.get("weight", 0.07)) * V2["red_boost"]
            pb["red_team"] = True
            red[pb["name"]] = pb
        cfg.playbooks.update(red)
        write(run_build(cfg, log=lambda *a: None), cfg, out)
        (out / "red_team.json").write_text(json.dumps({"half": s["half"], "red_team": sorted(red), **s}, indent=1),
                                           encoding="utf-8")
    (out / "BUILT").write_text(json.dumps(s), encoding="utf-8")
    log(f"{name}: world built")
    return out


def replay(name: str, log=print) -> Path:
    table = TABLES / f"{name}.parquet"
    if table.exists():
        return table
    with _V2_SLOTS if SHARDS[name]["kind"] == "v2" else _NO_LIMIT:
        return _replay(name, table, log)


class _NoLimit:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_NO_LIMIT = _NoLimit()


def _replay(name: str, table: Path, log) -> Path:
    world = build_world(name, log)
    TABLES.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": os.pathsep.join(str(REPO / p) for p in ("backend", "ml", "data"))}
    t0 = time.perf_counter()
    tmp = table.with_suffix(".partial.parquet")
    with open(LOGS / f"{name}.log", "w", encoding="utf-8") as fh:
        rc = subprocess.run([sys.executable, "-m", "dataset.replay", "--data", str(world), "--out", str(tmp)],
                            cwd=REPO, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    if rc:
        raise RuntimeError(f"{name}: replay failed (exit {rc}); see {LOGS / (name + '.log')}")
    tmp.replace(table)                         # only a finished table counts as done
    log(f"{name}: table in {time.perf_counter() - t0:.0f}s")
    return table


def status() -> dict[str, str]:
    return {n: "table" if (TABLES / f"{n}.parquet").exists() else "world" if (WORLDS / n / "BUILT").exists() else "-"
            for n in SHARDS}


def tables(which: str) -> list[Path]:
    """The finished tables of a set (train / calib / test), for model.train --table."""
    return [TABLES / f"{n}.parquet" for n, s in SHARDS.items() if s["set"] == which and (TABLES / f"{n}.parquet").exists()]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--set", default="all", choices=["all", "train", "calib", "test"])
    b.add_argument("--workers", type=int, default=4)
    sub.add_parser("status")
    a = p.parse_args()
    if a.cmd == "status":
        st = status()
        for k in ("table", "world", "-"):
            print(f"{k:6s} {sum(v == k for v in st.values())}")
        return
    # test and calib first: the model can be evaluated as soon as any training shards are done;
    # sim and v2 alternate, so the v2 limit does not leave workers idle
    order = sorted((n for n, s in SHARDS.items() if a.set in ("all", s["set"])),
                   key=lambda n: ({"test": 0, "calib": 1, "train": 2}[SHARDS[n]["set"]], n[-2:], SHARDS[n]["kind"]))
    t0 = time.perf_counter()

    def one(n):
        try:
            replay(n, log=lambda m: print(f"{time.strftime('%H:%M:%S')} {m}", flush=True))
        except Exception as e:  # noqa: BLE001 (one bad shard must not stop the rest)
            print(f"{time.strftime('%H:%M:%S')} {n}: FAILED {e}", flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(one, order))
    print(f"done in {(time.perf_counter() - t0) / 60:.0f} min; {status()}")


if __name__ == "__main__":
    main()
