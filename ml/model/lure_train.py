"""On-device lure classifier: char n-gram TF-IDF + multinomial logistic regression -> lure.json

    PYTHONPATH=backend;ml;data python -m model.lure_train

`lure.json` is exactly what android/.../LureScorer.kt (`LinearLureClassifier`, `LureModel`) reads.
`lure_vectors.json` lists texts with the answer the JSON must produce, so the Android unit test can
prove the phone scores identically.

lure-0.2:
- classes: the five scam tags, `other_scam` and `normal`;
- calibration: one temperature T (softmax(scores / T)), fitted on out-of-fold scores of held-out
  templates, so a probability of 0.6 means the same for every class;
- the decision (`decide`): the top class when its calibrated probability reaches 0.6
  (`UNCLEAR_BELOW`, the same number as the send threshold), else `unclear`, which keeps the top
  class and its probability so the caller can see what it leaned to. "Not sure" is never
  reported as `normal` (CLAUDE.md rule 1).

Evaluation holds out whole message templates (unseen phrasings). C and T are chosen by grouped
cross-validation on the development templates only; the test templates are scored once.
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
from joblib import Parallel, delayed
from scipy.optimize import minimize_scalar
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score

from model.lure_corpus import CLASSES, OUT as CORPUS, SCAM_TAGS, generate

VERSION = "lure-0.2"
NGRAM = (2, 5)
MAX_FEATURES = 20_000
C_GRID = (5.0, 10.0, 20.0, 50.0, 100.0)
WEIGHT_GRID = ("balanced", None)  # class_weight: balanced (plan default) or the corpus's own shares
C = 20.0               # default for fit(); main() chooses C and the weighting on held-out templates
FOLDS = 4
SEND_THRESHOLD = 0.6   # LURE_SEND_THRESHOLD on the phone, contracts/watch_rules.json lure_min_conf
UNCLEAR_BELOW = SEND_THRESHOLD  # no class reaches this -> "unclear"
NORMAL, UNCLEAR = "normal", "unclear"
TARGETS = {  # acceptance on held-out templates (docs/plan-v3.md step 1)
    "normal_false_alarm_max": 0.005, "scam_caught_min": 0.85, "normal_unclear_max": 0.03, "refund_f1_min": 0.6,
}
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


def _bmp_only(gram: str) -> bool:
    """Kotlin strings are UTF-16: characters above U+FFFF (emoji) split into two units there, so
    n-grams containing them would differ between Python and the phone. They are dropped."""
    return all(ord(ch) <= 0xFFFF for ch in gram)


def fit(texts: list[str], tags: list[str], c: float | None = None,
        class_weight: str | dict | None = "balanced") -> tuple[TfidfVectorizer, LogisticRegression]:
    params = dict(analyzer="char_wb", ngram_range=NGRAM, lowercase=True, dtype=np.float64)
    first = TfidfVectorizer(min_df=2, max_features=MAX_FEATURES, **params).fit(texts)
    vocab = sorted(g for g in first.vocabulary_ if _bmp_only(g))
    vec = TfidfVectorizer(vocabulary={g: i for i, g in enumerate(vocab)}, **params)
    x = vec.fit_transform(texts)
    clf = LogisticRegression(C=C if c is None else c, max_iter=5000, class_weight=class_weight).fit(x, tags)
    return vec, clf


def export(vec: TfidfVectorizer, clf: LogisticRegression, temperature: float = 1.0) -> dict:
    """The LureModel JSON. Numbers are rounded to 6 significant digits to keep the file small;
    the vectors are computed from these rounded numbers, so phone and tests agree exactly."""
    r = lambda v: float(f"{v:.6g}")  # noqa: E731
    return {
        "version": VERSION, "analyzer": "char_wb", "ngram_range": list(NGRAM), "lowercase": True,
        "classes": [str(c) for c in clf.classes_],
        "temperature": r(temperature), "unclear_below": UNCLEAR_BELOW,
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


def _softmax(scores: list[float], temperature: float = 1.0) -> list[float]:
    z = [s / temperature for s in scores]
    m = max(z)
    exps = [math.exp(s - m) for s in z]
    total = sum(exps)
    return [e / total for e in exps]


def raw_scores(model: dict, text: str) -> list[float]:
    """coef . tfidf(text) + intercept, per class (scikit-learn's decision_function)."""
    t = text.lower() if model["lowercase"] else text
    counts = Counter(model["vocabulary"][g] for g in char_wb_ngrams(t, *model["ngram_range"])
                     if g in model["vocabulary"])
    weights = {i: c * model["idf"][i] for i, c in counts.items()}
    norm = math.sqrt(sum(v * v for v in weights.values()))
    return [b + (0.0 if norm == 0 else sum(row[i] * v / norm for i, v in weights.items()))
            for row, b in zip(model["coef"], model["intercept"])]


def score_json(model: dict, text: str) -> tuple[str, float, list[float]]:
    """The top class, its probability and every class's calibrated probability (classes order)."""
    probs = _softmax(raw_scores(model, text), model.get("temperature", 1.0))
    best = max(range(len(probs)), key=probs.__getitem__)
    return model["classes"][best], probs[best], probs


def decide(model: dict, probs: list[float]) -> tuple[str, float, str]:
    """(tag, conf, top). The top class when its probability reaches `unclear_below` (0.6), else
    `unclear` with the top class's probability; `top` is always the most likely class. The phone's
    `LinearLureClassifier.decide` is the same rule."""
    best = max(range(len(probs)), key=probs.__getitem__)  # first of equals, like Kotlin's maxBy
    top, conf = model["classes"][best], probs[best]
    return (top if conf >= model.get("unclear_below", UNCLEAR_BELOW) else UNCLEAR), conf, top


def scam_hit(model: dict, probs: list[float]) -> tuple[str, float]:
    """The phone's answer for a message: (tag, conf) from `decide` (tag may be `unclear`; it is
    sent only when it is a scam tag with conf >= SEND_THRESHOLD, which `unclear` never reaches)."""
    tag, conf, _ = decide(model, probs)
    return tag, conf


def is_sent(tag: str, conf: float) -> bool:
    """What leaves the phone as a lure tag: a scam class at or above the send threshold."""
    return tag not in (NORMAL, UNCLEAR) and conf >= SEND_THRESHOLD


# ---------- calibration ----------

def fit_temperature(scores: np.ndarray, y: np.ndarray) -> float:
    """One temperature minimising the log loss of softmax(scores / T) on held-out scores."""
    def nll(log_t: float) -> float:
        z = scores / math.exp(log_t)
        z = z - z.max(axis=1, keepdims=True)
        logp = z - np.log(np.exp(z).sum(axis=1, keepdims=True))
        return float(-logp[np.arange(len(y)), y].mean())
    res = minimize_scalar(nll, bounds=(math.log(0.05), math.log(20.0)), method="bounded")
    return float(math.exp(res.x))


def _probs(scores: np.ndarray, temperature: float) -> np.ndarray:
    z = scores / temperature
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def log_loss(probs: np.ndarray, y: np.ndarray) -> float:
    return float(-np.log(np.clip(probs[np.arange(len(y)), y], 1e-15, 1)).mean())


def ece(probs: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error of the top-class probability."""
    conf, pred = probs.max(axis=1), probs.argmax(axis=1)
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs((pred[m] == y[m]).mean() - conf[m].mean())
    return float(total)


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


def template_folds(df: pd.DataFrame, k: int = FOLDS, seed: int = 1) -> np.ndarray:
    """A fold number per row; every template sits in one fold, every (tag, language) is spread."""
    rng = random.Random(seed)
    fold_of: dict[int, int] = {}
    for _, g in df.groupby(["tag", "lang"]):
        tids = sorted(g.template_id.unique())
        rng.shuffle(tids)
        start = rng.randrange(k)
        fold_of.update({t: (start + i) % k for i, t in enumerate(tids)})
    return df.template_id.map(fold_of).to_numpy()


def _fold_scores(df: pd.DataFrame, train: np.ndarray, c: float, cw: str | None, classes: list[str]) -> np.ndarray:
    vec, clf = fit(df.text[train].tolist(), df.tag[train].tolist(), c, cw)
    assert list(clf.classes_) == classes
    return clf.decision_function(vec.transform(df.text[~train].tolist()))


Setting = tuple[float, "str | None"]  # (C, class_weight)


def oof_scores(df: pd.DataFrame, settings: list[Setting], k: int = FOLDS) -> dict[Setting, np.ndarray]:
    """Out-of-fold decision scores per setting, every row scored by a model that never saw its template."""
    folds = template_folds(df, k)
    classes = sorted(df.tag.unique())
    jobs = [(st, f) for st in settings for f in range(k)]
    res = Parallel(n_jobs=min(len(jobs), 8))(delayed(_fold_scores)(df, folds != f, *st, classes) for st, f in jobs)
    out = {st: np.zeros((len(df), len(classes))) for st in settings}
    for (st, f), s in zip(jobs, res):
        out[st][folds == f] = s
    return out


def decisions(probs: np.ndarray, classes: list[str], unclear_below: float = UNCLEAR_BELOW) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    best = probs.argmax(axis=1)
    conf = probs[np.arange(len(probs)), best]
    top = np.array(classes)[best]
    tag = np.where(conf >= unclear_below, top, UNCLEAR)
    return tag, conf, top


def metrics(probs: np.ndarray, df: pd.DataFrame, classes: list[str]) -> dict:
    """Acceptance numbers for one set of calibrated probabilities (`unclear` counts as wrong for F1)."""
    tag, conf, top = decisions(probs, classes)
    truth = df.tag.to_numpy()
    lang = df.lang.to_numpy()
    is_scam = truth != NORMAL
    sent = np.array([is_sent(t, c) for t, c in zip(tag, conf)])
    unclear = tag == UNCLEAR

    def block(m: np.ndarray) -> dict:
        s, n = m & is_scam, m & ~is_scam
        return {
            "messages": int(m.sum()),
            "scam_caught": float((sent | unclear)[s].mean()),   # a scam tag, or "unclear"
            "scam_sent": float(sent[s].mean()),                  # a scam tag at >= 0.6 (what the phone reports)
            "scam_right_tag": float((tag == truth)[s].mean()),
            "scam_unclear": float(unclear[s].mean()),
            "scam_called_normal": float((tag == NORMAL)[s].mean()),
            "normal_false_alarm": float(sent[n].mean()),        # normal -> any scam class
            "normal_unclear": float(unclear[n].mean()),
        }
    labels = list(CLASSES)
    f1 = f1_score(truth, tag, labels=labels, average=None, zero_division=0)
    out = {**block(np.ones(len(df), bool)),
           "macro_f1": float(np.mean(f1)),
           "per_class_f1": {c: float(v) for c, v in zip(labels, f1)},
           "by_language": {lg: block(lang == lg) for lg in sorted(set(lang))}}
    # Does 0.6 mean the same for every class? Precision of each class's confident answers.
    out["precision_at_threshold"] = {
        c: (float((truth[tag == c] == c).mean()) if (tag == c).any() else None) for c in labels}
    y = np.array([classes.index(t) for t in truth])
    out["log_loss"], out["ece"] = log_loss(probs, y), ece(probs, y)
    return out


def acceptance(m: dict) -> dict:
    checks = {
        "normal_false_alarm": (m["normal_false_alarm"], "<=", TARGETS["normal_false_alarm_max"]),
        "scam_caught": (m["scam_caught"], ">=", TARGETS["scam_caught_min"]),
        "normal_unclear": (m["normal_unclear"], "<=", TARGETS["normal_unclear_max"]),
        "refund_f1": (m["per_class_f1"]["refund"], ">=", TARGETS["refund_f1_min"]),
    }
    return {k: {"value": v, "target": f"{op} {t}", "met": bool(v <= t if op == "<=" else v >= t)}
            for k, (v, op, t) in checks.items()}


def choose_setting(df: pd.DataFrame, cs: tuple[float, ...] = C_GRID,
                   weights: tuple = WEIGHT_GRID) -> tuple[Setting, float, dict[Setting, dict]]:
    """C, class weighting and the temperature from out-of-fold scores on the development templates
    only: the setting that meets the most acceptance targets, then the best macro F1."""
    classes = sorted(df.tag.unique())
    y = np.array([classes.index(t) for t in df.tag])
    table = {}
    for st, s in oof_scores(df, [(c, w) for w in weights for c in cs]).items():
        t = fit_temperature(s, y)
        m = metrics(_probs(s, t), df, classes)
        table[st] = {"temperature": t, "macro_f1": m["macro_f1"], "scam_caught": m["scam_caught"],
                     "normal_false_alarm": m["normal_false_alarm"], "normal_unclear": m["normal_unclear"],
                     "refund_f1": m["per_class_f1"]["refund"], "log_loss": m["log_loss"],
                     "targets_met": sum(v["met"] for v in acceptance(m).values())}
    best = max(table, key=lambda st: (table[st]["targets_met"], table[st]["macro_f1"]))
    return best, table[best]["temperature"], table


VECTOR_TEXTS = [
    "This is CBI. A parcel in your name with drugs was seized. Join the video call now or you will be arrested.",
    "आप डिजिटल अरेस्ट में हैं। कैमरा चालू रखें और 50,000 रुपये सुरक्षित खाते में भेजें।",
    "Aapka KYC expire ho gaya hai, ye app install karo aur sab permission allow karo short.example/Rk7Tq",
    "Dear SBI customer, your account will be blocked today. Update KYC now: sbi-kyc-update.example",
    "Like YouTube videos and earn ₹200 per task. Join us on Telegram today!",
    "Your commission of Rs 12,000 is frozen. Pay Rs 8,500 to unlock withdrawal.",
    "SEBI registered expert: IREDA will give 300% return this week. Join our VIP group.",
    "Your refund of ₹4,999 is approved. Scan the QR code and enter your UPI PIN to receive it.",
    "Aapki bijli aaj raat kat jayegi, turant 9800001234 pe call karo.",
    "Your parcel is held at the warehouse. Pay Rs 25 redelivery fee within 24 hours: parcel-redeliver.example/fee",
    "Congratulations! Your number won Rs 25,00,000 in the KBC lucky draw. Pay the processing tax to claim it.",
    "Your loan of Rs 50,000 is approved without CIBIL. Pay Rs 1,999 processing fee to get the money now.",
    "I have recorded your video call. Pay Rs 20,000 in one hour or I send it to your family.",
    "482913 is your OTP for a transaction of Rs 1,250 at Amazon. Do not share it with anyone. -HDFC Bank",
    "Rs 2,000 debited from a/c XX1234 to VPA shreeganesh.kirana@okaxis. -SBI",
    "Police never arrest anyone over a video call. Report fraud at 1930.",
    "Dear Customer, KYC update is due. Please visit your home branch. We never ask for OTP.",
    "Mummy main ghar pahunch gaya, khana kha liya.",
    "Refund of Rs 499 for your Flipkart order has been processed. It may take 3 to 5 days.",
    "🚨 Y0ur acc0unt w1ll be bl0cked t0day 🚨 update KYC now",
    "URGENT URGENT CALL BACK",
    "Please call me back when you can",
    "ok",
    "",
    "Part time job: earn Rs 5,000 daily, message us",  # no-break space: Kotlin must split on it too
]
MARGIN = 1e-4  # a vector this close to 0.6 could flip on float noise; such texts are not used


def make_vectors(model: dict, extra: list[str]) -> list[dict]:
    out = []
    for t in VECTOR_TEXTS + extra:
        top, top_conf, probs = score_json(model, t)
        tag, conf, top2 = decide(model, probs)
        assert top2 == top and conf == top_conf
        if abs(conf - model["unclear_below"]) < MARGIN:
            continue
        out.append({"text": t, "tag": tag, "conf": round(conf, 6), "top": top, "probs": [round(x, 6) for x in probs]})
    return out


AMBIGUOUS = [  # not in the corpus; short or mixed messages the model should not be sure about
    "Please call me back when you can, it is about your account",
    "Your parcel and your bank account both need attention today",
    "Sir payment pending hai, jaldi kar do",
    "Kindly confirm the amount and the details by evening",
    "आपका काम हो गया, बाकी पैसे कल भेज देना",
    "Refund and KYC both pending, call us",
    "Bonus credited, check your app for the next step",
]


def _vector_extras(model: dict, df: pd.DataFrame, n_unclear: int = 4, n_other: int = 2) -> list[str]:
    """Texts so the vectors surely hold `unclear` answers (leaning to different classes) and
    `other_scam` answers: hand-written ambiguous texts, then halves of two messages of different
    classes glued together, then corpus texts for `other_scam`. Deterministic."""
    def answer(t: str) -> tuple[str, float, str]:
        return decide(model, score_json(model, t)[2])
    picks, tops = [], set()

    def take_unclear(t: str) -> None:
        tag, conf, top = answer(t)
        if tag == UNCLEAR and top not in tops and abs(conf - model["unclear_below"]) >= MARGIN and len(tops) < n_unclear:
            picks.append(t)
            tops.add(top)
    for t in AMBIGUOUS:
        take_unclear(t)
    rng = random.Random(5)
    by_class = {c: g.text.tolist() for c, g in df.groupby("tag")}
    for _ in range(2000):
        if len(tops) >= n_unclear:
            break
        c1, c2 = rng.sample(sorted(by_class), 2)
        a, b = rng.choice(by_class[c1]), rng.choice(by_class[c2])
        take_unclear(a[: len(a) // 2].rstrip() + " " + b[len(b) // 2:].lstrip())
    for t in by_class.get("other_scam", []):
        if n_other <= 0:
            break
        tag, conf, _ = answer(t)
        if tag == "other_scam" and abs(conf - model["unclear_below"]) >= MARGIN and t not in VECTOR_TEXTS:
            picks.append(t)
            n_other -= 1
    return picks


def _pct(v: float) -> str:
    return f"{100 * v:.1f}%"


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
    classes = sorted(df.tag.unique())
    assert set(classes) == set(CLASSES), classes
    held = split_by_template(df)
    dev, test = df[~held].reset_index(drop=True), df[held].reset_index(drop=True)
    print(f"corpus {len(df):,} messages ({_pct((df.tag == NORMAL).mean())} normal), {df.template_id.nunique()} templates; "
          f"test {len(test):,} messages from {test.template_id.nunique()} held-out templates")

    # 1. C, class weighting and T by grouped cross-validation on the development templates only.
    (c_best, cw_best), t_dev, table = choose_setting(dev)
    for (c, w), v in table.items():
        print(f"  C={c:<5g} {str(w):<8} T={v['temperature']:.3f} macro F1 {v['macro_f1']:.3f} caught {_pct(v['scam_caught'])} "
              f"normal FA {_pct(v['normal_false_alarm'])} normal unclear {_pct(v['normal_unclear'])} "
              f"refund F1 {v['refund_f1']:.2f} targets met {v['targets_met']}{'  <- chosen' if (c, w) == (c_best, cw_best) else ''}")

    # 2. One model on every development template, scored once on the held-out test templates.
    vec, clf = fit(dev.text.tolist(), dev.tag.tolist(), c_best, cw_best)
    test_scores = clf.decision_function(vec.transform(test.text.tolist()))
    held_out = metrics(_probs(test_scores, t_dev), test, classes)
    uncal = metrics(_probs(test_scores, 1.0), test, classes)
    held_out["uncalibrated"] = {k: uncal[k] for k in ("log_loss", "ece", "scam_caught", "normal_false_alarm",
                                                      "normal_unclear", "macro_f1", "precision_at_threshold")}
    held_out["acceptance"] = acceptance(held_out)
    print(f"held-out templates ({held_out['messages']:,} messages), C={c_best:g}, class_weight={cw_best}, T={t_dev:.3f}: macro F1 {held_out['macro_f1']:.3f}, "
          f"log loss {uncal['log_loss']:.3f} -> {held_out['log_loss']:.3f}, ECE {uncal['ece']:.3f} -> {held_out['ece']:.3f}")
    for k, v in held_out["acceptance"].items():
        print(f"  {k:<20} {v['value']:.4f} (target {v['target']}) {'met' if v['met'] else 'MISSED'}")
    print(f"  scam sent as a scam tag {_pct(held_out['scam_sent'])}, right tag {_pct(held_out['scam_right_tag'])}, "
          f"unclear {_pct(held_out['scam_unclear'])}, called normal {_pct(held_out['scam_called_normal'])}")
    print("  per-class F1: " + ", ".join(f"{c} {v:.2f}" for c, v in held_out["per_class_f1"].items()))
    print("  precision at >= 0.6: " + ", ".join(f"{c} {'-' if v is None else f'{v:.2f}'}"
                                              for c, v in held_out["precision_at_threshold"].items()))
    for lg, v in held_out["by_language"].items():
        print(f"  {lg:<9} caught {_pct(v['scam_caught'])} (sent {_pct(v['scam_sent'])}), normal FA {_pct(v['normal_false_alarm'])}, "
              f"normal unclear {_pct(v['normal_unclear'])}")

    # 3. The shipped model: every template, same C; T from out-of-fold scores over every template.
    y_all = np.array([classes.index(t) for t in df.tag])
    t_all = fit_temperature(oof_scores(df, [(c_best, cw_best)])[(c_best, cw_best)], y_all)
    vec, clf = fit(df.text.tolist(), df.tag.tolist(), c_best, cw_best)
    model = export(vec, clf, t_all)
    sample = df.text.sample(3000, random_state=0).tolist()
    sk = _probs(clf.decision_function(vec.transform(sample)), model["temperature"])
    js = np.array([score_json(model, t)[2] for t in sample])
    drift = float(np.abs(sk - js).max())
    assert drift < 1e-3, f"JSON scorer drifted from scikit-learn by {drift}"
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "lure.json").write_text(json.dumps(model, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    vectors = make_vectors(model, _vector_extras(model, df))
    tags = Counter(v["tag"] for v in vectors)
    assert tags[UNCLEAR] and tags["other_scam"], tags
    (a.out / "lure_vectors.json").write_text(json.dumps({
        "version": VERSION, "classes": model["classes"], "temperature": model["temperature"],
        "unclear_below": model["unclear_below"], "vectors": vectors}, ensure_ascii=False, indent=1), encoding="utf-8")
    (a.out / "lure_metrics.json").write_text(json.dumps({
        "version": VERSION, "corpus": {"messages": len(df), "normal_share": float((df.tag == NORMAL).mean()),
                                       "templates": int(df.template_id.nunique()),
                                       "templates_per_class": {c: int(df[df.tag == c].template_id.nunique()) for c in CLASSES},
                                       "by_language": {lg: int(n) for lg, n in df.lang.value_counts().sort_index().items()}},
        "calibration": {"method": "one temperature, softmax(scores / T), fitted by log loss on out-of-fold scores of held-out templates",
                        "temperature_dev": t_dev, "temperature_shipped": model["temperature"]},
        "unclear_rule": f"top class if its calibrated probability >= {UNCLEAR_BELOW}, else 'unclear' (keeps the top class and its probability)",
        "c": c_best, "class_weight": cw_best,
        "setting_search_dev_oof": {f"C={c:g},class_weight={w}": v for (c, w), v in table.items()},
        "held_out_templates": held_out, "max_prob_diff_json_vs_sklearn": drift}, indent=2), encoding="utf-8")
    size_kb = (a.out / "lure.json").stat().st_size / 1024
    print(f"lure.json: {len(model['vocabulary']):,} n-grams, {size_kb:.0f} KB, T={model['temperature']}; "
          f"JSON vs scikit-learn max diff {drift:.1e}")
    for v in vectors:
        print(f"  {v['tag']:<14} {v['conf']:.2f} (top {v['top']:<13}) {v['text'][:64]!r}")


if __name__ == "__main__":
    main()
