"""The fused threat (plan v3 step 5): the trained model's p_scam and the playbook search's best match,
as one probability that this payment is a scam.

    p_playbook = isotonic(similarity of the best playbook)        # learned on the calibration shards
    threat     = 1 - (1 - p_lgbm) * (1 - p_playbook)               # form "noisy_or": either strong is enough
    threat     = sigmoid(b + a1 logit p_lgbm + a2 logit p_playbook + a3 logit p_lgbm * logit p_playbook)
                                                                   # form "logistic", when it fit better

The two are independent evidence by construction: the model never sees the similarity (ml/model/train.py)
and the search never sees the model. The artifact (ml/model/artifacts/v0/fusion.json, written by
`python -m model.fusion`) belongs to one model version; with any other scorer (the rules fallback, an
older model) there is no fusion and the policy decides as before, from lit families (api/policy.py).
Tier thresholds are config (policy.yaml `fused:`, rule 6), not part of the artifact.
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("ruko")
PATH = Path(os.environ.get("RUKO_FUSION", Path(__file__).resolve().parents[2] / "ml" / "model" / "artifacts" / "v0" / "fusion.json"))
CLIP = 1e-4


def _logit(p: float) -> float:
    p = min(max(p, CLIP), 1 - CLIP)
    return math.log(p / (1 - p))


@dataclass
class Fusion:
    model_version: str
    iso_x: list[float]
    iso_y: list[float]
    form: str = "noisy_or"
    coef: tuple[float, float, float] = (1.0, 1.0, 0.0)
    intercept: float = 0.0

    @classmethod
    def from_spec(cls, spec: dict) -> "Fusion":
        return cls(spec["model_version"], spec["playbook_iso"]["x"], spec["playbook_iso"]["y"], spec.get("form", "noisy_or"),
                   tuple(spec.get("coef", (1.0, 1.0, 0.0))), float(spec.get("intercept", 0.0)))

    def p_playbook(self, similarity: float) -> float:
        """P(scam | the best playbook matched this well); no match -> 0."""
        if similarity <= 0 or not self.iso_x:
            return 0.0
        xs, ys = self.iso_x, self.iso_y
        if similarity <= xs[0]:
            return ys[0]
        if similarity >= xs[-1]:
            return ys[-1]
        for i in range(1, len(xs)):
            if similarity <= xs[i]:
                t = (similarity - xs[i - 1]) / (xs[i] - xs[i - 1]) if xs[i] > xs[i - 1] else 1.0
                return ys[i - 1] + t * (ys[i] - ys[i - 1])
        return ys[-1]

    def threat(self, p_lgbm: float, similarity: float) -> tuple[float, dict]:
        """(threat 0..1, parts for the analyst)."""
        pp = self.p_playbook(similarity)
        if self.form == "logistic":
            a, b = _logit(p_lgbm), _logit(pp)
            z = self.intercept + self.coef[0] * a + self.coef[1] * b + self.coef[2] * a * b
            t = 1 / (1 + math.exp(-z))
        else:
            t = 1 - (1 - p_lgbm) * (1 - pp)
        # Either source alone is a floor: a match never makes the model's evidence count for less.
        t = max(t, p_lgbm, pp)
        return round(t, 4), {"lgbm": round(p_lgbm, 4), "playbook": round(pp, 4), "similarity": round(similarity, 4)}


def load(model_version: str, path: Path | None = None) -> Fusion | None:
    """The fusion for this scorer version, or None (no file, a broken file, or another model's)."""
    path = path or PATH
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
        f = Fusion.from_spec(spec)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.error("fusion file %s not used (%s); tiers from lit families", path, e)
        return None
    if f.model_version != model_version:
        log.warning("fusion file is for %s, the scorer is %s; tiers from lit families", f.model_version, model_version)
        return None
    return f
