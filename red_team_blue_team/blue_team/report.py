"""A run's report.md: what broke, what clustered, what the agents drafted, what humans must decide."""
from __future__ import annotations

from pathlib import Path

from blue_team.evidence import Workspace


def markdown(summary: dict, ws: Workspace, out: Path) -> str:
    st = summary["status"]
    lines = [
        f"# Blue team run {summary['run_id']}",
        "",
        f"Scorer `{summary['scorer']}`, agents `{summary['agents']}`, world `{summary['world']}`.",
        "",
        "## Where the shield broke",
        f"{summary['cases']} complaint cases: **{st.get('missed', 0)} missed** (no payment interrupted), "
        f"**{st.get('unnamed', 0)} unnamed** (interrupted, scam not named), {st.get('held', 0)} held.",
        "",
        "## Clusters (HDBSCAN over missed + unnamed cases)",
        "| cluster | kind | cases | nearest known playbook | similarity | named share | top tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in summary["clusters"]:
        toks = ", ".join(t for t, _ in c["top_tokens"][:4])
        lines.append(f"| {c['cluster_id']} | {c['kind']} | {c['cases']} | {c['nearest']} | {c['similarity']} | "
                     f"{c['named_share']} | {toks} |")
    lines += ["", f"{summary['noise']} breach cases fit no cluster (one-offs, kept for the next run).", ""]
    lines += ["## Candidates for the playbook database", ""]
    if not summary["candidates"]:
        lines.append("No new cluster this run.")
    for cand in summary["candidates"]:
        card = _card(out, cand)
        bt = card["draft"]["backtest"] or {}
        a = card["analyst"]
        c = card["draft"]["card"]
        lines += [
            f"### {cand['name']} ({cand['cluster_id']}, {cand['cases']} cases)",
            f"**{c['title']}**",
            "",
            c["summary"],
            "",
            "Steps: " + " → ".join(c["steps"]),
            "",
            f"- Matcher: `{bt.get('rule_in_words')}`",
            f"- Backtest: case recall {bt.get('cluster_case_recall')}, legit payments named per 1,000 "
            f"{bt.get('legit_payments_named_per_1000')}, overlap with known playbooks {bt.get('known_playbook_payments_also_matched')}",
            f"- Gates: {'pass' if not cand['gate_failures'] else '; '.join(cand['gate_failures'])}",
            f"- AI-powered: {c.get('ai_powered')}",
            f"- Advice: {c['advice_en']} / {c['advice_hi']}",
            f"- Drafted by `{cand['drafted_by']}`; analyst agent (`{a.get('reviewed_by')}`): **{a['verdict']}**"
            + (f" (nearest {a.get('nearest_playbook')})" if a.get("nearest_playbook") else ""),
            f"  - {a.get('rationale', '')}",
            "",
            f"Decide: `python -m blue_team approve {cand['name']} --analyst <you>` "
            f"or `python -m blue_team reject {cand['name']} --analyst <you> --note \"why\"`",
            "",
        ]
    return "\n".join(lines) + "\n"


def _card(out: Path, cand: dict) -> dict:
    import json
    p = out / "candidates" / f"{cand['cluster_id']}_{cand['name']}.json"
    return json.loads(p.read_text(encoding="utf-8"))
