import random

import yaml

from api import rule_scorer
from blue_team import matcher, playbook_db, tokens
from bt_helpers import features

LEAF = {"feature": "on_call", "op": "is", "value": True}


def test_valid_matcher_has_no_errors():
    assert matcher.validate({"all": [LEAF, {"not": {"feature": "payer_says", "op": "in", "value": ["shop"]}}]}) == []


def test_bad_matchers_are_explained():
    assert "unknown feature 'sms_text'" in matcher.validate({"feature": "sms_text", "op": "eq", "value": "x"})
    assert any("unknown op" in e for e in matcher.validate({"feature": "on_call", "op": "exec", "value": 1}))
    assert any("needs a number" in e for e in matcher.validate({"feature": "amount_inr", "op": ">=", "value": "5"}))
    assert any("deeper" in e for e in matcher.validate({"not": {"not": {"not": {"not": LEAF}}}}))
    assert any("too many" in e for e in matcher.validate({"any": [LEAF] * 13}))
    assert matcher.validate("import os")  # not an object: rejected, never run


def test_unknown_never_satisfies_a_comparison():
    f = features(on_call=None, amount_inr=None)
    assert not matcher.matches(LEAF, f)
    assert not matcher.matches({"feature": "amount_inr", "op": "<", "value": 10}, f)
    assert not matcher.matches({"feature": "on_call", "op": "is", "value": False}, f)
    assert matcher.matches({"feature": "on_call", "op": "is_null"}, f)


def test_known_playbooks_in_the_database_name_exactly_like_the_engine():
    """The engine's data/playbooks/playbooks.yaml, read into matchers, must name every payment exactly
    like backend/api/rule_scorer._playbook does."""
    pbs = playbook_db.load(("known",))
    r = random.Random(1)
    opts = {"lure_tag": [None, "kyc", "arrest_threat", "trading_tip", "task_job", "refund"], "episode_state": [0, 1, 2, None],
            **{k: [None, True, False] for k in ("sideloaded_last_24h", "outgoing_to_unknown", "remote_control", "session_dictated",
                                                "on_call", "caller_unknown", "voip_call", "story_mismatch", "entry_typed",
                                                "video_call")}}
    for _ in range(5000):
        f = features(**{k: r.choice(v) for k, v in opts.items()})
        assert playbook_db.name_scam(f, pbs) == rule_scorer._playbook(f), f


def test_approved_playbooks_come_after_known_ones(tmp_db):
    card = {"name": "always", "title": "t", "match": [{"priority": 100, "rule": {"feature": "amount_inr", "op": ">", "value": 0}}]}
    playbook_db.write(card, "approved", tmp_db)
    pbs = playbook_db.load(root=tmp_db)
    assert playbook_db.name_scam(features(lure_tag="trading_tip"), pbs) == "trading_group"
    assert playbook_db.name_scam(features(), pbs) == "always"


def test_tokens_and_gaps():
    f = features(on_call=True, voip_call=True, caller_unknown=None, entry_method="typed", payer_says="family", amount_inr=20000)
    toks = tokens.payment_tokens(f)
    assert {"CALL_ON", "CALL_VOIP", "CALLER_UNKNOWN", "ENTRY_TYPED", "SAYS_FAMILY", "AMT_10K_50K"} <= set(toks)
    doc = tokens.case_document([(0, f), (30 * 60, f)])
    assert doc.split().count("PAY") == 2 and "GAP_UNDER_1H" in doc
    for name, rule in tokens.TOKENS.items():
        assert matcher.validate(rule) == [], name


def test_common_spellings_are_normalized_not_trusted():
    rule = {"all": [{"feature": "first_time_payee", "op": "is", "value": "true"},
                    {"feature": "amount_inr", "op": "gte", "value": "1000"},
                    {"feature": "on_call", "op": "is_true"},
                    {"feature": "payer_says", "op": "in", "value": "family"}]}
    n = matcher.normalize(rule)
    assert matcher.validate(n) == []
    assert n["all"][0]["value"] is True and n["all"][1] == {"feature": "amount_inr", "op": ">=", "value": 1000.0}
    assert n["all"][2] == {"feature": "on_call", "op": "is", "value": True} and n["all"][3]["value"] == ["family"]
    assert matcher.validate(matcher.normalize({"feature": "on_call", "op": "exec", "value": 1}))  # still rejected


def test_token_leaves_expand_to_the_tokens_exact_rule():
    voip = features(on_call=True, voip_call=True, caller_unknown=None)
    rule = matcher.normalize({"all": [{"token": "CALL_ON"}, {"token": "CALLER_UNKNOWN"}]})
    assert matcher.validate(rule) == [] and matcher.matches(rule, voip)
    assert not matcher.matches({"feature": "caller_unknown", "op": "is", "value": True}, voip)   # the trap it avoids
    assert any("unknown token" in e for e in matcher.validate(matcher.normalize({"token": "NOPE"})))


def test_approved_cards_export_to_the_engine_file_format_or_say_why_not():
    from api.playbooks import parse
    from blue_team import engine_file
    ok = {"name": "voice_clone_family", "title": "Voice-clone relative", "approved_by": ["asha", "ravi"],
          "misnamed_as": "digital_arrest",
          "match": [{"priority": 39, "rule": matcher.normalize({"all": [{"token": "CALL_ON"}, {"token": "CALLER_UNKNOWN"},
                                                                        {"not": {"token": "REMOTE_CONTROL"}}]})}]}
    text, problems = engine_file.export_entry(ok)
    assert problems == [] and "BEFORE the first 'digital_arrest'" in text
    entry = yaml.safe_load(text)[0]
    assert entry["match"] == {"on_call": True, "unknown_caller": True, "remote_control": False}
    rules = parse({"playbooks": [entry]})                        # the engine accepts it
    r = random.Random(4)
    for _ in range(2000):                                        # and it names exactly like our matcher
        f = features(**{k: r.choice([None, True, False]) for k in ("on_call", "caller_unknown", "voip_call", "remote_control")})
        assert rules[0][2](f) == matcher.matches(ok["match"][0]["rule"], f)
    bad = {**ok, "match": [{"priority": 100, "rule": {"all": [{"token": "SAYS_FAMILY"}, {"token": "AMT_10K_50K"}]}}]}
    text, problems = engine_file.export_entry(bad)
    assert any("request field" in p for p in problems) and any("no '>='" in p or "no '<'" in p for p in problems)
    assert "NOT EXPRESSIBLE" in text
