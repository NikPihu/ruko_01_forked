"""The blue team's inbox: what the attack runner (synthetic_playbook/interface_script) hands over.

His runner plays one playbook against the real RUKO engine and judges each reply by its threat
score. Its `blue_team` sink (interface_script/sinks.py) calls `receive()` after every run:

- every verdict lands in inbox/verdicts/<playbook>.json (so the console can show what was tried);
- a **breakthrough** (most of the playbook's scam payments called normal) also lands its playbook
  in inbox/breakthroughs/<playbook>.yaml. Those are what the blue team must learn to name: the
  console builds one attack world from them all (many scams at once, as in real life), replays
  it, and the blue team works from the complaints.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from blue_team import config

INBOX = config.HERE / "inbox"


def receive(v, sc, df, out: Path, log=print, inbox: Path | None = None) -> None:
    box = inbox or INBOX
    (box / "verdicts").mkdir(parents=True, exist_ok=True)
    rec = {**v.summary(), "runner_out": str(Path(out).resolve()), "victims": len(getattr(sc, "victims", []) or []),
           "received": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (box / "verdicts" / f"{v.playbook}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    bt = box / "breakthroughs" / f"{v.playbook}.yaml"
    if v.breakthrough:
        bt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(Path(out) / "playbook.yaml", bt)
        log(f"  blue team inbox: breakthrough '{v.playbook}' queued ({v.scam_missed}/{v.scam_judged} called normal)")
    elif bt.exists():          # it no longer gets through (the engine improved): not the blue team's problem now
        bt.unlink()


def verdicts(inbox: Path | None = None) -> dict[str, dict]:
    d = (inbox or INBOX) / "verdicts"
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))} if d.exists() else {}


def breakthroughs(inbox: Path | None = None) -> list[Path]:
    d = (inbox or INBOX) / "breakthroughs"
    return sorted(d.glob("*.yaml")) if d.exists() else []
