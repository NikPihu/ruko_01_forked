# AI-written scam messages test

**Question.** Scammers now use AI to write polished, personalised, urgent messages in new words.
Does the lure model, trained on known scam templates, still catch them?

**The test set.** `backend/evalsuite/ai_lures.jsonl`:
- **Scam messages:** written the way AI writes them, in English, Hindi and Hinglish, with phrasings
  the model never saw (arrest threat, KYC, task job, trading tip, refund).
- **Honest look-alikes:** real OTPs, bank and RBI notices, real refunds, family and work messages.

**How it is scored.**
- **Command:** `PYTHONPATH=backend;ml;data python -m evalsuite.ai_lures`.
- **Same scoring as the phone:** it uses the model's own Python scorer (`ml/model/lure_train.py`)
  and the phone's 0.6 send threshold, so it measures exactly what the app would flag.
- **Output:** `backend/evalsuite/ai_lures_results.json`, served by `GET /v1/eval` (`ai_lures`) and
  shown as a card on the console's **Evaluation** page.

**Latest result** (`lure-0.1`):

| Measure | Result |
|---|---|
| Scam messages caught | 96% (on unseen templates the earlier baseline was 84%) |
| Right scam type | 88% |
| False alarms on honest messages | 0% |

The set is small and hand-written, so treat these as a smoke test, not a benchmark.

**Who does what.** The model is in `ml/`. If the number drops, ML retrains, and the test
re-runs on the new `lure.json`. The separate "looks AI-written" classifier for the app is in
[message-check.md](message-check.md).
