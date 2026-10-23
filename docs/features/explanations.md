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
- **Console:** the **Payment explanation** page (open a row on Transactions) draws a linking
  graph (user, payee, caller, mule accounts) next to the number table.
- **App:** `ui/alerts/` shows `user_view` only. `AlertText.kt` turns the message key into words;
  an unknown key falls back to the tier's general text.

**Tests:** `backend/tests/test_explain.py`. Among other things, it checks that the app's view never
contains a score.
