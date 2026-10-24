"""The trained server scorer, a drop-in for api/rule_scorer.score (the engine's app.state.score).

    from model.predict import score
    score(features) -> {p_scam, family_scores, reasons, playbook, model_version}

`features` is exactly what backend/features/build.py build_features() returns; nothing is
re-implemented here. `None` stays missing (LightGBM's own missing-value branch), never 0 or false.
The playbook still comes from the rules engine's matcher (config-like, analyst-approved playbooks)
until discovery adds new ones. No LLM anywhere (CLAUDE.md rule 13).

Two model formats: lgbm-0.2 (four family models + a combiner, `Model`) and lgbm-0.3 (`kind: single`,
`SingleModel`: one LightGBM over the engine features, the phone verdict's level and class, and the
journey's scam steps; family scores from its per-family contributions). lgbm-0.3 reads two more
keys from the dict it scores: `steps` ({step: seen}, features/steps.py) and `verdict`
((level, fraud_class) of the phone's verdict, or None); without them those inputs are missing.

Payee guardrail (+pg1): with hard payee evidence (registry listed, a suspect two analysts approved,
or a money loop plus a crowd signal) the payee family is at least the rules engine's payee score.
The simulated worlds hold few mules, all small, so the trained payee model learned "many payers =
a shop" and ignores evidence it never saw (approved suspects); the guardrail keeps such a payee lit.
"""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path

import lightgbm as lgb
import numpy as np

from api import rule_scorer
from api.rule_scorer import _playbook
from model.data import VERDICT, encode_features, step_inputs, verdict_inputs

MODEL_PATH = Path(os.environ.get("RUKO_MODEL", Path(__file__).resolve().parent / "artifacts" / "v0" / "server_model.json"))
FAMILIES = ("C", "L", "P", "B")
CLIP = 1e-4
LIT = 0.5            # policy.yaml family_threshold
MAX_REASONS = 4      # same as the rules engine
GUARDRAIL = "pg1"    # payee guardrail, appended to the model version
# lgbm-0.3: one model shares the credit between families, so a call or a lure rarely makes a scam 10x
# likelier on its own while the payee and amount carry most of it. Reasons come from every family whose
# evidence at least doubled the odds (log-LR >= ln 2), not only lit ones, so the user still reads "a
# call from an unknown number" next to "a new payee".
REASON_MIN_LOG_LR = math.log(2.0)


def hard_payee_evidence(f: dict) -> bool:
    """Payee evidence strong enough that the rules engine's payee score is a floor."""
    return bool(f.get("payee_registry_listed") or f.get("payee_approved_suspect")
                or (f.get("payee_money_loop") and f.get("payee_crowd")))


def payee_floor(f: dict) -> float | None:
    """The rules engine's payee-family score when there is hard payee evidence, else None."""
    return rule_scorer.score(f)["family_scores"]["P"] if hard_payee_evidence(f) else None


def model_inputs(features: dict) -> dict[str, float]:
    """The scored dict -> every numeric input of either format: the engine features, the phone
    verdict's level and class (`verdict`, with device_c/l/b missing when there is none) and the
    journey's steps (`steps`)."""
    x = encode_features({k: v for k, v in features.items() if k not in ("steps", "verdict")})
    v = features.get("verdict")
    x |= verdict_inputs(*(v if v else (None, None)))
    if not v and "steps" in features:   # an engine that sends steps also says when there is no verdict
        x |= dict.fromkeys(VERDICT, math.nan)
    x |= step_inputs(features.get("steps"))
    return x


class _Family:
    def __init__(self, spec: dict):
        self.features = spec["features"]
        self.booster = lgb.Booster(model_str=spec["booster"])
        self.iso_x = np.asarray(spec["iso_x"])
        self.iso_y = np.asarray(spec["iso_y"])

    def calibrated(self, row: np.ndarray) -> float:
        raw = float(self.booster.predict(row)[0])
        return float(np.interp(raw, self.iso_x, self.iso_y))


class Model:
    def __init__(self, spec: dict):
        self.version = f"{spec['version']}+{GUARDRAIL}"
        self.prior = spec["prior"]
        self.k = spec["family_k"]
        self.families = {f: _Family(spec["families"][f]) for f in FAMILIES}
        self.coef = np.asarray(spec["combiner"]["coef"])
        self.intercept = spec["combiner"]["intercept"]
        self.extra = spec["combiner"]["inputs"][len(FAMILIES) + 1:]     # lgbm-0.3: the verdict's level
        self.reasons = spec["reasons"]

    def strength(self, p: float) -> float:
        p = min(max(p, CLIP), 1 - CLIP)
        lr = (p / (1 - p)) / (self.prior / (1 - self.prior))
        return lr / (lr + self.k)

    def calibrated_for(self, strength: float) -> float:
        """The calibrated probability whose family score is `strength` (the inverse of strength())."""
        s = min(max(strength, CLIP), 1 - CLIP)
        odds = self.k * s / (1 - s) * (self.prior / (1 - self.prior))
        return odds / (1 + odds)

    def score(self, features: dict) -> dict:
        x = model_inputs(features)
        rows, cal = {}, {}
        for f, fam in self.families.items():
            rows[f] = np.array([[x.get(c, math.nan) for c in fam.features]], dtype=float)
            cal[f] = fam.calibrated(rows[f])
        floor = payee_floor(features)
        guarded = floor is not None and self.calibrated_for(floor) > cal["P"]
        if guarded:
            cal["P"] = self.calibrated_for(floor)
        stage = features.get("stage") or 0
        z = self.intercept + sum(self.coef[i] * _logit(cal[f]) for i, f in enumerate(FAMILIES)) + self.coef[4] * stage
        z += sum(self.coef[5 + i] * (0.0 if math.isnan(x.get(c, math.nan)) else x[c]) for i, c in enumerate(self.extra))
        p_scam = 1 / (1 + math.exp(-z))
        family_scores = {f: round(self.strength(cal[f]), 3) for f in FAMILIES}
        return {"p_scam": round(p_scam, 4), "family_scores": family_scores,
                "reasons": self._reasons(rows, family_scores, _rule_payee_reasons(features) if guarded else None),
                "playbook": _playbook(features),
                "model_version": self.version}

    def score_frame(self, x, floors=None) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """Many rows at once (model.data.encode_frame columns): p_scam and family scores, no reasons.
        `floors`: payee_floor() of each row's raw features (None or NaN = no hard evidence)."""
        cal = {f: np.interp(fam.booster.predict(x.reindex(columns=fam.features)), fam.iso_x, fam.iso_y)
               for f, fam in self.families.items()}
        if floors is not None:
            fl = np.array([np.nan if v is None else v for v in floors], dtype=float)
            s = np.clip(fl, CLIP, 1 - CLIP)
            odds = self.k * s / (1 - s) * (self.prior / (1 - self.prior))
            cal["P"] = np.where(np.isnan(fl), cal["P"], np.maximum(cal["P"], odds / (1 + odds)))
        stage = np.nan_to_num(x["stage"].to_numpy(dtype=float), nan=0.0)
        z = self.intercept + sum(self.coef[i] * _logit_arr(cal[f]) for i, f in enumerate(FAMILIES)) + self.coef[4] * stage
        for i, c in enumerate(self.extra):
            z = z + self.coef[5 + i] * np.nan_to_num(x[c].to_numpy(dtype=float), nan=0.0)
        lr_prior = self.prior / (1 - self.prior)
        fam = {}
        for f in FAMILIES:
            p = np.clip(cal[f], CLIP, 1 - CLIP)
            lr = (p / (1 - p)) / lr_prior
            fam[f] = lr / (lr + self.k)
        return 1 / (1 + np.exp(-z)), fam

    def _reasons(self, rows: dict, family_scores: dict, payee_override: list[tuple[str, float]] | None = None) -> list[str]:
        """Codes of the features that pushed lit families up the most, taken in turns: the best reason
        of each lit family (strongest family first), then each family's second best, and so on, so
        one family's details never crowd out another family's evidence (e.g. a WhatsApp call's R1
        and the payment's R6 must not hide R2 remote control)."""
        ranked: list[list[tuple[str, float]]] = []
        for f in sorted(family_scores, key=lambda k: -family_scores[k]):
            if family_scores[f] < LIT:
                continue
            if f == "P" and payee_override is not None:
                ranked.append(payee_override)  # the guardrail lit P: the rules' payee reasons
                continue
            fam = self.families[f]
            contrib = fam.booster.predict(rows[f], pred_contrib=True)[0][:-1]  # last value is the bias
            weight: dict[str, float] = {}
            for name, c in zip(fam.features, contrib):
                code = self.reasons.get(name)
                if code and c > 0:
                    weight[code] = weight.get(code, 0.0) + float(c)
            ranked.append(sorted(weight.items(), key=lambda kv: -kv[1]))
        out: list[str] = []
        for depth in range(max((len(codes) for codes in ranked), default=0)):
            for codes in ranked:
                if depth < len(codes) and codes[depth][0] not in out and len(out) < MAX_REASONS:
                    out.append(codes[depth][0])
        return out


class SingleModel:
    """lgbm-0.3 (model/train.py): one booster, isotonic calibration, family scores from contributions."""

    def __init__(self, spec: dict):
        self.version = f"{spec['version']}+{GUARDRAIL}"
        self.prior = spec["prior"]
        self.k = spec["family_k"]
        self.features = spec["features"]
        self.fams = spec["families"]
        self.booster = lgb.Booster(model_str=spec["booster"])
        self.iso_x, self.iso_y = np.asarray(spec["iso_x"]), np.asarray(spec["iso_y"])
        self.reasons = spec["reasons"]
        self.idx = {f: np.array([i for i, c in enumerate(self.features) if self.fams.get(c) == f], dtype=int)
                    for f in FAMILIES}

    def inputs(self, features: dict) -> np.ndarray:
        x = model_inputs(features)
        return np.array([[x.get(c, math.nan) for c in self.features]], dtype=float)

    def _finish(self, contrib: np.ndarray, floor_lr: np.ndarray | None) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """contrib: rows x (features + bias) -> (calibrated p_scam, family log-LRs after the guardrail)."""
        fam = {f: contrib[:, self.idx[f]].sum(axis=1) for f in FAMILIES}
        raw = contrib.sum(axis=1)
        if floor_lr is not None:
            lift = np.where(np.isnan(floor_lr), 0.0, np.maximum(0.0, np.nan_to_num(floor_lr) - fam["P"]))
            fam["P"] = fam["P"] + lift
            raw = raw + lift
        p = np.interp(1 / (1 + np.exp(-raw)), self.iso_x, self.iso_y)
        return p, fam

    def _floor_lr(self, floor: float | None) -> float:
        """The payee floor (a rules-engine family score) as a log-LR: s = LR / (LR + K)."""
        if floor is None:
            return math.nan
        s = min(max(floor, CLIP), 1 - CLIP)
        return math.log(self.k * s / (1 - s))

    def score(self, features: dict) -> dict:
        row = self.inputs(features)
        contrib = self.booster.predict(row, pred_contrib=True)
        floor_lr = self._floor_lr(payee_floor(features))
        guarded = not math.isnan(floor_lr) and floor_lr > float(contrib[0, self.idx["P"]].sum())
        p, fam = self._finish(contrib, np.array([floor_lr]))
        family_scores = {f: round(float(1 / (1 + self.k * math.exp(-min(max(fam[f][0], -50), 50)))), 3)
                         for f in FAMILIES}
        return {"p_scam": round(float(p[0]), 4), "family_scores": family_scores,
                "reasons": self._reasons(contrib[0], {f: float(fam[f][0]) for f in FAMILIES},
                                         _rule_payee_reasons(features) if guarded else None),
                "playbook": _playbook(features), "model_version": self.version}

    def score_frame(self, x, floors=None) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """Many rows (model.data.encode_frame columns, incl. the verdict and step columns)."""
        ps, fams = [], {f: [] for f in FAMILIES}
        fl = None if floors is None else np.array([self._floor_lr(v if v is None or not math.isnan(v) else None)
                                                   for v in floors], dtype=float)
        xx = x.reindex(columns=self.features)
        for a in range(0, len(xx), 100_000):
            c = self.booster.predict(xx.iloc[a:a + 100_000], pred_contrib=True)
            p, fam = self._finish(c, None if fl is None else fl[a:a + 100_000])
            ps.append(p)
            for f in FAMILIES:
                fams[f].append(fam[f])
        out = {f: 1 / (1 + self.k * np.exp(-np.clip(np.concatenate(v), -50, 50))) for f, v in fams.items()}
        return np.concatenate(ps), out

    def _reasons(self, contrib: np.ndarray, log_lr: dict[str, float], payee_override=None) -> list[str]:
        """As Model._reasons, the strongest features of each family taken in turns, over the families
        whose evidence at least doubled the odds (REASON_MIN_LOG_LR), strongest family first."""
        ranked: list[list[tuple[str, float]]] = []
        for f in sorted(log_lr, key=lambda k: -log_lr[k]):
            if log_lr[f] < REASON_MIN_LOG_LR:
                continue
            if f == "P" and payee_override is not None:
                ranked.append(payee_override)
                continue
            weight: dict[str, float] = {}
            for i in self.idx[f]:
                code = self.reasons.get(self.features[i])
                if code and contrib[i] > 0:
                    weight[code] = weight.get(code, 0.0) + float(contrib[i])
            ranked.append(sorted(weight.items(), key=lambda kv: -kv[1]))
        out: list[str] = []
        for depth in range(max((len(codes) for codes in ranked), default=0)):
            for codes in ranked:
                if depth < len(codes) and codes[depth][0] not in out and len(out) < MAX_REASONS:
                    out.append(codes[depth][0])
        return out


def _rule_payee_reasons(f: dict) -> list[tuple[str, float]]:
    """The rules engine's payee reason codes, strongest first (each code once)."""
    best: dict[str, float] = {}
    for sig in rule_scorer.signals(f):
        if sig["family"] == "P" and sig["strength"] >= rule_scorer.REASON_MIN_STRENGTH:
            best[sig["reason"]] = max(best.get(sig["reason"], 0.0), sig["strength"])
    return sorted(best.items(), key=lambda kv: -kv[1])


def _logit(p: float) -> float:
    p = min(max(p, CLIP), 1 - CLIP)
    return math.log(p / (1 - p))


def _logit_arr(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, CLIP, 1 - CLIP)
    return np.log(p / (1 - p))


@lru_cache(maxsize=1)
def load(path: str | Path = MODEL_PATH) -> Model | SingleModel:
    spec = json.loads(Path(path).read_text())
    return SingleModel(spec) if spec.get("kind") == "single" else Model(spec)


MODEL_VERSION = "lgbm-0.3+pg1"


def score(features: dict) -> dict:
    return load().score(features)
