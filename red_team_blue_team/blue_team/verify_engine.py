"""The attack runner against the real engine, for verify.py's live check. Used as

    python -m blue_team.verify_engine run --playbook <yaml> --out <dir> --seed <n>

with environment variables choosing what is previewed (nothing is written to backend/ or data/):

    BLUE_VERIFY_CARD=<card yaml>   name payments with the engine's playbooks plus this card's rule, in the
                                   blue-team matcher (what the engine would do once its playbook format
                                   can express the rule: '>=', '<', the request's entry method)
    BLUE_VERIFY_CONTRACT=open      let threat.fraud_type carry any name (the contract lists six; with a
                                   new name the real engine fails open, backend/api/main.py threat_of)

The runner's blue-team sink is always removed: a verification never writes the red-team inbox. Every
payment's internal playbook name is written to <out>/named.jsonl (the reply shows it only at T1+).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import yaml


def _drop_blue_team_sink() -> None:
    from interface_script import sinks
    sinks.SINKS[:] = [s for s in sinks.SINKS if getattr(s, "__name__", "") != "blue_team"]


def _open_contract() -> None:
    from schema import events
    events.Threat.model_fields["fraud_type"].annotation = Optional[str]
    events.Threat.model_rebuild(force=True)
    events.DecideResponse.model_rebuild(force=True)


def _namer_hook(card_path: str | None, record: Path | None) -> None:
    """Wrap the engine's namer. With a card: known playbooks, then this card (by its approved priority),
    in the blue-team matcher, which also reads the request's entry method and payer_says. With
    `record`: write every payment's internal name to named.jsonl, because the engine shows the name
    only at T1+ (backend/api/main.py), so a reply alone cannot say what it named a T0 payment."""
    import json

    import api.main as engine
    import api.rule_scorer as rules

    name_engine = rules._playbook
    if card_path:
        from blue_team import verify
        card = yaml.safe_load(open(card_path, encoding="utf-8"))
        name_card = verify.namer(card, None)
    request: dict = {}
    build = engine.build_features
    fh = open(record, "a", encoding="utf-8") if record else None

    def build_features(req, *a, **k):
        request.clear()
        request.update(request_id=req.request_id, entry_method=req.entry_method, payer_says=req.payer_says)
        return build(req, *a, **k)

    def playbook(f: dict):
        if card_path:
            name = name_card({**f, "entry_method": request.get("entry_method"), "payer_says": request.get("payer_says")})
        else:
            name = name_engine(f)
        if fh and request.get("request_id"):
            fh.write(json.dumps({"request_id": request["request_id"], "named": name}) + "\n")
            fh.flush()
        return name

    engine.build_features = build_features
    rules._playbook = playbook
    try:
        import model.predict as predict
        predict._playbook = playbook
    except ImportError:
        pass


def _out_dir(argv: list[str]) -> Path | None:
    return Path(argv[argv.index("--out") + 1]) if "--out" in argv else None


def main() -> None:
    _drop_blue_team_sink()
    if os.environ.get("BLUE_VERIFY_CONTRACT") == "open":
        _open_contract()
    out = _out_dir(sys.argv)
    if out:
        out.mkdir(parents=True, exist_ok=True)
        (out / "named.jsonl").write_text("", encoding="utf-8")
    _namer_hook(os.environ.get("BLUE_VERIFY_CARD"), out / "named.jsonl" if out else None)
    from interface_script.__main__ import main as runner_main
    sys.argv = ["interface_script", *sys.argv[1:]]
    runner_main()


if __name__ == "__main__":
    main()
