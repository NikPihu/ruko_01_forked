"""lure.json must score exactly like scikit-learn, and the shipped vectors must match the shipped JSON."""
import json

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer

from model import lure_train as lt
from model.lure_corpus import generate

TRICKY = ["Hello   world", "a", "आप डिजिटल अरेस्ट में हैं।", "ok ok", " leading and trailing ",
          "Part time job", "x\ty\nz", "😀 emoji 😀", ""]


def test_char_wb_ngrams_match_scikit_learn():
    analyzer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), lowercase=False).build_analyzer()
    for t in TRICKY:
        assert lt.char_wb_ngrams(t, 2, 5) == analyzer(t), t


def test_vocabulary_has_no_characters_the_phone_would_split():
    df = generate(seed=3, per_scam_template=4, per_normal_template=6)
    vec, _ = lt.fit(df.text.tolist(), df.tag.tolist())
    assert all(ord(ch) <= 0xFFFF for g in vec.vocabulary_ for ch in g)


def test_exported_json_scores_like_scikit_learn():
    df = generate(seed=3, per_scam_template=4, per_normal_template=6)
    vec, clf = lt.fit(df.text.tolist(), df.tag.tolist())
    model = lt.export(vec, clf)
    texts = df.text.sample(200, random_state=0).tolist() + TRICKY
    sk = clf.predict_proba(vec.transform(texts))
    js = np.array([lt.score_json(model, t)[2] for t in texts])
    assert np.abs(sk - js).max() < 1e-4


def test_scam_hit_reports_total_scam_probability():
    model = {"classes": ["arrest_threat", "kyc", "normal", "refund"]}
    assert lt.scam_hit(model, [0.05, 0.35, 0.3, 0.3]) == ("kyc", pytest.approx(0.7))
    assert lt.scam_hit(model, [0.1, 0.1, 0.7, 0.1]) == ("normal", 0.7)


def test_shipped_vectors_match_the_shipped_model():
    if not (lt.ARTIFACTS / "lure.json").exists():
        pytest.skip("run python -m model.lure_train first")
    model = json.loads((lt.ARTIFACTS / "lure.json").read_text(encoding="utf-8"))
    vectors = json.loads((lt.ARTIFACTS / "lure_vectors.json").read_text(encoding="utf-8"))
    assert (vectors["version"], vectors["classes"]) == (model["version"], model["classes"])
    for v in vectors["vectors"]:
        tag, conf, probs = lt.score_json(model, v["text"])
        assert tag == v["tag"] and abs(conf - v["conf"]) < 1e-6
        assert lt.scam_hit(model, probs)[0] == v["scam_tag"]
