# What RUKO needs from ML (Diwansu)

Owner of `ml/`: Diwansu Pilania. Everything else around the models (the app, the server, the
console, the contract, evaluation plumbing) is built by Jagdeep. This page says exactly what each
model must take in, give back, and pass, so it plugs in without changes on either side.

Rules that apply to every model (root `CLAUDE.md`):

| Rule | What it means for a model |
|---|---|
| 1. Unknown is never safe | A missing / `null` input must never *lower* the risk. Test it. |
| 2. Only conclusions leave the phone | On-device models read text on the phone; only a tag, a score or a count is sent. |
| 4. Never show the score | The model can return scores; the server keeps them for analysts. Users see reason words only. |
| 5. Two independent families | Scores come per family (C, L, P, B). One source never lights two families. |
| 13. No LLM in the decision path | LightGBM / logistic / n-gram models only. |
| 14. No age, gender or language as inputs | Use them only to check fairness of the results. |

---

## 1. Server scam model (replaces the rules in `/v1/decide`)

**Where it plugs in:** `ml/model/predict.py` `score(features)`. The engine runs it with
`python -m api.main --scorer ml`. If it fails to load, the engine falls back to the rules by itself
(`api/main.py` `pick_scorer`). Today `lgbm-0.1` exists; the `.venv` still needs `lightgbm`
(`pip install -r ml/requirements.txt`).

**Input:** the feature dict built by `backend/features/build.py` (the only place features are
defined; its `FAMILY` map says which family each belongs to). Values can be `None` (unknown).
Features added since `lgbm-0.1` that the next version should learn:
- `session_dictated`, `session_pasted_after_switch`, `session_app_switches`, `session_hesitation`,
  `session_abandoned_30m` (B, coached Pay screen);
- `call_on_speaker` (C);
- `payee_in_contacts`, `payee_in_run` (B);
- coming next: `video_call` (C, video call while paying) and `payee_automated` (P, bot-scale ring).

**Output** (same shape as `api/rule_scorer.score`):

| Key | What |
|---|---|
| `p_scam` | 0–1, calibrated |
| `family_scores` | `{"C", "L", "P", "B"}`, each 0–1; a family "lights" at ≥ 0.5 (`policy.yaml`) |
| `reasons` | up to 4 contract reason codes (`R1_…` to `R12_…`), most important first, only from lit families |
| `playbook` | `api/rule_scorer._playbook(features)` (keep using it, or return the same names) |
| `model_version` | e.g. `"lgbm-0.2"` |
| `signals` | **optional, wanted for the analyst explanation:** a list of `{family, reason, strength}`. For LightGBM, one entry per reason with its summed positive contribution (0–1 scaled). The console shows these as small / medium / large. Until the model returns it, the console shows the rules' signals for the same inputs. If you add it, `ml/tests/test_predict.py` (same shape as the rules) needs the key allowed. |

**Must pass:**
- `ml/tests/test_predict.py`;
- the backend suite with `--scorer ml` (`pytest backend/tests`);
- p95 under 10 ms per call;
- Meena's examples (`contracts/examples/decide_request_meena.json`, `…_coached.json`) give T3/T4, and
  the kirana example gives T0;
- removing any one input (set to `None`) never lowers `p_scam`.

**Training data:** besides the simulator replay, the engine can now write every live decision with
all its inputs. Run it with `--db logs/ruko.db`, then:
`python -m store.export --db logs/ruko.db --out logs/exports/transactions.parquet`.
Inputs are `f_*` columns, family scores are `family_*`, and outcomes / feedback come with them.

## 2. Lure model (scam-script messages, on the phone)

- **Exists:** `ml/model/artifacts/lure.json` + `lure_vectors.json`. The app loads `lure.json` from
  its assets.
- **Next:** Jagdeep is adding an **AI-written messages test**: scam and normal messages rewritten in
  new words, in English, Hindi and Hinglish (`backend/evalsuite/ai_lures.jsonl`, run with
  `python -m evalsuite.ai_lures`). It reports "caught" and "false alarms" against today's 84%.
- **Ask:** if that number is clearly lower, retrain so paraphrased (AI-written) scam messages are
  caught, keeping false alarms at about 0. Same JSON format, new vectors.

## 3. "Looks AI-written" message classifier (new, on the phone)

**What it's for:** the app's Message check screen labels an SMS from a personal or unregistered
sender as "Looks AI-written" (never "is AI"). Registered business headers like `VM-HDFCBK` are
skipped by the app, so the model never sees bank alerts or OTPs.

**Train on:** synthetic data. AI-written or AI-paraphrased messages (scam and harmless) vs
human-style SMS (short, informal, typos, Hinglish, abbreviations), in English, Hindi and Hinglish.

**Deliver** to `ml/model/artifacts/`:

| File | What |
|---|---|
| `ai_text.json` | the model, scored in plain Kotlin like `lure.json` (char n-gram TF-IDF + logistic regression is fine), with a `version` and a recommended `threshold` |
| `ai_text_vectors.json` | test texts with expected `probability` (to 1e-6) and `label`, so the app's Kotlin can be checked against Python |
| a short metrics note | accuracy on held-out phrasings, false "AI-written" rate on human-style SMS, per language |

**Limits:**
- under 2 MB;
- under 20 ms per message on a mid-range phone;
- text never leaves the phone.

The label is a hint shown to the user. It never changes a payment's tier.

## 4. Later: device model (`ml/PLAN.md` M4b)

- `device_model.json` + `DeviceModel.kt` reference + vectors.
- The contract then gets `context.device_model = {version, c, l, b, p, reasons}`. Jagdeep adds it
  (rule 8), and Manjeet / Jagdeep wire it in the app.

## 5. Policy numbers

Suggested tier thresholds, or family weights from tuning: send them as a change to
`backend/api/policy.yaml`, with the evaluation numbers that support them. Don't put numbers in code.

## What you get from the system

- `backend/features/build.py`: the one feature definition (training must import it).
- `GET /v1/payments/{id}/explain`: shows each model's scores and `signals` to analysts, so you can
  see what the model is doing on live payments.
- `GET /v1/transactions` and `store.export`: every decision, for error analysis.
- Evaluation sets and scripts in `backend/evalsuite/` (AI-written lures) and `data/eval/`.

## Findings from the demo agents (2026-10-23, `lgbm-0.2`, live data)

`python -m demo.agents --all` (or "Run demo scenarios" on the console's Overview) runs one scripted
victim per scam type through the real API. With the rules every scenario lands as expected. With
`lgbm-0.2`:

| Scenario | Rules | lgbm-0.2 | Why (from `/v1/payments/{id}/explain`) |
|---|---|---|---|
| Refund QR (unknown call, QR, pumped demo mule) | T3 | **T0** | the model's payee family is 0.30 for the demo mule (rules: mule-like, large), so only C lights |
| Digital arrest (call, remote app, arrest SMS, "government") | T3 | **T2** | all four families lit, but `p_scam` 0.736 < the T3 cut 0.75 |

Ask: check the payee family on a freshly pumped mule (many strangers, fast pass-through, 4 days
old), and the calibration near the T3 cut, before the demo.
