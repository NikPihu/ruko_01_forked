"""Step 2: group the breaches with HDBSCAN and decide which groups need the agents.

Each case is a token document (blue_team/tokens.py). TF-IDF over token n-grams, reduced with SVD,
clustered with HDBSCAN (sklearn), which needs no number of clusters and leaves one-off cases as
noise instead of forcing them into a group.

Two passes:
- **Breaches** (missed / unnamed cases). A cluster is *known* when most of its cases were already
  named by a playbook (a known scam that slipped past the tiers: a tuning problem, not a new
  playbook), or when its centroid is close to the cases a playbook names. Otherwise it is *new*.
- **Misnamed** (held cases: interrupted *and* named, yet the victim paid and complained). For each
  playbook, its held cases are clustered on their own; a subgroup whose signals do not fit the
  playbook's other held cases is *misnamed*: RUKO warned with the wrong story (a voice-clone
  "son" called a digital arrest), which may be why the warning did not work.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from blue_team import config

SIGNATURE_IGNORE = ("LURE_", "EPISODE_", "BAIT_", "GAP_")   # what a missed lure / episode would remove


@dataclass
class Cluster:
    cluster_id: str
    case_ids: list[str]
    kind: str                     # new | known | misnamed
    nearest_playbook: str | None  # misnamed: the playbook RUKO named these cases with
    similarity: float             # new/known: centroid cosine to the nearest playbook's cases;
                                  # misnamed: fit to the playbook's other held cases (lures ignored)
    named_share: float            # share of its cases some playbook already named
    top_tokens: list[tuple[str, float]] = field(default_factory=list)   # (token n-gram, lift)
    baseline_ids: list[str] | None = None   # misnamed: the playbook's other held cases, to compare with


@dataclass
class Result:
    clusters: list[Cluster]
    noise: list[str]              # breach cases in no cluster
    breaches: pd.DataFrame        # the clustered breach cases, with a `cluster` column


def _embed(docs: pd.Series, cfg: dict):
    vec = TfidfVectorizer(token_pattern=r"\S+", lowercase=False, ngram_range=tuple(cfg["ngram_range"]),
                          max_df=cfg["max_df"], sublinear_tf=True)
    vec.fit(docs)
    x = normalize(vec.transform(docs))
    k = max(2, min(cfg["svd_components"], x.shape[0] - 1, x.shape[1] - 1))
    z = normalize(TruncatedSVD(n_components=k, random_state=0).fit_transform(x))
    labels = HDBSCAN(min_cluster_size=cfg["min_cluster_size"], min_samples=cfg["min_samples"],
                     cluster_selection_method=cfg["selection"], copy=True).fit_predict(z)
    return vec, x, labels


def _top_tokens(x, mask, vocab) -> list[tuple[str, float]]:
    centroid = np.asarray(x[mask].mean(axis=0)).ravel()
    overall = np.asarray(x.mean(axis=0)).ravel() + 1e-9
    lift = centroid / overall
    order = np.argsort(-(centroid * np.log1p(lift)))[:12]
    return [(str(vocab[i]), round(float(lift[i]), 2)) for i in order]


def run(case_df: pd.DataFrame) -> Result:
    cfg = config.load()["cluster"]
    include = set(config.load()["breach"]["include"])
    br = case_df[case_df["status"].isin(include)].reset_index(drop=True)
    suspects = misnamed(case_df) if config.load()["misnamed"]["enabled"] else []
    # Cases a playbook named are what "known" looks like, except groups suspected to be misnamed:
    # otherwise missed voice-clone calls look like the digital arrests their misnamed twins were called.
    doubtful = {i for c in suspects for i in c.case_ids}
    ref = case_df[case_df["named_main"].notna() & ~case_df["case_id"].isin(doubtful)]
    clusters: list[Cluster] = []
    if len(br) >= cfg["min_cluster_size"]:
        vec, x_br, labels = _embed(br["document"], cfg)
        br = br.assign(cluster=labels)
        known = {pb: np.asarray(normalize(vec.transform(g["document"])).mean(axis=0)).ravel()
                 for pb, g in ref.groupby("named_main")}
        vocab = np.array(vec.get_feature_names_out())
        for lab in sorted(set(labels) - {-1}):
            g = br[br["cluster"] == lab]
            centroid = np.asarray(x_br[labels == lab].mean(axis=0)).ravel()
            sims = {pb: _cos(centroid, c) for pb, c in known.items()}
            nearest = max(sims, key=sims.get) if sims else None
            sim = sims.get(nearest, 0.0) if nearest else 0.0
            named = g["named_main"].dropna().tolist()
            named_share = len(named) / len(g)
            if named_share >= cfg["known_named_share"]:
                kind, nearest = "known", Counter(named).most_common(1)[0][0]
                sim = sims.get(nearest, sim)
            elif sim >= cfg["known_similarity"]:
                kind = "known"
            else:
                kind = "new"
            clusters.append(Cluster(f"c{lab:02d}", g["case_id"].tolist(), kind, nearest, round(float(sim), 3),
                                    round(named_share, 3), _top_tokens(x_br, labels == lab, vocab)))
    else:
        br = br.assign(cluster=-1)
    clusters += suspects
    return Result(clusters, br.loc[br["cluster"] == -1, "case_id"].tolist(), br)


def misnamed(case_df: pd.DataFrame) -> list[Cluster]:
    """Subgroups of a playbook's held cases that do not fit the rest of them."""
    cfg, mcfg = config.load()["cluster"], config.load()["misnamed"]
    sets = token_sets(case_df)
    w = idf(sets)
    held = case_df[(case_df["status"] == "held") & case_df["named_main"].notna()]
    out = []
    for pb, g in held.groupby("named_main"):
        if len(g) < mcfg["min_cases"]:
            continue
        g = g.reset_index(drop=True)
        vec, x, labels = _embed(g["document"], cfg)
        groups = sorted(set(labels) - {-1})
        if len(groups) < 2:                     # one coherent group: nothing looks out of place
            continue
        vocab = np.array(vec.get_feature_names_out())
        ids = g["case_id"].tolist()
        for lab in groups:
            mine = [i for i, l in zip(ids, labels) if l == lab]
            rest = [i for i in ids if i not in set(mine)]
            fit = profile_cosine(mine, rest, sets, w)
            if fit < mcfg["fit_below"]:
                out.append(Cluster(f"m_{pb}_{lab}", mine, "misnamed", pb, round(fit, 3), 1.0,
                                   _top_tokens(x, labels == lab, vocab), baseline_ids=rest))
    return out


def token_sets(case_df: pd.DataFrame) -> dict[str, set[str]]:
    return {cid: set(doc.split()) for cid, doc in zip(case_df["case_id"], case_df["document"])}


def idf(sets: dict[str, set[str]]) -> dict[str, float]:
    """log(N / cases with the token), over every complaint case: rare tokens say more."""
    n = len(sets)
    df = Counter(t for toks in sets.values() for t in toks)
    return {t: float(np.log(n / c)) for t, c in df.items()}


def profile(case_ids, sets: dict[str, set[str]]) -> dict[str, float]:
    n = max(len(case_ids), 1)
    cnt = Counter(t for cid in case_ids for t in sets[cid] if t != "PAY")
    return {t: c / n for t, c in cnt.items()}


def profile_cosine(a_ids, b_ids, sets: dict[str, set[str]], w: dict[str, float]) -> float:
    """Cosine of IDF-weighted token-share profiles, lure / episode / gap tokens left out: a known scam
    whose lure the phone missed still looks like itself, and tokens every scam shares count little."""
    if not a_ids or not b_ids:
        return 0.0
    a, b = profile(a_ids, sets), profile(b_ids, sets)
    keys = sorted(k for k in set(a) | set(b) if not k.startswith(SIGNATURE_IGNORE))
    va = np.array([a.get(k, 0) * w.get(k, 0) for k in keys])
    vb = np.array([b.get(k, 0) * w.get(k, 0) for k in keys])
    n = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(va @ vb / n) if n else 0.0


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0
