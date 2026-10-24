"""Where a finished run is sent.

Each sink is a function `(verdict, scenario, results_df, out_dir) -> None`. Add one to SINKS and it
runs after every run; nothing else changes. The blue team is a sink: when it is ready, add
`blue_team(...)` here (post to its endpoint, or write into its queue folder) and it will receive
every breakthrough automatically.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path


def handoff_folder(v, sc, df, out: Path, log=print) -> None:
    """A breakthrough is written to out/handoff/ : the playbook, the missed payments, the verdict.

    This is the packet the blue team reads (cluster the missed payments, decide if the pattern is
    new, then a human reviews it).
    """
    if not v.breakthrough:
        return
    h = out / "handoff"
    h.mkdir(exist_ok=True)
    (h / "verdict.json").write_text(json.dumps(v.summary(), indent=2), encoding="utf-8")
    shutil.copy(out / "playbook.yaml", h / "playbook.yaml")
    missed = df[(df.judged) & (df.is_scam) & (df.called_normal == True)]  # noqa: E712 - pandas mask
    missed.to_csv(h / "missed_payments.csv", index=False)
    (h / "README.txt").write_text(
        f"Playbook '{v.playbook}' got past the server ({v.scorer}).\n"
        f"{v.scam_missed} of {v.scam_judged} scam payments came back with a threat score of "
        f"{v.normal_max_score} or less, i.e. treated as normal.\n\n"
        "playbook.yaml        the scenario that was run\n"
        "missed_payments.csv  the payments the server called normal (one row per payment)\n"
        "verdict.json         the counts behind this\n", encoding="utf-8")
    log(f"  handoff written: {h}")


def blue_team(v, sc, df, out: Path, log=print) -> None:
    """The blue team's inbox (red_team_blue_team/blue_team/inbox.py): every verdict, and the playbook
    of every breakthrough. Skipped quietly when the blue team is not on PYTHONPATH."""
    try:
        from blue_team import inbox
    except ImportError:
        return
    inbox.receive(v, sc, df, out, log=log)


SINKS = [handoff_folder, blue_team]


def emit(v, sc, df, out: Path, log=print) -> None:
    for sink in SINKS:
        sink(v, sc, df, out, log=log)
