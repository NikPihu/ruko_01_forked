# Explanations: short for the user, complete for the analyst

**What it does.** Every decision can be explained at two levels.
- **The user** sees the level in words, the scam type and the top 1 to 3 reasons, in English or
  Hindi. Never a score: a scammer holding the phone could use it to probe RUKO (rule 4).
- **The analyst** sees every number behind the same decision.

**How it works.**
- **Stored at decide time:** the engine stores the full detail of each decision in
  `decision_details` (see [transaction-database.md](transaction-database.md)).
- **Built on request:** `GET /v1/payments/{id}/explain` (`backend/api/explain.py`) returns:
  - `user_view`: exactly what the app showed (tier, at most 3 reasons, message key, playbook, pause);
  - `scores`: `p_scam`, the score of each family (C context, L lure, P payee, B behaviour), and
    which families were lit;
  - `reasons`: each reason with the inputs behind it and how strong it was;
  - `playbooks`: every playbook rule checked, and the one that matched;
  - `policy_steps`: how the policy got to the tier (corroboration, amount caps, trusted payee,
    alert budget);
  - `sources`: what each intel source answered (NPCI, bank, registries, FRI);
  - `stage_path`: the scam stages this user went through;
  - `signal_source`: which signals were real and which came from the debug panel;
  - the scorer and policy versions.
- **Console:** the **Payment explanation** page (open a row on Transactions) starts with
  **"Why T3"** (`summary` in the response). It has:
  - one sentence on why ("a pause with a trusted-person call, because 3 of 4 kinds of evidence
    were lit (2 needed)");
  - a graph read left to right: each fact in words with its real value (e.g. "13 different people
    paid it in 7 days", "18× the user's biggest payment in 90 days") → the four kinds of evidence,
    lit ones first (score bar, red when lit) → the decision. Facts sit next to their own kind, so
    lines never cross; lit kinds feed the decision with a thick red line;
  - then the scam type and what the tier needed.

  Below that are the full number tables. `INPUT_WORDS` in `explain.py` has the words for each
  input; unknown or false inputs are never listed (rule 1).
- **App:** `ui/alerts/` shows `user_view` only. `AlertText.kt` turns the message key into words;
  an unknown key falls back to the tier's general text.

**Tests:** `backend/tests/test_explain.py`. Among other things, it checks that the app's view never
contains a score.
