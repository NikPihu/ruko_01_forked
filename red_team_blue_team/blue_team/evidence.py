"""Everything the agents may look at, as plain JSON, and the backtest every drafted matcher must pass.

The agents never see raw tables. They call these functions as tools: a cluster's overview, one case,
one payee, a comparison with a known playbook, and `test_matcher`, which runs a drafted rule over
every replayed payment. Only what the server already holds is exposed: engine features, tiers,
request fields and plain payee UPI IDs (looked up anyway, CLAUDE.md rule 7). User ids are the
pseudonyms the server stores; no SMS text, contacts or ground truth exist here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

from blue_team import config, matcher, playbook_db, tokens
from blue_team.breach import Scored
from blue_team.cluster import Result

PAYEE_FIELDS = ("payee_holder_type", "payee_account_age_days", "payee_verified_merchant", "payee_uniq_payers_7d",
                "payee_pass_through_24h", "payee_median_hold_min", "payee_registry_listed", "payee_mulehunter",
                "payee_forwards_to_cashout", "payee_money_loop", "payee_crowd")


def _r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else (round(float(x), n) if isinstance(x, (float, np.floating)) else x)


@dataclass
class Workspace:
    scored: Scored
    cases: pd.DataFrame          # every case (held / unnamed / missed)
    clusters: Result
    legit: np.ndarray            # presumed-legit payments (bool per scored row)
    playbooks: list[playbook_db.Playbook]

    def __post_init__(self):
        self.case_by_id = self.cases.set_index("case_id")
        self.cluster_by_id = {c.cluster_id: c for c in self.clusters.clusters}
        self.case_tokens = {cid: set(doc.split()) for cid, doc in zip(self.cases["case_id"], self.cases["document"])}
        known = [pb for pb in self.playbooks if pb.status == "known"]
        self.known_named = np.array([playbook_db.name_scam(f, known) is not None for f in self.scored.feats])
        self.weight = self.scored.rows["weight"].to_numpy(float)

    # ---- helpers -------------------------------------------------------------------------------
    def _cluster(self, cluster_id: str):
        if cluster_id not in self.cluster_by_id:
            raise KeyError(f"no cluster {cluster_id!r}; clusters: {sorted(self.cluster_by_id)}")
        return self.cluster_by_id[cluster_id]

    def _rows_of(self, case_ids) -> list[int]:
        return [i for cid in case_ids for i in self.case_by_id.at[cid, "rows"]]

    def _token_share(self, case_ids) -> dict[str, float]:
        n = len(case_ids)
        cnt = Counter(t for cid in case_ids for t in self.case_tokens[cid] if t != "PAY")
        return {t: c / n for t, c in cnt.items()}

    def token_idf(self) -> dict[str, float]:
        """log(N / cases with the token), over every complaint case: rare tokens say more."""
        n = len(self.case_tokens)
        df = Counter(t for toks in self.case_tokens.values() for t in toks)
        return {t: float(np.log(n / c)) for t, c in df.items()}

    # ---- tools ---------------------------------------------------------------------------------
    def overview(self, cluster_id: str) -> dict:
        c = self._cluster(cluster_id)
        g = self.case_by_id.loc[c.case_ids]
        base_ids = c.baseline_ids or self.clusters.breaches["case_id"].tolist()
        share, base = self._token_share(c.case_ids), self._token_share(base_ids)
        distinctive = sorted(((t, s, s / max(base.get(t, 0), 1e-9)) for t, s in share.items() if s >= 0.3),
                             key=lambda x: (-x[2], -x[1]))[:15]
        rows = self.scored.rows.loc[self._rows_of(c.case_ids)]
        payees = Counter(p for ps in g["payees"] for p in ps)
        weeks = g["filed_at"].dt.tz_localize(None).dt.to_period("W").astype(str).value_counts().sort_index()
        docs = {cid: self.case_tokens[cid] for cid in c.case_ids}
        medoid = max(docs, key=lambda a: sum(len(docs[a] & docs[b]) / len(docs[a] | docs[b]) for b in docs))
        return {
            "cluster_id": c.cluster_id, "kind": c.kind, "cases": len(c.case_ids), "users": int(g["user_id"].nunique()),
            "ruko_named_it": c.nearest_playbook if c.kind == "misnamed" else None,
            "status": g["status"].value_counts().to_dict(),
            "first_payment": str(g["first_ts"].min()), "last_complaint": str(g["filed_at"].max()),
            "complaints_per_week": weeks.to_dict(), "complaint_sources": g["source"].value_counts().to_dict(),
            "payments_per_case": {"median": _r(g["n_payments"].median(), 1), "max": int(g["n_payments"].max())},
            "amount_inr": {"median": _r(rows["amount"].median(), 0), "p90": _r(rows["amount"].quantile(0.9), 0),
                           "total": _r(rows["amount"].sum(), 0)},
            "distinctive_tokens": [{"token": t, "share_of_cases": round(s, 2), "lift": round(l, 2)}
                                   for t, s, l in distinctive],
            "lift_is_against": (f"the other complaints RUKO named {c.nearest_playbook}" if c.kind == "misnamed"
                                else "all missed / unnamed complaints"),
            "typical_case": {"case_id": medoid, "sequence": self.case_by_id.at[medoid, "document"]},
            "ruko_said": {"max_tier": g["max_tier"].value_counts().to_dict(),
                          "named_by_a_playbook": round(c.named_share, 2)},
            "payees": {"distinct": len(payees), "paid_by_2plus_cases": sum(1 for v in payees.values() if v >= 2),
                       "top": [{"upi_id": p, "cases": n} for p, n in payees.most_common(5)]},
            "nearest_known_playbook": ({"name": c.nearest_playbook, "fit_to_its_other_cases": c.similarity}
                                       if c.kind == "misnamed" else {"name": c.nearest_playbook, "similarity": c.similarity}),
            "example_case_ids": c.case_ids[:5],
        }

    def case(self, case_id: str) -> dict:
        if case_id not in self.case_by_id.index:
            raise KeyError(f"no case {case_id!r}")
        c = self.case_by_id.loc[case_id]
        out, last = [], None
        for i in c["rows"]:
            r, f = self.scored.rows.loc[i], self.scored.feats[i]
            out.append({"ts": str(r["ts"]), "minutes_since_previous": None if last is None else round((r["ts"] - last).total_seconds() / 60, 1),
                        "amount_inr": _r(r["amount"], 0), "entry_method": f.get("entry_method"), "payer_says": f.get("payer_says"),
                        "payee_upi_id": r["payee_upi"], "ruko_tier": r["tier"], "ruko_named": r["named"] if isinstance(r["named"], str) else None,
                        "tokens": tokens.payment_tokens(f)})
            last = r["ts"]
        return {"case_id": case_id, "status": c["status"], "complaint_filed": str(c["filed_at"]), "source": c["source"],
                "payments": out}

    def payee(self, upi_id: str) -> dict:
        rows = self.scored.rows
        idx = np.flatnonzero(rows["payee_upi"].to_numpy() == upi_id)
        if not len(idx):
            raise KeyError(f"no payments to {upi_id!r}")
        last = self.scored.feats[idx[-1]]
        in_cases = [cid for cid, ps in zip(self.cases["case_id"], self.cases["payees"]) if upi_id in ps]
        in_clusters = sorted({c.cluster_id for c in self.clusters.clusters if set(c.case_ids) & set(in_cases)})
        return {"upi_id": upi_id, "payments_seen": int(len(idx)), "distinct_payers": int(rows["user_id"].iloc[idx].nunique()),
                "as_of_last_payment": {k: _r(last.get(k)) for k in PAYEE_FIELDS},
                "complaints_naming_it": len(in_cases), "clusters": in_clusters}

    def compare(self, cluster_id: str, playbook: str) -> dict:
        c = self._cluster(cluster_id)
        pb = next((p for p in self.playbooks if p.name == playbook), None)
        if pb is None:
            raise KeyError(f"no playbook {playbook!r}")
        own = set(c.case_ids)
        ref = [i for i in self.cases.loc[self.cases["named_main"] == playbook, "case_id"] if i not in own]
        a, b = self._token_share(c.case_ids), self._token_share(ref) if ref else {}
        diff = sorted(((t, a.get(t, 0) - b.get(t, 0)) for t in set(a) | set(b)), key=lambda x: x[1])
        rows = self._rows_of(c.case_ids)
        circular = c.kind == "misnamed" and playbook == c.nearest_playbook
        return {"cluster_id": cluster_id, "playbook": playbook, "playbook_title": pb.title,
                "playbook_summary": pb.card.get("summary", "").strip(), "playbook_steps": pb.card.get("steps", []),
                "reference_cases": len(ref),
                "centroid_similarity": c.similarity if c.nearest_playbook == playbook and not circular else None,
                "playbook_rules_name_this_cluster": (
                    "not shown: these complaints were selected *because* this playbook's rule named them, so it "
                    "says nothing about whether the name is right. Judge by the story." if circular else
                    round(float(np.mean([playbook_db.name_scam(self.scored.feats[i], [pb]) is not None for i in rows])), 2)),
                "more_common_in_cluster": [{"token": t, "diff": round(d, 2)} for t, d in diff[::-1][:8] if d > 0],
                "more_common_in_playbook": [{"token": t, "diff": round(d, 2)} for t, d in diff[:8] if d < 0]}

    def test_matcher(self, rule: dict, cluster_id: str) -> dict:
        rule = matcher.normalize(rule)
        errors = matcher.validate(rule)
        if errors:
            return {"valid": False, "errors": errors}
        gates = config.load()["gates"]
        c = self._cluster(cluster_id)
        hit = np.array([matcher.matches(rule, f) for f in self.scored.feats])
        rows = self._rows_of(c.case_ids)
        case_hit = [bool(hit[self.case_by_id.at[cid, "rows"]].any()) for cid in c.case_ids]
        legit = float(1000 * self.weight[self.legit & hit].sum() / max(self.weight[self.legit].sum(), 1e-9))
        known_elsewhere = self.known_named.copy()
        known_elsewhere[rows] = False       # a misnamed group's own payments are what a fix should take
        overlap = float(hit[known_elsewhere].mean()) if known_elsewhere.any() else 0.0
        others = {o.cluster_id: round(float(np.mean([hit[self.case_by_id.at[cid, "rows"]].any() for cid in o.case_ids])), 2)
                  for o in self.clusters.clusters if o.cluster_id != cluster_id}
        res = {"valid": True, "rule_in_words": matcher.describe(rule),
               "cluster_payment_recall": round(float(hit[rows].mean()), 3),
               "cluster_case_recall": round(float(np.mean(case_hit)), 3),
               "legit_payments_named_per_1000": round(legit, 3),
               "known_playbook_payments_also_matched": round(overlap, 3),
               "other_clusters_case_recall": {k: v for k, v in others.items() if v > 0}}
        res["gate_failures"] = gate_failures(res, gates)
        return res

    def mules(self, cluster_id: str) -> list[dict]:
        g = self.case_by_id.loc[self._cluster(cluster_id).case_ids]
        cnt = Counter(p for ps in g["payees"] for p in ps)
        return [{"upi_id": p, "cases": n} for p, n in cnt.most_common()]

    def labels(self, cluster_id: str) -> list[str]:
        return [str(self.scored.rows.at[i, "tx_id"]) for i in self._rows_of(self._cluster(cluster_id).case_ids)]


def gate_failures(res: dict, gates: dict) -> list[str]:
    out = []
    if res["cluster_case_recall"] < gates["min_cluster_recall"]:
        out.append(f"names only {res['cluster_case_recall']:.0%} of the cluster's cases (need {gates['min_cluster_recall']:.0%})")
    if res["legit_payments_named_per_1000"] > gates["max_legit_per_1000"]:
        out.append(f"would name {res['legit_payments_named_per_1000']:.2f} legit payments per 1,000 (max {gates['max_legit_per_1000']})")
    if res["known_playbook_payments_also_matched"] > gates["max_known_overlap"]:
        out.append(f"also matches {res['known_playbook_payments_also_matched']:.0%} of known-playbook payments "
                   f"(max {gates['max_known_overlap']:.0%}): probably a known scam")
    return out
