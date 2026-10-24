"""RUKO risk engine API.

    PYTHONPATH=backend:ml:data python -m api.main --data data/ --intel http://127.0.0.1:8001 --port 8000

Add --demo-clock when a real phone is paying: the phone sends today's time, but the synthetic
world (baselines, mock intel) lives at the sim clock. With the flag, the engine ignores the
request's `ts` and uses the sim clock, read from the mock at startup and on /sim/reset.

Use 127.0.0.1, not localhost: on Windows "localhost" tries IPv6 first and adds ~200 ms per new
connection, which alone blows the 150 ms intel budget.

Decide path, all inside a 200 ms deadline (fail open on timeout or any error):
    tracker.update -> intel.lookup (150 ms budget) -> build_features -> score -> policy -> evidence

Every check, its full decision and its outcome go into the transaction database (`store/db.py`,
in memory unless --db is given), off the latency path.

--scorer rules (default) or ml: ml uses ml/model/predict.py when it loads, otherwise the rules.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api import rule_scorer as scorer
from features.user_baseline import Baselines
from evidence.store import EvidenceStore, pseudonym
from features.build import build_features
from api.intel import IntelAdapter
from api.policy import Policy
from api.episode_events import EpisodeService
from graph import discover as discovery
from graph.store import GraphStore
from store.db import TxnStore
from api.explain import explain
from patterns import emerging
from api.feedback import FeedbackService, alert_health
from schema.events import (CONTRACT_VERSION, DecideRequest, DecideResponse, EpisodeEvent, EpisodeEventResponse,
                           Feedback, FeedbackResponse, MyPayment, MyPayments, PaymentOutcome,
                           PaymentOutcomeResponse, Threat, WatchEvent, WatchEventResponse)
from features.tracker import StageTracker

log = logging.getLogger("ruko")
DEADLINE_S = 0.200
MAX_ALERTS = 500
# The built analyst console (cd console && npm run build), served at /console/.
CONSOLE_DIST = Path(__file__).resolve().parents[2] / "console" / "dist"


class PatternReviewBody(BaseModel):
    """An analyst names an emerging pattern (a new scam type) or dismisses it."""
    analyst: str
    action: str  # name | dismiss
    name: str | None = None


class ReviewBody(BaseModel):
    """An analyst's decision on a discovered suspect (two different approvals are needed)."""
    reviewer: str
    decision: str  # approve | reject


def create_app(data_dir: str | Path, intel_client: httpx.AsyncClient | None = None,
               intel_url: str = "http://127.0.0.1:8001", evidence_path: str = ":memory:",
               intel_budget_s: float = 0.150, intel_cache_ttl_s: float = 10.0,
               log_path: str | Path | None = "logs/decide.jsonl", evidence_async: bool = True,
               demo_clock: bool = False, discover_every_s: float | None = None,
               db_path: str | Path = ":memory:", scorer_name: str = "rules") -> FastAPI:
    """`scorer_name`: "rules" (api/rule_scorer.py) or "ml" (the trained LightGBM model in
    ml/model/predict.py). If the model cannot be loaded, the engine keeps the rules (never fails).
    `db_path`: the transaction database, in memory by default (store/db.py)."""
    client = intel_client or httpx.AsyncClient(base_url=intel_url)
    # sim time - wall time; None means "use the request's ts".
    clock: dict[str, timedelta | None] = {"offset": None}

    async def sync_clock() -> None:
        try:
            r = await client.get("/sim/state")
            sim_now = datetime.fromisoformat(r.raise_for_status().json()["now"])
            clock["offset"] = sim_now - datetime.now(sim_now.tzinfo)
            log.info("demo clock: sim now %s", sim_now.isoformat())
        except (httpx.HTTPError, KeyError, ValueError):
            log.warning("demo clock: sim state not reachable; using request timestamps")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Open the connection pool before the first payment so it doesn't pay connect costs.
        try:
            await asyncio.gather(*(client.get("/health") for _ in range(6)))
        except httpx.HTTPError:
            log.warning("intel services not reachable at startup; lookups will count as unknown")
        if demo_clock:
            await sync_clock()
        task = asyncio.create_task(discover_loop()) if discover_every_s else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="RUKO risk engine", lifespan=lifespan)
    intel = IntelAdapter(client, budget_s=intel_budget_s, cache_ttl_s=intel_cache_ttl_s)
    tracker, policy = StageTracker(), Policy()
    baselines = Baselines.from_data(data_dir)
    evidence = EvidenceStore(evidence_path)
    trusted: dict[str, set[str]] = {}
    # Swappable: anything with score(features) -> same dict shape (e.g. the trained model).
    app.state.score, app.state.model_version = load_scorer(scorer_name)
    scorer_version = app.state.model_version
    scorer_used = "rules" if scorer_version == scorer.MODEL_VERSION else "ml"
    store = TxnStore(db_path)
    app.state.store = store

    def persist(fn, *args) -> None:
        """Database writes never sit on the payment path (rule 3)."""
        try:
            loop = asyncio.get_running_loop() if evidence_async else None
        except RuntimeError:  # a sync endpoint already runs in a worker thread
            loop = None
        if loop:
            loop.run_in_executor(None, fn, *args)
        else:
            fn(*args)
    app.state.evidence, app.state.trusted = evidence, trusted
    graph = GraphStore()
    app.state.graph = graph
    reviews: dict[str, discovery.Review] = {}
    found: dict = {"suspects": [], "last_run": None}
    app.state.reviews = reviews
    # Payment checks that got T1 or higher, newest last, for the analyst console.
    alerts: list[dict] = []
    app.state.alerts = alerts
    eval_dir = Path(data_dir) / "eval"

    def sim_now() -> datetime:
        now = datetime.now().astimezone()
        return now + clock["offset"] if clock["offset"] is not None else now

    def run_discovery(min_band: str = "med") -> list[dict]:
        now = sim_now()
        try:
            found["suspects"] = discovery.discover(graph, reviews, now, min_band=min_band)
            found["last_run"] = discovery.last_run_summary(found["suspects"], now)
        except Exception as e:  # a broken run must never affect payments
            log.exception("discovery failed")
            found["last_run"] = discovery.last_run_summary([], now, error=str(e))
        return found["suspects"]

    async def discover_loop() -> None:
        while True:
            await asyncio.sleep(discover_every_s)
            await asyncio.get_running_loop().run_in_executor(None, run_discovery)
    episodes = EpisodeService(intel, evidence, graph=graph)
    app.state.episodes = episodes
    feedback = FeedbackService(store, trusted, evidence,
                               per_user_per_day=policy.cfg.get("feedback", {}).get("per_user_per_day", 30),
                               persist=persist)
    watch_seen: set[str] = set()
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    def fail_open(req: DecideRequest) -> DecideResponse:
        return DecideResponse(request_id=req.request_id, tier="T0", reasons=["ruko_unavailable"], fail_open=True)

    async def decide_inner(req: DecideRequest, ms: dict, trace: dict) -> DecideResponse:
        t = time.perf_counter()
        base = baselines.get(req.user_id, at=req.ts)  # only what the bank knew before this payment
        upi = req.payee_upi_id.strip().lower()
        is_trusted = upi in trusted.get(req.user_id, set())
        # Known payee: the bank's history, or a payment here the phone reported completed (c2-0.6) —
        # but only a real, aged payment, not a tiny recent "anchor" (known-payee poisoning, audit §2.1).
        kp = policy.cfg.get("known_payee", {})
        paid_here = graph.known_payee(req.user_id, upi, req.ts,
                                      kp.get("min_age_hours", 48), kp.get("min_inr", 500))
        micro_anchor = not paid_here and graph.micro_anchor(
            req.user_id, upi, req.ts, kp.get("anchor_window_hours", 72), kp.get("anchor_max_inr", 200))
        state = tracker.update(req, new_payee=upi not in base.known_payees and not paid_here and not is_trusted)
        ms["tracker"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        call = req.context.call if req.context else None
        res = await intel.lookup(upi, call.caller_number if call else None)
        ms["intel"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        # The payment graph: this check is an edge, and the payee's crowd / loop signals are read
        # from what episodes already added (no extra lookups on the payment path).
        graph.add_payment(req.user_id, upi, req.amount_inr, req.ts, request_id=req.request_id)
        graph.expire(req.ts)
        ring = graph.account_signals(upi, req.ts)
        # Discovered suspects count only after two analysts approved them (§9.5).
        ring["approved_suspect"] = upi in discovery.approved_suspects(reviews)
        feats = build_features(req, state, res, base, is_trusted, ring=ring, paid_here=paid_here,
                               micro_anchor=micro_anchor)
        ms["features"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        s = app.state.score(feats)
        # The phone's fraud class names the scam when the server's playbook matcher found none (c2-0.8),
        # e.g. a WhatsApp "digital arrest" call whose number the phone cannot see.
        dv = req.context.device_verdict if req.context else None
        if s["playbook"] is None and dv is not None and dv.fraud_class is not None:
            s = {**s, "playbook": dv.fraud_class}
        ms["score"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        control_seen = any(stage == "S3" for stage, _ in state.stage_path) or bool(feats["remote_control"])
        d = policy.decide(s, feats, state.stage, control_seen, req.user_id, req.ts)
        ms["policy"] = (time.perf_counter() - t) * 1000

        evidence_id = None
        if d.tier != "T0" or d.applied:
            evidence_id = f"e_{uuid.uuid4().hex[:12]}"
            row = {
                "id": evidence_id, "ts": req.ts.isoformat(), "user_hash": pseudonym(req.user_id),
                "payee_hash": pseudonym(upi), "caller_hash": pseudonym(call.caller_number if call else None),
                "tier": d.tier, "p_scam": s["p_scam"], "reasons": s["reasons"], "playbook": s["playbook"],
                "family_scores": {**s["family_scores"], "lit": d.lit_families, "policy_rules": d.applied},
                "features": feats, "intel_status": res.status,
                "stage_path": [(stage, ts.isoformat()) for stage, ts in state.stage_path],
                "model_version": s["model_version"], "policy_version": policy.version,
            }
            if evidence_async:  # off the latency path
                asyncio.get_running_loop().run_in_executor(None, evidence.write, row)
            else:
                evidence.write(row)

        reasons = s["reasons"] if d.tier != "T0" else []
        graph.set_decision(req.request_id, d.tier, reasons, evidence_id)
        trace.update(details={
            "features": feats, "p_scam": s["p_scam"], "family_scores": s["family_scores"],
            "lit_families": d.lit_families, "policy_steps": d.applied, "intel_status": res.status,
            "stage_path": [(stage, ts.isoformat()) for stage, ts in state.stage_path],
            "signals": s.get("signals")},
            scorer_version=s.get("model_version", scorer_version))
        if d.tier != "T0":
            alerts.append({
                "alert_id": evidence_id or f"a_{uuid.uuid4().hex[:12]}", "payment_id": req.request_id,
                "ts": req.ts.isoformat(),
                "user_hash": pseudonym(req.user_id), "payee": upi, "amount_inr": req.amount_inr,
                "tier": d.tier, "reasons": reasons, "message_key": d.message_key,
                "playbook": s["playbook"], "stage": state.stage, "pause_minutes": d.pause_minutes,
                "stage_path": [(stage, ts.isoformat()) for stage, ts in state.stage_path],
                "families": d.lit_families, "evidence_id": evidence_id, "entry_method": req.entry_method,
            })
            del alerts[:-MAX_ALERTS]
        return DecideResponse(
            request_id=req.request_id, tier=d.tier, reasons=reasons, message_key=d.message_key,
            pause_minutes=d.pause_minutes, playbook=s["playbook"] if d.tier != "T0" else None,
            stage=state.stage, evidence_id=evidence_id, threat=threat_of(s, d))

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "model_version": app.state.model_version, "scorer": scorer_used,
                "policy_version": policy.version, "playbooks": scorer.PLAYBOOK_SOURCE, "contract_version": CONTRACT_VERSION,
                "demo_clock": clock["offset"] is not None, "db": "memory" if str(db_path) == ":memory:" else "file"}

    @app.post("/v1/decide", response_model=DecideResponse)
    async def decide(req: DecideRequest) -> DecideResponse:
        t0, ms, trace = time.perf_counter(), {}, {}
        if clock["offset"] is not None:
            req = req.model_copy(update={"ts": datetime.now(req.ts.tzinfo) + clock["offset"]})
        try:
            resp = await asyncio.wait_for(decide_inner(req, ms, trace), timeout=DEADLINE_S)
        except asyncio.TimeoutError:
            log.warning("decide timed out")
            resp = fail_open(req)
        except Exception:
            log.exception("decide failed")
            resp = fail_open(req)
        ms["total"] = (time.perf_counter() - t0) * 1000
        try:  # a fail-open answer is recorded too: it is what the user saw
            persist(store.record_decision, {
                "payment_id": req.request_id, "user_id": req.user_id, "payee_upi": req.payee_upi_id.strip().lower(),
                "amount_inr": req.amount_inr, "entry_method": req.entry_method, "ts": req.ts, "tier": resp.tier,
                "reasons": resp.reasons, "message_key": resp.message_key, "playbook": resp.playbook,
                "stage": resp.stage, "pause_minutes": resp.pause_minutes,
                "scorer_version": trace.get("scorer_version", scorer_version), "policy_version": policy.version,
                "evidence_id": resp.evidence_id, "fail_open": resp.fail_open, "latency_ms": round(ms["total"], 2),
            }, trace.get("details", {}))
        except Exception:
            log.exception("recording the payment failed")
        if log_path:
            with open(log_path, "a") as fh:
                fh.write(json.dumps({"ts": req.ts.isoformat(), "request_id": req.request_id,
                                     "tier": resp.tier, **{f"ms_{k}": round(v, 2) for k, v in ms.items()}}) + "\n")
        return resp

    @app.post("/v1/payment/outcome", response_model=PaymentOutcomeResponse)
    def payment_outcome(o: PaymentOutcome) -> PaymentOutcomeResponse:
        """After the PIN or Cancel (c2-0.6): the payment's outcome goes into the payment graph.
        Never on the payment path; the phone retries until it gets an answer."""
        ts = o.ts
        if clock["offset"] is not None:
            ts = datetime.now(o.ts.tzinfo) + clock["offset"]
        status, recorded = graph.record_outcome(o.request_id, o.user_id, o.payee_upi_id, o.amount_inr,
                                                o.status, ts)
        if recorded:
            persist(store.record_outcome, o.request_id, o.status, ts)
        return PaymentOutcomeResponse(request_id=o.request_id, status=status, recorded=recorded)

    @app.post("/v1/episode", response_model=EpisodeEventResponse)
    async def episode_event(ev: EpisodeEvent) -> EpisodeEventResponse:
        """The phone's watcher changed state (c2-0.4). Never needed by /v1/decide; missing means unknown."""
        now = ev.ts
        if clock["offset"] is not None:
            now = datetime.now(ev.ts.tzinfo) + clock["offset"]
        try:
            resp = await episodes.handle(ev, now)
            persist(store.record_episode, ev.event_id, ev.user_id, ev.episode_id, ev.trigger, resp.episode_risk,
                    [a.upi_id for a in ev.accounts], resp.case_id, now)
            if resp.case_id:
                case = next((c for c in episodes.cases if c["case_id"] == resp.case_id), None)
                if case:
                    persist(store.record_case, case)
            return resp
        except Exception:
            log.exception("episode event failed")
            return EpisodeEventResponse(event_id=ev.event_id, episode_risk="unknown", reasons=[])

    def server_ts(ts: datetime) -> datetime:
        return datetime.now(ts.tzinfo) + clock["offset"] if clock["offset"] is not None else ts

    @app.post("/v1/feedback", response_model=FeedbackResponse)
    def post_feedback(fb: Feedback) -> FeedbackResponse:
        """What the user did on an alert (c2-0.8). Only for the user's own payment; never on the payment path."""
        return feedback.handle(fb, server_ts(fb.ts))

    @app.post("/v1/watch", response_model=WatchEventResponse)
    def post_watch(ev: WatchEvent) -> WatchEventResponse:
        """An early warning from the phone (c2-0.8): moves the user's scam stage before any payment."""
        if ev.event_id in watch_seen:
            return WatchEventResponse(event_id=ev.event_id, recorded=False)
        watch_seen.add(ev.event_id)
        ts = server_ts(ev.ts)
        stage = tracker.observe(ev.user_id, ev.kind, ts, lure_conf=ev.lure_conf, call_minutes=ev.call_minutes)
        detail = {k: v for k, v in ev.model_dump(include={"lure_tag", "lure_conf", "source", "ai_written",
                                                           "call_kind", "call_minutes"}).items() if v is not None}
        persist(store.record_watch, ev.event_id, ev.user_id, ev.kind, detail, ts)
        return WatchEventResponse(event_id=ev.event_id, recorded=True, stage=stage)

    @app.get("/v1/me/payments", response_model=MyPayments)
    def my_payments(user_id: str, limit: int = 100) -> MyPayments:
        """The user's own payments as RUKO recorded them (c2-0.8): plain words, never a score."""
        rows = store.payments_of(user_id, limit=max(1, min(limit, 500)))
        return MyPayments(payments=[MyPayment(payee_upi_id=r.pop("payee_upi"), **r) for r in rows])

    @app.get("/v1/metrics/alerts")
    def metrics_alerts() -> dict:
        """Alert health for the console: what people do on alerts, per tier (aggregates only)."""
        return alert_health(store)

    @app.get("/v1/cases")
    def cases() -> list[dict]:
        """Analyst cases opened by high-risk episodes (console, C5)."""
        return episodes.cases

    @app.get("/v1/alerts")
    def list_alerts(min_tier: str = "T1", limit: int = 200) -> list[dict]:
        """Payment checks that got min_tier or higher, newest first (console, C5)."""
        rank = {"T1": 1, "T2": 2, "T3": 3, "T4": 4}
        if min_tier not in rank:
            raise HTTPException(422, "min_tier must be T1, T2, T3 or T4")
        keep = [a for a in alerts if rank[a["tier"]] >= rank[min_tier]]
        return keep[::-1][:max(1, min(limit, MAX_ALERTS))]

    @app.get("/v1/eval")
    def eval_results() -> dict:
        """The latest offline evaluation results, for the console's Evaluation page."""
        out = {}
        for name in ("episode", "graph"):
            f = eval_dir / f"{name}_results.json"
            out[name] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        # A3: the lure model on AI-written scam messages (python -m evalsuite.ai_lures)
        f = Path(__file__).resolve().parents[1] / "evalsuite" / "ai_lures_results.json"
        out["ai_lures"] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        return out

    # ---------- payment graph for the analyst console (contract C5, §9.7) ----------

    @app.get("/v1/graph/account/{upi_id}")
    def graph_account(upi_id: str, hops: int = 2) -> dict:
        out = graph.neighbourhood(upi_id, hops=max(1, min(hops, 3)))
        out["signals"] = graph.account_signals(upi_id, sim_now())
        return out

    @app.get("/v1/graph/story/{upi_id}")
    def graph_story(upi_id: str) -> dict:
        """The account's money flow as a short story: who baited whom, who paid it, where it went."""
        return graph.story(upi_id, sim_now())

    @app.get("/v1/graph/payments/{upi_id}")
    def graph_payments(upi_id: str, limit: int = 20) -> dict:
        """Payments into an account, newest first, each with its payment id, decision and outcome."""
        return graph.payments_for(upi_id, limit=max(1, min(limit, 100)))

    @app.get("/v1/payments/{payment_id}")
    def payment_by_id(payment_id: str) -> dict:
        """Trace one payment by its id (the /v1/decide request_id) from the check to its outcome."""
        p = graph.payment(payment_id)
        if p is None:
            raise HTTPException(404, "no payment with that id in the last 30 days")
        return p

    @app.get("/v1/graph/suspects")
    def graph_suspects(min_band: str = "med") -> dict:
        """Analysts see medium and high suspects by default; ?min_band=low shows everything."""
        if min_band not in discovery.BAND_RANK:
            raise HTTPException(422, "min_band must be low, med or high")
        return {"suspects": run_discovery(min_band), "last_run": found["last_run"],
                "approvals_needed": discovery.APPROVALS_NEEDED}

    @app.get("/v1/graph/rings")
    def graph_rings() -> dict:
        """Mule rings: members, hubs (with a hub score), victims, money and speed (analyst console)."""
        return {"as_of": sim_now().isoformat(), "rings": discovery.ring_view(graph, reviews, sim_now())}

    @app.get("/v1/graph/rings/{ring_id}")
    def graph_ring(ring_id: str) -> dict:
        ring = next((r for r in discovery.ring_view(graph, reviews, sim_now()) if r["ring_id"] == ring_id), None)
        if ring is None:
            raise HTTPException(404, "no such ring now (ring ids change when the graph changes)")
        return ring

    @app.post("/v1/graph/suspects/{upi_id}/review")
    def graph_review(upi_id: str, body: ReviewBody) -> dict:
        if body.decision not in ("approve", "reject"):
            raise HTTPException(422, "decision must be approve or reject")
        r = discovery.review(reviews, upi_id, body.reviewer.strip(), body.decision)
        store.record_review(upi_id, body.reviewer.strip(), body.decision, sim_now())
        return {"upi_id": upi_id.strip().lower(), "approved_by": sorted(r.approved_by),
                "rejected_by": sorted(r.rejected_by), "approved": r.approved}

    @app.get("/console/graph", include_in_schema=False)
    def console_graph() -> RedirectResponse:
        """Old address of the graph page; the analyst console replaced it."""
        return RedirectResponse("/console/#/explore")

    @app.post("/v1/trusted/{user_id}/{payee_upi_id}")
    def mark_trusted(user_id: str, payee_upi_id: str) -> dict:
        """The user tapped "I know this person"."""
        trusted.setdefault(user_id, set()).add(payee_upi_id.strip().lower())
        store.record_trusted(user_id, payee_upi_id, "app", sim_now())
        return {"ok": True}

    # ---------- transaction database reads (analyst console) ----------

    @app.get("/v1/transactions")
    def transactions(user_hash: str | None = None, payee: str | None = None, min_tier: str = "T0",
                     status: str | None = None, since: str | None = None, until: str | None = None,
                     limit: int = 200) -> dict:
        """Every recorded payment check, newest first, with filters. The full detail is per payment."""
        if min_tier not in ("T0", "T1", "T2", "T3", "T4"):
            raise HTTPException(422, "min_tier must be T0 to T4")
        if status not in (None, "checked", "completed", "cancelled"):
            raise HTTPException(422, "status must be checked, completed or cancelled")
        rows = store.transactions(user_hash, payee, min_tier, status, since, until, limit)
        return {"count": len(rows), "transactions": rows}

    @app.get("/v1/transactions/{payment_id}")
    def transaction(payment_id: str) -> dict:
        """One payment with everything behind it: every input, every score, policy steps, feedback.
        Analysts only (rule 4: the score never reaches the user)."""
        p = store.payment(payment_id)
        if p is None:
            raise HTTPException(404, "no recorded payment with that id")
        return {"payment": p, "details": store.details(payment_id), "feedback": store.feedback_for(payment_id)}

    @app.get("/v1/payments/{payment_id}/explain")
    def explain_payment(payment_id: str) -> dict:
        """Why this payment got its tier: everything for the analyst, and what the user saw.
        Analyst console only; the app gets the short reasons in /v1/decide (rule 4)."""
        p = store.payment(payment_id)
        if p is None:
            raise HTTPException(404, "no recorded payment with that id")
        return explain(p, store.details(payment_id), policy.cfg)

    @app.get("/v1/users/{user_hash}/timeline")
    def user_timeline(user_hash: str, limit: int = 200) -> dict:
        """One pseudonymous user's payments, outcomes, feedback and phone events in time order."""
        return {"user_hash": user_hash, "events": store.timeline(user_hash, limit=max(1, min(limit, 1000)))}

    def patterns_now() -> datetime:
        """The sim clock, or the newest recorded payment when replayed data runs ahead of it."""
        now = sim_now()
        newest = store.transactions(limit=1)
        if newest:
            ts = datetime.fromisoformat(newest[0]["ts"])
            now = max(now, ts)
        return now

    @app.get("/v1/patterns/emerging")
    def emerging_patterns() -> dict:
        """New scam workflows with no known playbook (A4): analyst view only, never in a decision."""
        now = patterns_now()
        found_patterns = emerging.find(store, now, store.pattern_reviews())
        return {"as_of": now.isoformat(), "thresholds": emerging.T, "patterns": found_patterns}

    @app.post("/v1/patterns/{pattern_id}/review")
    def review_pattern(pattern_id: str, body: PatternReviewBody) -> dict:
        """Name it (a draft playbook for the data folder is returned) or dismiss it."""
        if body.action not in ("name", "dismiss") or not body.analyst.strip():
            raise HTTPException(422, "action must be name or dismiss, with an analyst")
        if body.action == "name" and not (body.name or "").strip():
            raise HTTPException(422, "a name is needed")
        now = patterns_now()
        pattern = next((p for p in emerging.find(store, now, store.pattern_reviews()) if p["pattern_id"] == pattern_id), None)
        if pattern is None:
            raise HTTPException(404, "no such emerging pattern now")
        name = (body.name or "").strip().lower().replace(" ", "_") or None
        draft = emerging.draft_playbook(pattern, name) if body.action == "name" else None
        store.record_pattern_review(pattern_id, "named" if body.action == "name" else "dismissed", name,
                                    body.analyst.strip(), draft, now)
        return {"pattern_id": pattern_id, "status": "named" if draft else "dismissed", "name": name, "draft_playbook": draft}

    demo_state: dict = {"running": False, "results": None, "error": None, "started": None}

    @app.post("/v1/demo/run")
    def demo_run(request: Request, scenario: str | None = None) -> dict:
        """Run the scripted demo agents against this engine, in the background (demo only).
        They are test actors using the public API; they never take part in a decision (rule 13)."""
        import threading

        from demo import agents
        if demo_state["running"]:
            return {"started": False, "reason": "already running"}
        base = str(request.base_url).rstrip("/")

        def go_run() -> None:
            demo_state.update(running=True, error=None, started=datetime.now().astimezone().isoformat())
            try:
                w = agents.load_world(Path(data_dir))
                with httpx.Client(base_url=base, timeout=30) as c, httpx.Client(base_url=intel_url, timeout=30) as mock:
                    now = datetime.fromisoformat(mock.get("/sim/state").json()["now"])
                    agents.pump_mule(mock, w)
                    demo_state["results"] = agents.run(c, w, now, [scenario] if scenario else None)
            except Exception as e:  # a demo failure must never touch payments
                log.exception("demo agents failed")
                demo_state["error"] = str(e)
            finally:
                demo_state["running"] = False

        threading.Thread(target=go_run, daemon=True).start()
        return {"started": True}

    @app.get("/v1/demo/results")
    def demo_results() -> dict:
        return demo_state

    @app.get("/v1/store/stats")
    def store_stats() -> dict:
        return {"db": "memory" if str(db_path) == ":memory:" else "file", "rows": store.counts()}

    @app.get("/v1/evidence/verify")
    def verify() -> dict:
        return evidence.verify()

    @app.get("/v1/evidence/{evidence_id}")
    def get_evidence(evidence_id: str) -> dict:
        row = evidence.get(evidence_id)
        if row is None:
            raise HTTPException(404, "no such evidence")
        return row

    @app.post("/sim/reset")
    async def reset() -> dict:
        tracker.reset()
        policy.reset()
        evidence.clear()
        trusted.clear()
        episodes.reset()
        graph.reset()
        reviews.clear()
        alerts.clear()
        store.reset()
        feedback.reset()
        watch_seen.clear()
        found.update(suspects=[], last_run=None)
        if demo_clock:  # the mock may have moved its clock since startup
            await sync_clock()
        return {"ok": True}

    if CONSOLE_DIST.is_dir():
        app.mount("/console", StaticFiles(directory=CONSOLE_DIST, html=True), name="console")
    else:
        log.info("analyst console not built; run: cd console && npm install && npm run build")
    return app


THREAT_LEVEL = {"T0": "none", "T1": "low", "T2": "medium", "T3": "high", "T4": "critical"}


def threat_of(s: dict, d) -> Threat:
    """The threat analysis the app shows (c2-0.8): score 0..100, a level in words from the tier, the
    known scam it matches, and the families that agree."""
    return Threat(score=max(0, min(100, round(100 * s["p_scam"]))), level=THREAT_LEVEL[d.tier],
                  fraud_type=s["playbook"] if d.tier != "T0" else None, families=list(d.lit_families))


def load_scorer(name: str):
    """(score function, model version). Falls back to the rules if the trained model is missing."""
    if name == "ml":
        try:
            from model import predict  # ml/ is on PYTHONPATH (backend;ml;data)
            model = predict.load()
            return predict.score, model.version
        except Exception:
            log.exception("trained model not available; using the rules")
    return scorer.score, scorer.MODEL_VERSION


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(description="Run the RUKO risk engine")
    p.add_argument("--data", default="data")
    p.add_argument("--intel", default="http://127.0.0.1:8001")
    p.add_argument("--evidence", default="logs/evidence.db")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--demo-clock", action="store_true",
                   help="ignore request timestamps and use the mock's sim clock (live phone demos)")
    p.add_argument("--db", default=":memory:",
                   help="transaction database: in memory (default) or a file to keep the run, e.g. logs/ruko.db")
    p.add_argument("--scorer", choices=("ml", "rules"), default="ml",
                   help="ml: the trained LightGBM model (falls back to rules if missing); rules: rules-only")
    a = p.parse_args()
    uvicorn.run(create_app(a.data, intel_url=a.intel, evidence_path=a.evidence, demo_clock=a.demo_clock,
                           discover_every_s=3600, db_path=a.db, scorer_name=a.scorer),
                host="0.0.0.0", port=a.port)


if __name__ == "__main__":
    main()
