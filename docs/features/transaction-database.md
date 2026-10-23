# Transaction database

**What it does.** Keeps every payment check with its full decision, so the console, the app's
history and later model training all read the same records.

**How it works.**
- `backend/store/db.py` (`TxnStore`), SQLite **in memory** by default: empty on every start, and
  each test gets its own. `python -m api.main --db logs/ruko.db` keeps a run in a file.
- Writes happen off the payment's path (`persist()` runs in a background thread), so they never
  slow down `/v1/decide`.
- Users are stored as pseudonyms (rule 7). Payees stay plain, because they must be looked up.

**Tables:**

| Table | What's in it |
|---|---|
| `payments` | one row per check: tier, reasons, message key, playbook, pause, outcome |
| `decision_details` | analyst only: every feature, `p_scam`, family scores, lit families, policy steps, intel status, stage path, signals |
| `feedback` | alert actions |
| `watch_events` | early warnings |
| `episode_events` | task-scam watcher events |
| `cases`, `trusted_payees`, `reviews`, `pattern_reviews` | analyst work |

**Reads:**
- `GET /v1/transactions`, with filters: user, payee, minimum tier, status, time range.
- `GET /v1/transactions/{id}`.
- `GET /v1/users/{hash}/timeline`.
- `GET /v1/me/payments` (the app's history; words only, no score).
- `GET /v1/store/stats`.

**Export for training:**
`python -m store.export --db logs/ruko.db --out logs/exports/transactions.parquet`.

**Try it.** Run the demo agents, then open the console's **Transactions** page.
**Tests:** `backend/tests/test_store.py`.
