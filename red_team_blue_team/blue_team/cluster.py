"""Step 2: group the breaches with HDBSCAN and decide which groups are new scams.

Each missed / unnamed case is a token document (blue_team/tokens.py). TF-IDF over token n-grams,
reduced with SVD, clustered with HDBSCAN (sklearn), which needs no number of clusters and leaves
one-off cases as noise instead of forcing them into a group.

A cluster is **known** when most of its cases were already named by a playbook (a known scam that
slipped past the tiers: a tuning problem, not a new playbook), or when its centroid is close to the
cases a playbook names. Otherwise it is **new** and goes to the agents.
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


@dataclass
class Cluster:
    cluster_id: str
    case_ids: list[str]
    kind: str                     # new | known
    nearest_playbook: str | None
    similarity: float             # cosine of the centroid to the nearest playbook's cases
    named_share: float            # share of its cases some playbook already named
    top_tokens: list[tuple[str, float]] = field(default_factory=list)   # (token n-gram, lift)


@dataclass
class Result:
    clusters: list[Cluster]
    noise: list[str]              # breach cases in no cluster
    breaches: pd.DataFrame        # the clustered cases, with a `cluster` column


def run(case_df: pd.DataFrame) -> Result:
    cfg = config.load()["cluster"]
    include = set(config.load()["breach"]["include"])
    br = case_df[case_df["status"].isin(include)].reset_index(drop=True)
    ref = case_df[case_df["named_main"].notna()]          # cases a playbook named: what "known" looks like
    if len(br) < cfg["min_cluster_size"]:
        return Result([], br["case_id"].tolist(), br.assign(cluster=-1))

    vec = TfidfVectorizer(token_pattern=r"\S+", lowercase=False, ngram_range=tuple(cfg["ngram_range"]),
                          max_df=cfg["max_df"], sublinear_tf=True)
    vec.fit(br["document"])
    x_br = normalize(vec.transform(br["document"]))
    k = max(2, min(cfg["svd_components"], x_br.shape[0] - 1, x_br.shape[1] - 1))
    z = normalize(TruncatedSVD(n_components=k, random_state=0).fit_transform(x_br))
    labels = HDBSCAN(min_cluster_size=cfg["min_cluster_size"], min_samples=cfg["min_samples"],
                     cluster_selection_method=cfg["selection"], copy=True).fit_predict(z)
    br = br.assign(cluster=labels)

    known = {}
    for pb, g in ref.groupby("named_main"):
        known[pb] = np.asarray(normalize(vec.transform(g["document"])).mean(axis=0)).ravel()
    vocab = np.array(vec.get_feature_names_out())
    overall = np.asarray(x_br.mean(axis=0)).ravel() + 1e-9

    clusters = []
    for lab in sorted(set(labels) - {-1}):
        g = br[br["cluster"] == lab]
        rows = x_br[(labels == lab)]
        centroid = np.asarray(rows.mean(axis=0)).ravel()
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
        lift = centroid / overall
        order = np.argsort(-(centroid * np.log1p(lift)))[:12]
        clusters.append(Cluster(f"c{lab:02d}", g["case_id"].tolist(), kind, nearest, round(float(sim), 3),
                                round(named_share, 3), [(str(vocab[i]), round(float(lift[i]), 2)) for i in order]))
    return Result(clusters, br.loc[br["cluster"] == -1, "case_id"].tolist(), br)


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na and nb else 0.0
