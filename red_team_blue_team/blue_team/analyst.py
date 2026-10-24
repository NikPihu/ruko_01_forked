"""Step 4: the analyst reviews the investigator's draft, independently.

Verdicts: new_scam | variant_of_known (same mechanism as a known playbook; e.g. the phone missed the
lure, so the known matcher could not fire) | lookalike_not_scam (honest behaviour that resembles a
scam) | insufficient_evidence. The verdict is advice for the two human analysts; it approves
nothing. With Bedrock it is a second LLM agent with the same read-only tools and a skeptical brief;
offline, fixed rules on the backtest and the token profiles.
"""
from __future__ import annotations

from blue_team import cluster, config, llm, playbook_db
from blue_team.evidence import Workspace

VERDICTS = ["new_scam", "variant_of_known", "lookalike_not_scam", "insufficient_evidence"]
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": VERDICTS},
        "nearest_playbook": {"type": "string", "description": "for variant_of_known: the known playbook; else the closest one"},
        "rationale": {"type": "string", "description": "3-6 sentences citing the evidence you checked"},
        "required_changes": {"type": "array", "items": {"type": "string"},
                             "description": "what must change in the card before humans approve it"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "evidence": {"type": "array", "items": {"type": "object", "properties": {
            "source": {"type": "string", "description": "the tool call it came from, e.g. 'get_case rep_001239', 'get_cluster_overview', 'test_matcher'"},
            "fact": {"type": "string", "description": "the fact, in one short sentence, as the tool returned it"}},
            "required": ["source", "fact"]},
                     "description": "the 2-6 facts your verdict rests on, each with the tool call it came from"},
    },
    "required": ["verdict", "rationale", "confidence", "evidence"],
}

SYSTEM = """You are the analyst on RUKO's blue team: a skeptical second reviewer. An investigator
drafted a playbook card for a cluster of victim complaints that RUKO's shield did not stop. Decide:
- new_scam: a mechanism none of the known playbooks describes;
- variant_of_known: the same mechanism as a known playbook (for example the phone did not see the
  lure SMS, so the known rule could not fire). Then the right fix is the known playbook, not a new one;
- lookalike_not_scam: honest everyday behaviour (the matcher would name many legit payments);
- insufficient_evidence: too few or too mixed cases to say.
A missing lure is not evidence of a new scam. The phone often does not see the lure SMS (SMS checks
off, the message came on WhatsApp or Telegram, or the classifier did not know it) and the episode
watcher may be off, so a known scam whose lure was missed is exactly what reaches this queue as
"unnamed". Judge by the signals that remain: for example sideload + accessibility is fake_kyc_apk,
payer says "investment" is trading_group, remote control + a company story on an outgoing or unknown
call is fake_customer_care, repeated deposits to new payees after small credits is task_job.
get_candidate gives signal_similarity_lures_ignored to every known playbook (0-1, from the cases
that playbook names, lure and episode tokens left out, rare tokens weighted up); 0.8 or more
strongly suggests variant_of_known. "unknown" means there was nothing to compare with, not that the
cluster is different: then judge by the mechanism alone. A new_scam needs a mechanism no known
playbook describes.
If get_cluster_overview says ruko_named_it = X, the cluster is a *misnamed?* group: RUKO interrupted
these payments and named them X, yet the victims still paid and complained. Then decide whether X
is right: variant_of_known with nearest_playbook X means correctly named (no new playbook needed);
variant_of_known with another playbook means misnamed as X but really that one; new_scam means
misnamed and a scam no playbook describes. Similarities for a misnamed group are against X's
*other* complaints.
For a misnamed group, the fact that X's rule names these payments is not evidence: that is how
they were selected. Decide by the story. Compare what the payer said (payer_says), who called and
how (VoIP, unknown, listed, outgoing), remote control or screen sharing, how the payee was entered
(typed, QR, collect), amounts and timing with X's summary and steps (compare_with_playbook returns
them, and X's *other* complaints). Example: X = digital_arrest is an "officer" threatening arrest,
usually with remote control and a "government" payment; a group where the payer says "family",
with no remote control, is a different story even if RUKO's digital_arrest rule fired.
Check the investigator's claims against the cases yourself; run test_matcher if a number looks off;
compare with the nearest known playbooks. Do not invent evidence: list the 2-6 facts your verdict
rests on in `evidence`, each with the tool call it came from (code checks you made those calls).
Your verdict is advice to two human analysts, who decide. Finish by calling submit_review."""


def _tools(ws: Workspace, cluster_id: str, draft: dict) -> list[llm.Tool]:
    empty = {"type": "object", "properties": {}, "required": []}
    known = {pb.name for pb in ws.playbooks}

    def submit(i: dict) -> dict:
        if i.get("verdict") not in VERDICTS:
            return {"accepted": False, "errors": [f"verdict must be one of {VERDICTS}"]}
        if i["verdict"] == "variant_of_known" and i.get("nearest_playbook") not in known:
            return {"accepted": False, "errors": [f"variant_of_known needs nearest_playbook, one of {sorted(known)}"]}
        ev = i.get("evidence")
        if not isinstance(ev, list) or not ev or not all(isinstance(e, dict) and e.get("source") and e.get("fact") for e in ev):
            return {"accepted": False, "errors": ["evidence: at least 1 item, each {source: the tool call, fact: what it returned}"]}
        return {"accepted": True}

    return [
        llm.Tool("get_candidate", "The investigator's draft card, the code backtest of its matcher, and the cluster's "
                 "signal similarity to every known playbook with lures ignored.", empty,
                 lambda i: {"card": draft["card"], "backtest": draft["backtest"], "gate_failures": draft["gate_failures"],
                            "signal_similarity_lures_ignored": similarities(ws, cluster_id)}),
        llm.Tool("get_cluster_overview", "Size, dates, amounts, distinctive tokens, payees, RUKO's response.", empty,
                 lambda i: ws.overview(cluster_id)),
        llm.Tool("get_case", "One complaint and its payments.",
                 {"type": "object", "properties": {"case_id": {"type": "string"}}, "required": ["case_id"]},
                 lambda i: ws.case(i["case_id"])),
        llm.Tool("list_playbooks", "Known and approved playbooks.", empty,
                 lambda i: {"playbooks": playbook_db.summaries(ws.playbooks)}),
        llm.Tool("compare_with_playbook", "How this cluster differs from the cases a known playbook names.",
                 {"type": "object", "properties": {"playbook": {"type": "string"}}, "required": ["playbook"]},
                 lambda i: ws.compare(cluster_id, i["playbook"])),
        llm.Tool("test_matcher", "Backtest any matcher over every replayed payment.",
                 {"type": "object", "properties": {"matcher": {"type": "object"}}, "required": ["matcher"]},
                 lambda i: ws.test_matcher(i["matcher"], cluster_id)),
        llm.Tool("submit_review", "Submit your verdict.", REVIEW_SCHEMA, submit),
    ]


def review(ws: Workspace, cluster_id: str, draft: dict, rt, model_id: str, on_event=None) -> dict:
    a = config.load()["agents"]
    task = f"Review the draft playbook '{draft['card']['name']}' for cluster {cluster_id}."
    res = llm.run_agent(rt, model_id, SYSTEM, task, _tools(ws, cluster_id, draft), "submit_review", a["analyst_max_turns"],
                        on_event=on_event)
    if res.final is None:
        out = review_offline(ws, cluster_id, draft)
        out["reviewed_by"] = f"offline (the {model_id} analyst gave no verdict in {res.turns} turns)"
    else:
        from blue_team.investigator import check_sources
        out = {**res.final, "reviewed_by": model_id, "evidence": check_sources(res.final.get("evidence"), res.transcript)}
    out["transcript"] = res.transcript
    out["usage"] = {"turns": res.turns, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out}
    return out


MIN_REFERENCE_CASES = 3


def similarities(ws: Workspace, cluster_id: str) -> dict[str, float | str]:
    """Lure-ignored similarity per known playbook; 'unknown' when too few complaints were named by it to compare."""
    out: dict[str, float | str] = {}
    for pb in ws.playbooks:
        if pb.status != "known":
            continue
        own = set(ws.cluster_by_id[cluster_id].case_ids)
        n = sum(1 for i in ws.cases.loc[ws.cases["named_main"] == pb.name, "case_id"] if i not in own)
        out[pb.name] = (round(profile_similarity(ws, cluster_id, pb.name), 2) if n >= MIN_REFERENCE_CASES
                        else f"unknown (only {n} named complaints to compare with)")
    return out


def profile_similarity(ws: Workspace, cluster_id: str, playbook: str) -> float:
    """Cosine of IDF-weighted token-share profiles, ignoring lure / episode / gap tokens, so a known
    scam whose lure the phone missed still looks like itself, and tokens every scam shares count little."""
    mine = ws.cluster_by_id[cluster_id].case_ids
    own = set(mine)
    ref = [i for i in ws.cases.loc[ws.cases["named_main"] == playbook, "case_id"] if i not in own]
    return cluster.profile_cosine(mine, ref, ws.case_tokens, ws.token_idf())


def review_offline(ws: Workspace, cluster_id: str, draft: dict) -> dict:
    g, rules = config.load()["gates"], config.load()["analyst_offline"]
    bt, cases = draft["backtest"], len(ws.cluster_by_id[cluster_id].case_ids)
    sims = {pb.name: profile_similarity(ws, cluster_id, pb.name) for pb in ws.playbooks if pb.status == "known"}
    nearest = max(sims, key=sims.get) if sims else None
    sim = sims.get(nearest, 0.0)
    if bt and bt["legit_payments_named_per_1000"] > rules["lookalike_legit_per_1000"]:
        verdict, why = "lookalike_not_scam", f"the matcher names {bt['legit_payments_named_per_1000']:.1f} legit payments per 1,000"
    elif sim >= rules["variant_similarity"] or (bt and bt["known_playbook_payments_also_matched"] > g["max_known_overlap"]):
        verdict, why = "variant_of_known", f"its signals match {nearest} (profile similarity {sim:.2f}, lures ignored)"
    elif cases < config.load()["cluster"]["min_cluster_size"] or (bt and bt["cluster_case_recall"] < g["min_cluster_recall"]):
        verdict, why = "insufficient_evidence", f"{cases} cases, matcher case recall {bt['cluster_case_recall'] if bt else 0:.0%}"
    else:
        verdict, why = "new_scam", f"no known playbook is close (nearest {nearest}, {sim:.2f}) and the matcher passes the gates"
    evidence = [{"source": "signal_similarity_lures_ignored", "fact": f"closest known playbook: {nearest} at {sim:.2f} "
                 f"(variant threshold {rules['variant_similarity']})", "seen": True}]
    if bt:
        evidence.append({"source": "test_matcher", "fact": f"case recall {bt['cluster_case_recall']:.0%}, "
                         f"{bt['legit_payments_named_per_1000']} legit per 1,000, "
                         f"{bt['known_playbook_payments_also_matched']:.0%} of other known-scam payments", "seen": True})
    if bt and "warns" in bt:
        why += ("; approved, it would raise these payments to a warning (conditions span " + "+".join(bt["families"]) + ")"
                if bt["warns"] else "; approved, it would only name the scam: its conditions come from one family (rule 5)")
    return {"verdict": verdict, "nearest_playbook": nearest, "rationale": f"Offline rules: {why}.", "evidence": evidence,
            "required_changes": ["write the scam's story (no LLM draft)"] if draft["drafted_by"] == "offline" else [],
            "confidence": "low", "reviewed_by": "offline", "profile_similarity": {k: round(v, 2) for k, v in sims.items()}}
