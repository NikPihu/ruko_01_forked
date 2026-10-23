import json

from blue_team import analyst, investigator, llm

GOOD = {"all": [{"feature": "on_call", "op": "is", "value": True}, {"feature": "payer_says", "op": "eq", "value": "family"}]}


def card(**kw):
    c = {"name": "relative_voice_clone", "title": "Voice-clone 'relative in trouble' call",
         "summary": "A caller sounding like a relative asks for urgent money.", "steps": ["call", "pay"],
         "signals": ["CALL_ON", "SAYS_FAMILY"], "matcher": GOOD, "reason_codes": ["R1_live_unknown_call"],
         "advice_en": "Hang up and call your relative back on their saved number.",
         "advice_hi": "फ़ोन काटें और अपने रिश्तेदार को उनके सेव नंबर पर वापस कॉल करें।",
         "ai_powered": {"likely": True, "why": "VoIP call, family story"}, "confidence": "medium"}
    c.update(kw)
    return c


def test_hdbscan_finds_both_new_scams_and_keeps_them_apart(ws):
    groups = [{i.split("_")[0] for i in c.case_ids} for c in ws.clusters.clusters if c.kind == "new"]
    assert {"rep0"} in groups and {"rep2"} in groups


def test_tools_expose_no_ground_truth(ws, new_cluster):
    blob = json.dumps([ws.overview(new_cluster), ws.case(ws.cluster_by_id[new_cluster].case_ids[0]),
                       ws.payee("mule0_0@ybl")], default=str)
    for word in ("label", "is_scam", "journey", "is_mule", "flow"):
        assert word not in blob


def test_backtest_and_gates(ws, new_cluster):
    bt = ws.test_matcher(GOOD, new_cluster)
    assert bt["cluster_case_recall"] == 1.0 and bt["legit_payments_named_per_1000"] == 0 and bt["gate_failures"] == []
    broad = ws.test_matcher({"feature": "amount_inr", "op": ">", "value": 0}, new_cluster)
    assert any("legit" in g for g in broad["gate_failures"])
    assert ws.test_matcher({"feature": "nope", "op": "is", "value": True}, new_cluster)["valid"] is False


def test_card_checks():
    assert investigator.check_card(card(), set()) == []
    errs = investigator.check_card(card(name="Bad Name", advice_hi="hang up", reason_codes=["R99"]), set())
    assert len(errs) == 3
    assert investigator.check_card(card(), {"relative_voice_clone"})


def test_offline_investigator_and_analyst(ws, new_cluster):
    draft = investigator.investigate_offline(ws, new_cluster, set())
    assert draft["gate_failures"] == [] and draft["backtest"]["cluster_case_recall"] >= 0.6
    assert investigator.check_card(draft["card"], set()) == []
    rev = analyst.review_offline(ws, new_cluster, draft)
    assert rev["verdict"] in analyst.VERDICTS


class FakeBedrock:
    """Plays back scripted model turns and records what the agent sent."""

    def __init__(self, turns):
        self.turns, self.calls = list(turns), []

    def converse(self, **kw):
        self.calls.append(kw)
        content = self.turns.pop(0)
        return {"output": {"message": {"role": "assistant", "content": content}}, "stopReason": "tool_use",
                "usage": {"inputTokens": 10, "outputTokens": 5}}


def use(name, inp, i):
    return {"toolUse": {"toolUseId": f"t{i}", "name": name, "input": inp}}


def test_investigator_agent_loop_retries_until_the_card_is_valid(ws, new_cluster):
    rt = FakeBedrock([
        [{"text": "Looking."}, use("get_cluster_overview", {}, 1)],
        [use("test_matcher", {"matcher": GOOD}, 2)],
        [use("submit_playbook", card(advice_hi="no hindi"), 3)],       # rejected: advice_hi not Hindi
        [use("submit_playbook", card(), 4)],
    ])
    draft = investigator.investigate(ws, new_cluster, rt, "fake-model", set())
    assert draft["card"]["name"] == "relative_voice_clone" and draft["drafted_by"] == "fake-model"
    assert draft["backtest"]["cluster_case_recall"] == 1.0
    assert draft["usage"]["turns"] == 4
    sent = json.dumps(rt.calls[-1]["messages"], ensure_ascii=False)
    assert "Devanagari" in sent                                       # the model was told what to fix


def test_agent_that_never_submits_falls_back_to_offline(ws, new_cluster):
    rt = FakeBedrock([[{"text": "I think it is a scam."}]] * 20)
    draft = investigator.investigate(ws, new_cluster, rt, "fake-model", set())
    assert draft["drafted_by"].startswith("offline")


def test_analyst_agent_needs_a_known_playbook_for_variant(ws, new_cluster):
    draft = investigator.investigate_offline(ws, new_cluster, set())
    rt = FakeBedrock([
        [use("submit_review", {"verdict": "variant_of_known", "nearest_playbook": "made_up", "rationale": "x", "confidence": "low"}, 1)],
        [use("submit_review", {"verdict": "new_scam", "rationale": "no known playbook has a family story", "confidence": "medium"}, 2)],
    ])
    rev = analyst.review(ws, new_cluster, draft, rt, "fake-model")
    assert rev["verdict"] == "new_scam" and rev["reviewed_by"] == "fake-model"


def test_tool_errors_go_back_to_the_model(ws, new_cluster):
    rt = FakeBedrock([[use("get_case", {"case_id": "nope"}, 1)], [use("no_such_tool", {}, 2)],
                      [use("submit_review", {"verdict": "insufficient_evidence", "rationale": "x", "confidence": "low"}, 3)]])
    tools = analyst._tools(ws, new_cluster, investigator.investigate_offline(ws, new_cluster, set()))
    res = llm.run_agent(rt, "fake", "sys", "task", tools, "submit_review", 5)
    assert res.final["verdict"] == "insufficient_evidence"
    statuses = [c["toolResult"]["status"] for m in rt.calls[-1]["messages"] if m["role"] == "user"
                for c in m["content"] if "toolResult" in c]
    assert statuses[:2] == ["error", "error"]
