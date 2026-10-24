"""Step 3: the investigator drafts a playbook card for a new cluster.

With Bedrock, an LLM agent explores the cluster through read-only tools (overview, cases, payees,
known playbooks, comparisons), tries matchers with `test_matcher` (code runs them over every
replayed payment) and submits a card. Code validates the card and backtests its matcher; a card
that fails the gates goes back to the agent to revise (twice), then is kept with its failures shown
to the human reviewers. Offline, a deterministic drafter builds the card from the cluster's tokens.
"""
from __future__ import annotations

import json
import re
import typing
from datetime import datetime, timezone

import numpy as np

from blue_team import config, engine_file, llm, matcher, playbook_db, tokens
from blue_team.evidence import Workspace
from schema.events import ReasonCode

REASON_CODES = sorted(c for c in typing.get_args(ReasonCode) if c != "ruko_unavailable")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
GENERIC_TOKENS = {"PAY", "NEW_PAYEE", "PAYEE_IN_RUN", "PAYEE_PERSON"}
MAX_GATE_RETRIES = 2

CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "snake_case name of the scam, e.g. relative_voice_clone"},
        "title": {"type": "string", "description": "one line a bank analyst understands"},
        "summary": {"type": "string", "description": "3-5 sentences: who is targeted, the story, how money moves"},
        "steps": {"type": "array", "items": {"type": "string"}, "description": "the scam step by step (2-8 steps)"},
        "signals": {"type": "array", "items": {"type": "string"}, "description": "tokens that mark it (from the evidence)"},
        "matcher": {"type": "object", "description": "the rule, in the fixed matcher format"},
        "reason_codes": {"type": "array", "items": {"type": "string", "enum": REASON_CODES}},
        "advice_en": {"type": "string", "description": "what to tell the user, at most 25 words"},
        "advice_hi": {"type": "string", "description": "the same advice in Hindi (Devanagari)"},
        "ai_powered": {"type": "object", "properties": {"likely": {"type": "boolean"}, "why": {"type": "string"}},
                       "required": ["likely", "why"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "evidence": {"type": "array", "items": {"type": "object", "properties": {
            "source": {"type": "string", "description": "the tool call it came from, e.g. 'get_case rep_001239', 'get_cluster_overview', 'test_matcher'"},
            "fact": {"type": "string", "description": "the fact, in one short sentence, as the tool returned it"}},
            "required": ["source", "fact"]},
                     "description": "3-8 facts this card rests on, each with the tool call it came from"},
    },
    "required": ["name", "title", "summary", "steps", "signals", "matcher", "reason_codes", "advice_en", "advice_hi",
                 "ai_powered", "confidence", "evidence"],
}

MATCHER_HELP = f"""Matcher format (JSON). A leaf: {{"feature": <field>, "op": <op>, "value": <value>}}.
Combine with {{"all": [...]}}, {{"any": [...]}}, {{"not": {{...}}}}. At most {matcher.MAX_LEAVES} leaves, depth {matcher.MAX_DEPTH}.
Shortcut (recommended): {{"token": "CALLER_UNKNOWN"}} uses that token's exact rule, e.g.
{{"all": [{{"token": "CALL_ON"}}, {{"token": "CALLER_UNKNOWN"}}, {{"token": "SAYS_FAMILY"}}]}}.
ops: is (true/false), eq, ne, in, not_in (list), >=, <=, >, < (numbers), is_null, not_null.
An unmeasured field (null) never satisfies a comparison.
Fields: {", ".join(sorted(matcher.FIELDS))}.
entry_method is typed|qr|contact|collect; payer_says is government|company|family|shop|investment|other;
lure_tag is arrest_threat|kyc|task_job|trading_tip|refund; payee_holder_type is person|merchant;
episode_state is 0 none, 1 watching, 2 active.
On a WhatsApp / VoIP call the phone cannot see the number, so caller_unknown is null, not true:
use the CALLER_UNKNOWN token, which covers both."""

TOKEN_GLOSSARY = "\n".join(f"- {name}: {matcher.describe(rule)}" for name, rule in tokens.TOKENS.items()) + \
    "\n- GAP_*: time between two payments of the case (under 10 min, under 1 h, under 1 day, over 1 day)"

SYSTEM = f"""You are the investigator on RUKO's blue team. RUKO is a UPI scam shield in India: at every
payment it scores signals from the phone and the bank and may pause the payment. You are given a
cluster of victim complaints (1930 / NCRP) about payments RUKO did not stop, or could not name,
and that match none of RUKO's known scam playbooks. Investigate it with the tools and draft a
playbook card so analysts can teach RUKO this scam.

Rules:
- Use only what the tools return. Never invent numbers, apps, companies, people or quotes.
- The server sees derived signals only (no SMS text, no audio, no contacts). Each payment is
  described by tokens:
{TOKEN_GLOSSARY}
- The matcher names the scam for future payments; it never blocks anything and never sets a tier.
  It must catch most of the cluster's cases (case recall >= {{min_recall}}), name almost no legit
  payments (<= {{max_legit}} per 1,000) and not overlap known playbooks (<= {{max_overlap}}). Always run
  test_matcher before submit_playbook. Prefer 2-4 robust conditions over many narrow ones.
- {MATCHER_HELP}
- If the evidence suggests AI tools (a voice that sounds like a relative, a chatbot agent, deepfake
  video), set ai_powered.likely and say which evidence; otherwise say it is not evident.
- advice_en: at most 25 words, calm, one concrete action. advice_hi: the same in Hindi (Devanagari).
- name: snake_case and descriptive of the scam (e.g. electricity_bill_disconnection), not a token list.
- evidence: list the 3-8 facts the card rests on, each with its source, the tool call it came from
  ("get_case rep_001239", "get_cluster_overview", "test_matcher"). Code checks you made those calls.
- This is fraud-prevention work for defenders: describe how the scam works factually so analysts
  can warn victims. Keep free text short; put your work into tool calls.

Work in this order: get_cluster_overview; get_case for 2-3 example cases; get_payee for the top
payee; list_playbooks and compare_with_playbook for the nearest one; test_matcher until the gates
pass; then submit_playbook."""


def _tools(ws: Workspace, cluster_id: str, state: dict) -> list[llm.Tool]:
    cid_only = {"type": "object", "properties": {}, "required": []}
    return [
        llm.Tool("get_cluster_overview", "Size, dates, amounts, distinctive tokens, typical case, payees, RUKO's response.",
                 cid_only, lambda i: ws.overview(cluster_id)),
        llm.Tool("get_case", "One complaint and its payments (tokens, amounts, entry, payer_says, RUKO's tier).",
                 {"type": "object", "properties": {"case_id": {"type": "string"}}, "required": ["case_id"]},
                 lambda i: ws.case(i["case_id"])),
        llm.Tool("get_payee", "What the bank, lists and payment graph show about one payee UPI ID.",
                 {"type": "object", "properties": {"upi_id": {"type": "string"}}, "required": ["upi_id"]},
                 lambda i: ws.payee(i["upi_id"])),
        llm.Tool("list_playbooks", "RUKO's known and approved playbooks: titles, summaries, steps, rules in words.",
                 cid_only, lambda i: {"playbooks": playbook_db.summaries(ws.playbooks)}),
        llm.Tool("compare_with_playbook", "How this cluster's tokens differ from the cases a known playbook names.",
                 {"type": "object", "properties": {"playbook": {"type": "string"}}, "required": ["playbook"]},
                 lambda i: ws.compare(cluster_id, i["playbook"])),
        llm.Tool("test_matcher", "Backtest a matcher over every replayed payment: cluster recall, legit payments named "
                 "per 1,000, overlap with known playbooks, gate failures.",
                 {"type": "object", "properties": {"matcher": {"type": "object"}}, "required": ["matcher"]},
                 lambda i: ws.test_matcher(i["matcher"], cluster_id)),
        llm.Tool("submit_playbook", "Submit the playbook card. Code validates it and backtests the matcher.",
                 CARD_SCHEMA, lambda i: _submit(ws, cluster_id, i, state)),
    ]


def task_for(ws: Workspace, cluster_id: str) -> str:
    c = ws.cluster_by_id[cluster_id]
    if c.kind == "misnamed":
        p = c.nearest_playbook
        return (f"Investigate cluster {cluster_id} ({len(c.case_ids)} complaints). RUKO interrupted these payments "
                f"and named them '{p}', yet the victims still paid and complained. Find out whether '{p}' is the "
                "right story. Draft the card for what these cases really are (if they really are "
                f"'{p}', say so in the summary and draft it for this subgroup anyway; the analyst decides). If approved, "
                f"its matcher runs just before '{p}', so it must pick out only this subgroup: test_matcher's "
                f"known_playbook_payments_also_matched counts the other '{p}' payments it would take. '{p}''s rule "
                "matching these payments is not evidence (that is how they were selected): compare the story "
                f"(payer_says, caller, remote control, entry, amounts) with '{p}''s summary via compare_with_playbook.")
    return f"Investigate cluster {cluster_id}. It has {len(c.case_ids)} complaints. Draft its playbook card."


def check_card(card: dict, existing: set[str]) -> list[str]:
    errs = []
    if not NAME_RE.match(str(card.get("name", ""))):
        errs.append("name must be snake_case, 3-41 characters, starting with a letter")
    elif card["name"] in existing:
        errs.append(f"name {card['name']!r} is already a playbook")
    errs += [f"matcher: {e}" for e in matcher.validate(card.get("matcher"))]
    bad = [c for c in card.get("reason_codes", []) if c not in REASON_CODES]
    if bad or not card.get("reason_codes"):
        errs.append(f"reason_codes must be 1+ of {REASON_CODES}" + (f" (bad: {bad})" if bad else ""))
    if not 2 <= len(card.get("steps", [])) <= 8:
        errs.append("steps: 2 to 8 steps")
    if len(str(card.get("advice_en", "")).split()) > 30:
        errs.append("advice_en: at most 25 words")
    if not DEVANAGARI.search(str(card.get("advice_hi", ""))):
        errs.append("advice_hi must be in Hindi (Devanagari script)")
    ev = card.get("evidence")
    if not isinstance(ev, list) or len(ev) < 2 or not all(isinstance(e, dict) and e.get("source") and e.get("fact") for e in ev):
        errs.append("evidence: at least 2 items, each {source: the tool call, fact: what it returned}")
    return errs


def _submit(ws: Workspace, cluster_id: str, card: dict, state: dict) -> dict:
    card["matcher"] = matcher.normalize(card.get("matcher"))
    errs = check_card(card, {pb.name for pb in ws.playbooks} | state["taken"])
    if errs:
        return {"accepted": False, "errors": errs}
    bt = ws.test_matcher(card["matcher"], cluster_id)
    state["last"] = (card, bt)
    if bt["gate_failures"] and state["gate_retries"] < MAX_GATE_RETRIES:
        state["gate_retries"] += 1
        return {"accepted": False, "backtest": bt,
                "errors": ["the matcher fails the gates; revise it with test_matcher and submit again"]}
    return {"accepted": True, "backtest": bt}


def check_sources(evidence: list[dict], transcript: list[dict]) -> list[dict]:
    """Mark each cited source `seen` if the agent really called that tool (with that argument, if given)."""
    calls = [(c["name"], json.dumps(c.get("input"), ensure_ascii=False)) for t in transcript for c in t.get("tool_calls", [])]
    out = []
    for e in evidence or []:
        src = str(e.get("source", "")).strip()
        name, _, arg = src.partition(" ")
        seen = any(n == name and (not arg or arg.strip("'\" ") in inp) for n, inp in calls)
        out.append({**e, "seen": seen})
    return out


def investigate(ws: Workspace, cluster_id: str, rt, model_id: str, taken: set[str], on_event=None) -> dict:
    """Run the LLM investigator; returns the draft (card + backtest + transcript)."""
    a, g = config.load()["agents"], config.load()["gates"]
    state = {"taken": taken, "last": None, "gate_retries": 0}
    system = SYSTEM.replace("{min_recall}", str(g["min_cluster_recall"])).replace(
        "{max_legit}", str(g["max_legit_per_1000"])).replace("{max_overlap}", str(g["max_known_overlap"]))
    task = task_for(ws, cluster_id)
    res = llm.run_agent(rt, model_id, system, task, _tools(ws, cluster_id, state), "submit_playbook",
                        a["investigator_max_turns"], on_event=on_event)
    card, bt = (res.final, state["last"][1]) if res.final else (state["last"] or (None, None))
    if card is None:
        card, bt = offline_card(ws, cluster_id, taken)
        how = f"offline (the {model_id} investigator submitted no valid card in {res.turns} turns)"
    elif bt and bt.get("gate_failures"):
        # Keep the model's story, but use the code-searched rule if it passes where the model's did not.
        rule = offline_card(ws, cluster_id, taken)[0]["matcher"]
        alt = ws.test_matcher(rule, cluster_id)
        if not alt["gate_failures"]:
            card = {**card, "matcher": matcher.normalize(rule),
                    "drafted_matcher": {"rule": card["matcher"], "gate_failures": bt["gate_failures"]}}
            bt = alt
            how = f"{model_id} (matcher: code search; the drafted one failed the gates)"
        else:
            how = model_id
    else:
        how = model_id
    if not how.startswith("offline"):
        card = {**card, "evidence": check_sources(card.get("evidence"), res.transcript)}
    return _draft(card, bt, cluster_id, how, res)


def offline_card(ws: Workspace, cluster_id: str, taken: set[str]) -> tuple[dict, dict]:
    """A deterministic card: a greedy rule from the cluster's distinctive tokens, template text."""
    ov = ws.overview(cluster_id)
    distinctive = [d["token"] for d in ov["distinctive_tokens"]
                   if d["token"] not in GENERIC_TOKENS and " " not in d["token"] and not d["token"].startswith("GAP_")]
    rule, bt = greedy_rule(ws, cluster_id, distinctive)
    words = [t.lower() for t in distinctive[:2]] or ["pattern"]
    name = "new_" + "_".join(words)[:30].strip("_")
    base, k = name, 2
    while name in taken or name in {pb.name for pb in ws.playbooks}:
        name, k = f"{base}_{k}", k + 1
    readable = ", ".join(t.lower().replace("_", " ") for t in distinctive[:5])
    card = {
        "name": name, "title": f"Unnamed pattern from {ov['cases']} complaints: {readable}",
        "summary": (f"{ov['cases']} complaints from {ov['users']} users describe payments RUKO did not stop. "
                    f"Most share: {readable}. Median payment Rs {ov['amount_inr']['median']:,.0f}; "
                    f"{ov['payees']['distinct']} payee accounts. Drafted without an LLM: an analyst should write the story."),
        "steps": [f"Complaint pattern: {readable}", "Victim pays a new payee the scammer chose"],
        "signals": distinctive[:6], "matcher": rule,
        "reason_codes": _reasons_for(rule),
        "advice_en": "Other people reported payments like this as scams. Stop, check with someone you trust, and call 1930 if unsure.",
        "advice_hi": "दूसरे लोगों ने ऐसे भुगतानों को धोखा बताया है। रुकें, किसी भरोसेमंद व्यक्ति से पूछें, और शक हो तो 1930 पर कॉल करें।",
        "ai_powered": {"likely": False, "why": "not assessed offline"}, "confidence": "low",
        "open_questions": ["What story did the scammer tell? (no LLM draft)"],
        "evidence": [{"source": "get_cluster_overview", "fact": f"{d['token']} in {d['share_of_cases']:.0%} of the cases "
                      f"({d['lift']}x {ov.get('lift_is_against', 'the baseline')})", "seen": True}
                     for d in ov["distinctive_tokens"][:4]]
                    + [{"source": "test_matcher", "fact": f"the rule names {bt['cluster_case_recall']:.0%} of the cases and "
                        f"{bt['legit_payments_named_per_1000']} legit payments per 1,000", "seen": True}],
    }
    return card, bt


def greedy_rule(ws: Workspace, cluster_id: str, candidates: list[str], max_terms: int = 3) -> tuple[dict, dict]:
    """A rule from the cluster's distinctive tokens: the AND of 1 to `max_terms` of them, or, when the
    best AND names fewer than gates.min_cluster_recall of the cases, an OR of two such ANDs (the
    second chosen over the cases the first missed). Ranked by: passes the legit and known-overlap
    gates, then reaches the recall gate with two families (so policy can raise it to a warning),
    then recall, two families, fewer terms, fewer legit payments. Exhaustive over at most 16
    candidates: a few thousand ANDs of precomputed masks."""
    from itertools import combinations
    g = config.load()["gates"]
    cands = [t for t in candidates if t in tokens.TOKENS][:16] or ["NEW_PAYEE"]
    hits = {t: np.array([matcher.matches(tokens.TOKENS[t], f) for f in ws.scored.feats]) for t in cands}
    case_rows = [ws.case_by_id.at[cid, "rows"] for cid in ws.cluster_by_id[cluster_id].case_ids]
    legit_w = ws.weight * ws.legit
    fam_of: dict[tuple, int] = {}

    def as_rule(combo: tuple) -> dict:
        return {"all": [tokens.TOKENS[t] for t in combo]} if len(combo) > 1 else tokens.TOKENS[combo[0]]

    def fams(combo: tuple) -> int:
        if combo not in fam_of:
            fam_of[combo] = len(engine_file.rule_families(as_rule(combo)))
        return fam_of[combo]

    def score(mask: np.ndarray, two_families: bool, terms: int) -> tuple:
        covered = np.array([mask[r].any() for r in case_rows])
        recall = float(covered.mean())
        legit = 1000 * legit_w[mask].sum() / max(legit_w.sum(), 1e-9)
        overlap = float(mask[ws.known_named].mean()) if ws.known_named.any() else 0.0
        excess = max(0.0, legit / g["max_legit_per_1000"] - 1) + max(0.0, overlap / g["max_known_overlap"] - 1)
        ok = recall >= g["min_cluster_recall"]
        return (excess == 0, ok and two_families, ok, two_families, recall - excess, -terms, -legit), covered

    combos = [c for k in range(1, max_terms + 1) for c in combinations(cands, k)]
    masks = {c: np.logical_and.reduce([hits[t] for t in c]) for c in combos}
    best = max(combos, key=lambda c: score(masks[c], fams(c) >= 2, len(c))[0])
    key, covered = score(masks[best], fams(best) >= 2, len(best))
    rule = as_rule(best)
    if not key[2] and not covered.all():           # below the recall gate: add a second branch
        def union_key(c: tuple) -> tuple:
            return score(masks[best] | masks[c], fams(best) >= 2 and fams(c) >= 2, len(best) + len(c))[0]
        second = max((c for c in combos if c != best), key=union_key, default=None)
        if second is not None and union_key(second) > key:
            rule = {"any": [as_rule(best), as_rule(second)]}
    return rule, ws.test_matcher(rule, cluster_id)


def _reasons_for(rule: dict) -> list[str]:
    from model.reasons import REASON
    codes = [REASON[f] for f in sorted(matcher.features_used(rule)) if f in REASON]
    return sorted(set(codes)) or ["R6_new_payee_typed"]


def _draft(card: dict, bt: dict, cluster_id: str, how: str, res: llm.AgentResult | None) -> dict:
    return {"card": card, "backtest": bt, "cluster_id": cluster_id, "drafted_by": how,
            "drafted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "gate_failures": bt.get("gate_failures", []) if bt else ["no backtest"],
            "transcript": res.transcript if res else [],
            "usage": {"turns": res.turns, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out} if res else None}


def investigate_offline(ws: Workspace, cluster_id: str, taken: set[str]) -> dict:
    card, bt = offline_card(ws, cluster_id, taken)
    return _draft(card, bt, cluster_id, "offline", None)

