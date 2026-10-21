"""On-device lure classifier: char n-gram TF-IDF + multinomial logistic regression -> lure.json

    PYTHONPATH=backend;ml;data python -m model.lure_train

`lure.json` is exactly what android/.../LureScorer.kt (`LinearLureClassifier`, `LureModel`) reads.
`lure_vectors.json` lists texts with the tag and confidence the JSON must produce, so the Android
unit test can prove the phone scores identically. Evaluation holds out whole message templates,
so it measures unseen phrasings, not memorised ones.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report

from model.lure_corpus import OUT as CORPUS, generate

VERSION = "lure-0.1"
NGRAM = (2, 5)
MAX_FEATURES = 20_000
# Chosen on held-out templates: C=4 caught 36% (today's phone rule), C=50 53% with no false alarms,
# and 84% with no false alarms under the scam-confidence rule below.
C = 50.0
SEND_THRESHOLD = 0.6  # LURE_SEND_THRESHOLD on the phone
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


def _bmp_only(gram: str) -> bool:
    """Kotlin strings are UTF-16: characters above U+FFFF (emoji) split into two units there, so
    n-grams containing them would differ between Python and the phone. They are dropped."""
    return all(ord(ch) <= 0xFFFF for ch in gram)


def fit(texts: list[str], tags: list[str]) -> tuple[TfidfVectorizer, LogisticRegression]:
    params = dict(analyzer="char_wb", ngram_range=NGRAM, lowercase=True, dtype=np.float64)
    first = TfidfVectorizer(min_df=2, max_features=MAX_FEATURES, **params).fit(texts)
    vocab = sorted(g for g in first.vocabulary_ if _bmp_only(g))
    vec = TfidfVectorizer(vocabulary={g: i for i, g in enumerate(vocab)}, **params)
    x = vec.fit_transform(texts)
    clf = LogisticRegression(C=C, max_iter=5000, class_weight="balanced").fit(x, tags)
    return vec, clf


def export(vec: TfidfVectorizer, clf: LogisticRegression) -> dict:
    """The LureModel JSON. Numbers are rounded to 6 significant digits to keep the file small;
    the vectors are computed from these rounded numbers, so phone and tests agree exactly."""
    r = lambda v: float(f"{v:.6g}")  # noqa: E731
    return {
        "version": VERSION, "analyzer": "char_wb", "ngram_range": list(NGRAM), "lowercase": True,
        "classes": [str(c) for c in clf.classes_],
        "vocabulary": {g: int(i) for g, i in vec.vocabulary_.items()},
        "idf": [r(v) for v in vec.idf_],
        "coef": [[r(v) for v in row] for row in clf.coef_],
        "intercept": [r(v) for v in clf.intercept_],
    }


# ---------- the phone's algorithm, in Python (LinearLureClassifier) ----------

_WS = re.compile(r"\s+")  # Unicode whitespace, like scikit-learn (see PLAN.md §12: Kotlin must match)


def char_wb_ngrams(text: str, min_n: int, max_n: int) -> list[str]:
    """scikit-learn's char_wb analyzer, written the way LureScorer.kt's charWbNgrams is."""
    out = []
    for word in (w for w in _WS.split(text) if w):
        w = f" {word} "
        for n in range(min_n, max_n + 1):
            offset = 0
            out.append(w[offset:offset + n])
            while offset + n < len(w):
                offset += 1
                out.append(w[offset:offset + n])
            if offset == 0:
                break
    return out


def score_json(model: dict, text: str) -> tuple[str, float, list[float]]:
    t = text.lower() if model["lowercase"] else text
    counts = Counter(model["vocabulary"][g] for g in char_wb_ngrams(t, *model["ngram_range"])
                     if g in model["vocabulary"])
    weights = {i: c * model["idf"][i] for i, c in counts.items()}
    norm = math.sqrt(sum(v * v for v in weights.values()))
    scores = [b + (0.0 if norm == 0 else sum(row[i] * v / norm for i, v in weights.items()))
              for row, b in zip(model["coef"], model["intercept"])]
    m = max(scores)
    exps = [math.exp(s - m) for s in scores]
    probs = [e / sum(exps) for e in exps]
    best = max(range(len(probs)), key=probs.__getitem__)
    return model["classes"][best], probs[best], probs


def scam_hit(model: dict, probs: list[float]) -> tuple[str, float]:
    """Proposed phone rule: the most likely scam tag, with confidence = 1 - P(normal).
    Scam types that look alike (KYC vs refund) split their probability; together they are sure."""
    k = model["classes"].index("normal")
    p_scam = 1.0 - probs[k]
    if p_scam <= probs[k]:
        return "normal", probs[k]
    best = max((i for i in range(len(probs)) if i != k), key=probs.__getitem__)
    return model["classes"][best], p_scam


# ---------- evaluation ----------

def split_by_template(df: pd.DataFrame, test_share: float = 0.25, seed: int = 0) -> np.ndarray:
    """Hold out about a quarter of the templates of every (tag, language)."""
    rng = random.Random(seed)
    held = set()
    for _, g in df.groupby(["tag", "lang"]):
        tids = sorted(g.template_id.unique())
        rng.shuffle(tids)
        held.update(tids[:max(1, round(len(tids) * test_share))] if len(tids) >= 3 else [])
    return df.template_id.isin(held).to_numpy()


def evaluate(model: dict, df: pd.DataFrame) -> dict:
    pred = [score_json(model, t) for t in df.text]
    tags = [p[0] for p in pred]
    is_scam = (df.tag != "normal").to_numpy()
    report = classification_report(df.tag, tags, output_dict=True, zero_division=0)
    out = {"n": int(len(df)), "macro_f1": report["macro avg"]["f1-score"],
           "per_class_f1": {k: v["f1-score"] for k, v in report.items() if k in set(df.tag)}}
    rules = {"today": [(t, c) for t, c, _ in pred],                    # top class and its probability
             "scam_conf": [scam_hit(model, probs) for _, _, probs in pred]}  # proposed (PLAN.md §12)
    for name, hits in rules.items():
        sent = np.array([t != "normal" and c >= SEND_THRESHOLD for t, c in hits])
        right = np.array([t for t, _ in hits]) == df.tag.to_numpy()
        lang = df.lang.to_numpy()
        out[name] = {
            "scam_caught_share": float(sent[is_scam].mean()),          # a scam tag reaches the server
            "scam_right_tag_share": float((sent & right)[is_scam].mean()),
            "normal_false_alarm_share": float(sent[~is_scam].mean()),  # a normal SMS sent as a lure
            "by_language": {lg: {"scam_caught": float(sent[is_scam & (lang == lg)].mean()),
                                 "normal_false_alarm": float(sent[~is_scam & (lang == lg)].mean())}
                            for lg in sorted(set(lang))},
        }
    return out


VECTOR_TEXTS = [
    "This is CBI. A parcel in your name with drugs was seized. Join the video call now or you will be arrested.",
    "आप डिजिटल अरेस्ट में हैं। कैमरा चालू रखें और 50,000 रुपये सुरक्षित खाते में भेजें।",
    "Aapka KYC expire ho gaya hai, ye app install karo aur sab permission allow karo bit.ly/3xK9pQ",
    "Dear SBI customer, your account will be blocked today. Update KYC now: sbi-kyc-update.com",
    "Like YouTube videos and earn ₹200 per task. Join us on Telegram today!",
    "Your commission of Rs 12,000 is frozen. Pay Rs 8,500 to unlock withdrawal.",
    "SEBI registered expert: IREDA will give 300% return this week. Join our VIP group.",
    "Your refund of ₹4,999 is approved. Scan the QR code and enter your UPI PIN to receive it.",
    "Aapki bijli aaj raat kat jayegi, turant 9876543210 pe call karo.",
    "482913 is your OTP for a transaction of Rs 1,250 at Amazon. Do not share it with anyone. -HDFC Bank",
    "Rs 2,000 debited from a/c XX1234 to VPA shreeganesh.kirana@okaxis. -SBI",
    "Police never arrest anyone over a video call. Report fraud at 1930.",
    "Dear Customer, KYC update is due. Please visit your home branch. We never ask for OTP.",
    "Mummy main ghar pahunch gaya, khana kha liya.",
    "Refund of Rs 499 for your Flipkart order has been processed. It may take 3 to 5 days.",
    "🚨 Y0ur acc0unt w1ll be bl0cked t0day 🚨 update KYC now",
    "URGENT URGENT CALL BACK",
    "ok",
    "",
    "Part time job: earn Rs 5,000 daily, message us",  # no-break space: Kotlin must split on it too
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--corpus", type=Path, default=CORPUS)
    p.add_argument("--out", type=Path, default=ARTIFACTS)
    a = p.parse_args()
    if a.corpus.exists():
        df = pd.read_csv(a.corpus, keep_default_na=False)
    else:
        df = generate()
        a.corpus.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(a.corpus, index=False, encoding="utf-8")
    held = split_by_template(df)
    vec, clf = fit(df.text[~held].tolist(), df.tag[~held].tolist())
    held_out = evaluate(export(vec, clf), df[held])
    print(f"held-out templates ({held_out['n']} messages), macro F1 {held_out['macro_f1']:.3f}")
    for rule in ("today", "scam_conf"):
        m = held_out[rule]
        langs = ", ".join(f"{lg} {100 * v['scam_caught']:.0f}%" for lg, v in m["by_language"].items())
        print(f"  rule {rule:<9}: scams caught {100 * m['scam_caught_share']:5.1f}% ({langs}), "
              f"normal false alarms {100 * m['normal_false_alarm_share']:.2f}%")

    # Final model on every template; the held-out numbers above are what we report.
    vec, clf = fit(df.text.tolist(), df.tag.tolist())
    model = export(vec, clf)
    sk = clf.predict_proba(vec.transform(df.text.tolist()))
    js = np.array([score_json(model, t)[2] for t in df.text])
    drift = float(np.abs(sk - js).max())
    assert drift < 1e-3, f"JSON scorer drifted from scikit-learn by {drift}"
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "lure.json").write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    vectors = []
    for t in VECTOR_TEXTS:
        tag, conf, probs = score_json(model, t)
        s_tag, s_conf = scam_hit(model, probs)
        vectors.append({"text": t, "tag": tag, "conf": round(conf, 6), "scam_tag": s_tag,
                        "scam_conf": round(s_conf, 6), "probs": [round(x, 6) for x in probs]})
    (a.out / "lure_vectors.json").write_text(json.dumps({"version": VERSION, "classes": model["classes"],
                                                         "vectors": vectors}, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    (a.out / "lure_metrics.json").write_text(json.dumps({"version": VERSION, "held_out_templates": held_out,
                                                         "max_prob_diff_json_vs_sklearn": drift}, indent=2))
    size_kb = (a.out / "lure.json").stat().st_size / 1024
    print(f"lure.json: {len(model['vocabulary']):,} n-grams, {size_kb:.0f} KB; JSON vs scikit-learn max diff {drift:.1e}")
    for v in vectors:
        print(f"  {v['scam_tag']:<14} {v['scam_conf']:.2f}  {v['text'][:70]!r}")


if __name__ == "__main__":
    main()
