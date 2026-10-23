"""Step 4: the analyst reviews the investigator's draft, independently.

Verdicts: new_scam | variant_of_known (same mechanism as a known playbook; e.g. the phone missed the
lure, so the known matcher could not fire) | lookalike_not_scam (honest behaviour that resembles a
scam) | insufficient_evidence. The verdict is advice for the two human analysts; it approves
nothing. With Bedrock it is a second LLM agent with the same read-only tools and a skeptical brief;
offline, fixed rules on the backtest and the token profiles.
"""
from __future__ import annotations

import numpy as np

from blue_team import config, llm, playbook_db
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
    },
    "required": ["verdict", "rationale", "confidence"],
}
SIGNATURE_IGNORE = ("LURE_", "EPISODE_", "BAIT_", "GAP_")   # what a missed lure / episode would remove

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
strongly suggests variant_of_known. A new_scam needs a mechanism no known playbook describes.
Check the investigator's claims against the cases yourself; run test_matcher if a number looks off;
compare with the nearest known playbooks. Do not invent evidence. Your verdict is advice to two
human analysts, who decide. Finish by calling submit_review."""


def _tools(ws: Workspace, cluster_id: str, draft: dict) -> list[llm.Tool]:
    empty = {"type": "object", "properties": {}, "required": []}
    known = {pb.name for pb in ws.playbooks}

    def submit(i: dict) -> dict:
        if i.get("verdict") not in VERDICTS:
            return {"accepted": False, "errors": [f"verdict must be one of {VERDICTS}"]}
        if i["verdict"] == "variant_of_known" and i.get("nearest_playbook") not in known:
            return {"accepted": False, "errors": [f"variant_of_known needs nearest_playbook, one of {sorted(known)}"]}
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


def review(ws: Workspace, cluster_id: str, draft: dict, rt, model_id: str) -> dict:
    a = config.load()["agents"]
    task = f"Review the draft playbook '{draft['card']['name']}' for cluster {cluster_id}."
    res = llm.run_agent(rt, model_id, SYSTEM, task, _tools(ws, cluster_id, draft), "submit_review", a["analyst_max_turns"])
    if res.final is None:
        out = review_offline(ws, cluster_id, draft)
        out["reviewed_by"] = f"offline (the {model_id} analyst gave no verdict in {res.turns} turns)"
    else:
        out = {**res.final, "reviewed_by": model_id}
    out["transcript"] = res.transcript
    out["usage"] = {"turns": res.turns, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out}
    return out


def similarities(ws: Workspace, cluster_id: str) -> dict[str, float]:
    return {pb.name: round(profile_similarity(ws, cluster_id, pb.name), 2) for pb in ws.playbooks if pb.status == "known"}


def profile_similarity(ws: Workspace, cluster_id: str, playbook: str) -> float:
    """Cosine of IDF-weighted token-share profiles, ignoring lure / episode / gap tokens, so a known
    scam whose lure the phone missed still looks like itself, and tokens every scam shares count little."""
    ref = ws.cases.loc[ws.cases["named_main"] == playbook, "case_id"].tolist()
    if not ref:
        return 0.0
    a = ws._token_share(ws.cluster_by_id[cluster_id].case_ids)
    b = ws._token_share(ref)
    idf = ws.token_idf()
    keys = sorted(k for k in set(a) | set(b) if not k.startswith(SIGNATURE_IGNORE))
    va = np.array([a.get(k, 0) * idf.get(k, 0) for k in keys])
    vb = np.array([b.get(k, 0) * idf.get(k, 0) for k in keys])
    n = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(va @ vb / n) if n else 0.0


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
    return {"verdict": verdict, "nearest_playbook": nearest, "rationale": f"Offline rules: {why}.",
            "required_changes": ["write the scam's story (no LLM draft)"] if draft["drafted_by"] == "offline" else [],
            "confidence": "low", "reviewed_by": "offline", "profile_similarity": {k: round(v, 2) for k, v in sims.items()}}
