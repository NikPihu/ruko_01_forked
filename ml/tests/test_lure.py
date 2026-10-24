"""lure.json (lure-0.2) must score exactly like scikit-learn, apply its temperature and the "unclear"
rule, and the shipped vectors must match the shipped JSON (the phone's LureModelTest reads them too)."""
import json
import math
import re

import numpy as np
import pandas as pd
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from model import lure_train as lt
from model.lure_corpus import CLASSES, OUT as CORPUS, SCAM_TAGS, TEMPLATES, _fill, generate

TRICKY = ["Hello   world", "a", "आप डिजिटल अरेस्ट में हैं।", "ok ok", " leading and trailing ",
          "Part time job", "x\ty\nz", "😀 emoji 😀", ""]
SEVEN = ["arrest_threat", "kyc", "normal", "other_scam", "refund", "task_job", "trading_tip"]


@pytest.fixture(scope="module")
def small():
    df = generate(seed=3, per_scam_template=4, per_normal_template=4)
    vec, clf = lt.fit(df.text.tolist(), df.tag.tolist())
    return df, vec, clf


def test_char_wb_ngrams_match_scikit_learn():
    analyzer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), lowercase=False).build_analyzer()
    for t in TRICKY:
        assert lt.char_wb_ngrams(t, 2, 5) == analyzer(t), t


def test_vocabulary_has_no_characters_the_phone_would_split(small):
    _, vec, _ = small
    assert all(ord(ch) <= 0xFFFF for g in vec.vocabulary_ for ch in g)


@pytest.mark.parametrize("temperature", [1.0, 0.7, 1.8])
def test_exported_json_scores_like_scikit_learn_with_its_temperature(small, temperature):
    df, vec, clf = small
    model = lt.export(vec, clf, temperature)
    assert model["temperature"] == temperature and model["unclear_below"] == 0.6
    texts = df.text.sample(200, random_state=0).tolist() + TRICKY
    sk = lt._probs(clf.decision_function(vec.transform(texts)), temperature)
    js = np.array([lt.score_json(model, t)[2] for t in texts])
    assert np.abs(sk - js).max() < 1e-4
    if temperature == 1.0:  # T = 1 is plain scikit-learn
        assert np.abs(clf.predict_proba(vec.transform(texts)) - js).max() < 1e-4


def test_temperature_changes_confidence_not_the_ranking():
    model = {"classes": ["kyc", "normal"], "lowercase": True, "ngram_range": [2, 3], "vocabulary": {" k": 0},
             "idf": [1.0], "coef": [[2.0], [-2.0]], "intercept": [0.0, 0.0]}
    sharp = lt.score_json({**model, "temperature": 0.5}, "kyc")
    plain = lt.score_json(model, "kyc")  # no temperature: 1.0
    soft = lt.score_json({**model, "temperature": 4.0}, "kyc")
    assert sharp[0] == plain[0] == soft[0] == "kyc"
    assert sharp[1] > plain[1] > soft[1] > 0.5
    assert plain[1] == pytest.approx(1 / (1 + math.exp(-4.0)))
    assert soft[1] == pytest.approx(1 / (1 + math.exp(-1.0)))


def test_fit_temperature_recovers_a_known_temperature():
    rng = np.random.default_rng(0)
    logits = rng.normal(0, 3, size=(4000, 4))
    p = lt._probs(logits, 2.0)  # the true probabilities are the logits softened by T = 2
    y = np.array([rng.choice(4, p=row) for row in p])
    assert lt.fit_temperature(logits, y) == pytest.approx(2.0, rel=0.1)


def test_unclear_when_no_class_reaches_the_threshold():
    model = {"classes": SEVEN, "unclear_below": 0.6}
    # A decided class keeps its own name and probability.
    assert lt.decide(model, [0.7, 0.05, 0.1, 0.05, 0.05, 0.03, 0.02]) == ("arrest_threat", 0.7, "arrest_threat")
    assert lt.decide(model, [0.0, 0.0, 0.6, 0.4, 0.0, 0.0, 0.0]) == ("normal", 0.6, "normal")  # 0.6 reaches it
    # Below 0.6: "unclear", with the class it leaned to and that class's probability.
    assert lt.decide(model, [0.05, 0.35, 0.3, 0.0, 0.3, 0.0, 0.0]) == ("unclear", 0.35, "kyc")
    # Leaning to normal is still "unclear", never "normal" (rule 1: unknown is never safe).
    assert lt.decide(model, [0.1, 0.1, 0.59, 0.1, 0.11, 0.0, 0.0]) == ("unclear", 0.59, "normal")
    # Ties go to the first class, like Kotlin's maxBy.
    assert lt.decide(model, [0.3, 0.3, 0.2, 0.2, 0.0, 0.0, 0.0])[2] == "arrest_threat"
    # scam_hit is the same rule without the top class (backend/evalsuite/ai_lures.py uses it).
    assert lt.scam_hit(model, [0.05, 0.35, 0.3, 0.0, 0.3, 0.0, 0.0]) == ("unclear", 0.35)


def test_only_scam_classes_at_the_threshold_are_sent():
    assert lt.is_sent("other_scam", 0.6) and lt.is_sent("kyc", 0.99)
    assert not lt.is_sent("kyc", 0.59)
    assert not lt.is_sent("normal", 0.99)
    assert not lt.is_sent("unclear", 0.59) and not lt.is_sent("unclear", 0.9)
    assert lt.UNCLEAR_BELOW == lt.SEND_THRESHOLD == 0.6


def test_metrics_count_unclear_as_caught_but_never_as_sent():
    df = pd.DataFrame({"tag": ["kyc", "kyc", "normal", "normal"], "lang": ["en"] * 4, "text": [""] * 4})
    classes = sorted(CLASSES)
    k, n = classes.index("kyc"), classes.index("normal")
    probs = np.full((4, 7), 0.0)
    probs[0, k] = 1.0                      # scam, decided
    probs[1, k], probs[1, n] = 0.5, 0.5    # scam, unclear -> caught, not sent
    probs[2, n] = 1.0                      # normal, right
    probs[3, k], probs[3, n] = 0.45, 0.55  # normal, unclear
    m = lt.metrics(probs, df, classes)
    assert m["scam_caught"] == 1.0 and m["scam_sent"] == 0.5 and m["scam_unclear"] == 0.5
    assert m["normal_false_alarm"] == 0.0 and m["normal_unclear"] == 0.5


def test_corpus_rows_and_templates():
    df = generate(seed=3, per_scam_template=2, per_normal_template=2)
    assert set(df.tag) == set(CLASSES) and set(SCAM_TAGS) == set(CLASSES) - {"normal"}
    assert set(df.lang) == {"en", "hi", "hinglish"}
    assert df.synthetic.all() and df.template_id.notna().all()
    per_class = {c: len({i for i, (t, _, _) in enumerate(TEMPLATES) if t == c}) for c in CLASSES}
    assert all(per_class[c] >= 40 for c in SCAM_TAGS), per_class
    assert per_class["normal"] >= 150, per_class
    for _, g in df.groupby("template_id"):
        assert g.tag.nunique() == 1 and g.lang.nunique() == 1


def test_made_up_numbers_look_made_up():
    import random
    r = random.Random(0)
    for _ in range(50):
        phone = _fill("{phone}", "en", r)
        assert re.fullmatch(r"(\+91 |0)?\d{2}0000\d{4}", phone), phone


def test_shipped_corpus_is_mostly_normal():
    if not CORPUS.exists():
        pytest.skip("run python -m model.lure_corpus first")
    df = pd.read_csv(CORPUS, keep_default_na=False)
    assert len(df) >= 20_000 and (df.tag == "normal").mean() >= 0.55


def _shipped():
    if not (lt.ARTIFACTS / "lure.json").exists():
        pytest.skip("run python -m model.lure_train first")
    model = json.loads((lt.ARTIFACTS / "lure.json").read_text(encoding="utf-8"))
    vectors = json.loads((lt.ARTIFACTS / "lure_vectors.json").read_text(encoding="utf-8"))
    return model, vectors


def test_shipped_model_is_lure_0_2_with_calibration_and_the_unclear_rule():
    model, _ = _shipped()
    assert model["version"] == "lure-0.2"
    assert model["classes"] == SEVEN
    assert model["unclear_below"] == lt.SEND_THRESHOLD
    assert 0.1 < model["temperature"] < 10


def test_shipped_vectors_match_the_shipped_model():
    model, vectors = _shipped()
    assert (vectors["version"], vectors["classes"]) == (model["version"], model["classes"])
    assert (vectors["temperature"], vectors["unclear_below"]) == (model["temperature"], model["unclear_below"])
    for v in vectors["vectors"]:
        top, top_conf, probs = lt.score_json(model, v["text"])
        tag, conf, top2 = lt.decide(model, probs)
        assert (tag, top2) == (v["tag"], v["top"]) and top2 == top, v["text"]
        assert abs(conf - v["conf"]) < 1e-6 and conf == top_conf
        assert np.abs(np.array(probs) - v["probs"]).max() < 1e-6
    tags = {v["tag"] for v in vectors["vectors"]}
    assert {"unclear", "other_scam", "normal"} <= tags
    assert any(v["tag"] == "unclear" and v["top"] != "normal" for v in vectors["vectors"])
    assert all(v["conf"] < 0.6 for v in vectors["vectors"] if v["tag"] == "unclear")


def test_metrics_report_the_acceptance_numbers():
    if not (lt.ARTIFACTS / "lure_metrics.json").exists():
        pytest.skip("run python -m model.lure_train first")
    m = json.loads((lt.ARTIFACTS / "lure_metrics.json").read_text(encoding="utf-8"))
    acc = m["held_out_templates"]["acceptance"]
    assert set(acc) == {"normal_false_alarm", "scam_caught", "normal_unclear", "refund_f1"}
    assert set(m["held_out_templates"]["by_language"]) == {"en", "hi", "hinglish"}
    assert set(m["held_out_templates"]["per_class_f1"]) == set(CLASSES)
