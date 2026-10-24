"""Run a scam playbook against the RUKO server and see whether it got through.

    python -m interface_script run  --playbook task_job
    python -m interface_script run  --playbook path/to/mine.yaml --victims 30 --server local
    python -m interface_script run-all                       # every playbook in sim_v2's library
    python -m interface_script show  <run-dir>               # the summary of a finished run
    python -m interface_script trace <run-dir> --journey j_000123
    python -m interface_script playbooks                     # what is in the library

Run from the repo root with PYTHONPATH=backend;ml;data (PowerShell) or backend:ml:data.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from interface_script import scenario  # noqa: E402  (after sys.path)

CONFIG = HERE / "config" / "runner.yaml"
DEFAULT_OUT = Path("synthetic_playbook/interface_script_out")


def load_config(a) -> dict:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    for key, section, name in (("normal_max_score", "judge", "normal_max_score"),
                               ("breakthrough_share", "judge", "breakthrough_share"),
                               ("victims", "scenario", "victims"),
                               ("victims_mode", "scenario", "victims_mode"),
                               ("normal_sample", "scenario", "normal_sample"),
                               ("users", "world", "users"), ("days", "world", "days"),
                               ("seed", "world", "seed"), ("server", "server", "target"),
                               ("scorer", "server", "scorer")):
        v = getattr(a, key, None)
        if v is not None:
            cfg[section][name] = v
    cfg["server"].setdefault("scorer", "ml")
    return cfg


def cmd_run(a) -> None:
    from interface_script.run import run

    cfg = load_config(a)
    out = a.out or DEFAULT_OUT / Path(str(a.playbook)).stem
    v = run(a.playbook, cfg, Path(out))
    sys.exit(0 if not a.fail_on_breakthrough or not v.breakthrough else 2)


def discover(folder: Path) -> list[Path]:
    """Every playbook file in a folder, in name order. Add a playbook = drop a YAML in the folder."""
    folder = Path(folder)
    if not folder.is_dir():
        sys.exit(f"No folder at {folder}.")
    files = sorted({*folder.glob("*.yaml"), *folder.glob("*.yml")}, key=lambda p: p.name)
    if not files:
        sys.exit(f"No .yaml / .yml playbooks in {folder}.")
    return files


def cmd_run_all(a) -> None:
    from interface_script.run import run

    cfg = load_config(a)
    folder = Path(a.playbooks) if a.playbooks else scenario.LIBRARY
    base = Path(a.out or DEFAULT_OUT / "all")
    files = discover(folder)
    print(f"{len(files)} playbooks in {folder}")
    rows = []
    for i, path in enumerate(files, 1):
        print(f"\n=== [{i}/{len(files)}] {path.stem}")
        rows.append(run(path, cfg, base / path.stem).summary())
    df = pd.DataFrame(rows).sort_values("miss_rate", ascending=False)
    base.mkdir(parents=True, exist_ok=True)
    df.to_csv(base / "all_playbooks.csv", index=False)
    cols = ["playbook", "scam_payments_judged", "scam_called_normal", "miss_rate",
            "false_alarm_rate", "breakthrough"]
    print(f"\n=== every playbook (threat score <= {cfg['judge']['normal_max_score']} is 'normal')")
    print(df[cols].to_string(index=False))
    print(f"\nbreakthroughs: {int(df.breakthrough.sum())} of {len(df)}   ->  {base / 'all_playbooks.csv'}")


def cmd_show(a) -> None:
    d = Path(a.run_dir)
    f = d / "summary.txt"
    if not f.exists():
        sys.exit(f"No run at {d} (expected summary.txt).")
    print(f.read_text(encoding="utf-8"))
    res = d / "results.csv"
    if res.exists():
        df = pd.read_csv(res)
        j = df[df.judged & df.is_scam]
        if len(j):
            print("scam payments by step of the journey:")
            j = j.assign(step=j.journey_pay_index.astype("Int64"))
            g = j.groupby("step").agg(payments=("threat_score", "size"),
                                      median_score=("threat_score", "median"),
                                      called_normal=("called_normal", "sum"))
            g["called_normal"] = g.called_normal.astype(int)
            print(g.to_string())
            print("\n(step 0 is the journey's first payment)")


def cmd_trace(a) -> None:
    d = Path(a.run_dir)
    df = pd.read_csv(d / "results.csv")
    rows = df[df.journey_id == a.journey] if a.journey else df[df.is_scam & df.judged]
    if rows.empty:
        ids = df[df.is_scam].journey_id.dropna().unique()[:8]
        sys.exit(f"Nothing for {a.journey!r}. Journeys here: {', '.join(map(str, ids))}")
    for _, r in rows.sort_values("ts").iterrows():
        normal = "NORMAL" if r.called_normal else ("fail-open" if r.get("fail_open") else "flagged")
        step = "-" if pd.isna(r.journey_pay_index) else f"{int(r.journey_pay_index)}"
        score = "  -" if pd.isna(r.threat_score) else f"{int(r.threat_score):>3}"
        reasons = "" if (not isinstance(r.reasons, str)) else r.reasons
        print(f"{str(r.ts)[:16]}  step {step:<2} Rs {r.amount_inr:>10,.0f}  "
              f"score {score}  {str(r.tier):<2}  {normal:9}  {reasons}")


def cmd_playbooks(a) -> None:
    for p in sorted(scenario.LIBRARY.glob("*.yaml")):
        pb = yaml.safe_load(p.read_text(encoding="utf-8"))
        print(f"{p.stem:<28} {len(pb['steps'])} steps   {pb.get('title', '')[:70]}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m interface_script", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--out", type=Path)
        p.add_argument("--server", help="'local' or a URL like http://127.0.0.1:8000")
        p.add_argument("--scorer", choices=["ml", "rules"], help="which scorer the local engine runs")
        p.add_argument("--victims", type=int)
        p.add_argument("--victims-mode", choices=["comply", "model"], dest="victims_mode")
        p.add_argument("--normal-sample", type=float, dest="normal_sample")
        p.add_argument("--users", type=int)
        p.add_argument("--days", type=int)
        p.add_argument("--seed", type=int)
        p.add_argument("--normal-max-score", type=int, dest="normal_max_score",
                       help="a threat score at or below this means the server called it normal")
        p.add_argument("--breakthrough-share", type=float, dest="breakthrough_share",
                       help="share of scam payments called normal that makes it a breakthrough")

    r = sub.add_parser("run")
    r.add_argument("--playbook", required=True, help="a YAML path, or a name from the library")
    r.add_argument("--fail-on-breakthrough", action="store_true", help="exit 2 on a breakthrough (for CI)")
    common(r)
    ra = sub.add_parser("run-all")
    ra.add_argument("--playbooks", type=Path,
                    help="a folder of playbook YAMLs (default: data/sim_v2/config/playbooks)")
    common(ra)
    s = sub.add_parser("show")
    s.add_argument("run_dir")
    t = sub.add_parser("trace")
    t.add_argument("run_dir")
    t.add_argument("--journey")
    sub.add_parser("playbooks")

    a = ap.parse_args()
    {"run": cmd_run, "run-all": cmd_run_all, "show": cmd_show, "trace": cmd_trace,
     "playbooks": cmd_playbooks}[a.cmd](a)


if __name__ == "__main__":
    main()
