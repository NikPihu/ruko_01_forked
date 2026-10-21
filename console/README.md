# RUKO analyst console

A web app for fraud analysts. It reads the risk engine's API and shows, in plain words:

| Page | What it answers |
|---|---|
| **Overview** | What RUKO stepped in on, which rings need a look, and whether the evidence log is intact |
| **Alerts & cases** | Every payment RUKO warned on, paused or held (`/v1/alerts`), and every task-scam case opened from phones' episode reports (`/v1/cases`) |
| **Case detail** | What RUKO did and why (reasons in words), the scam journey (contacted → hooked → paying), the evidence record, and the money flow around the payee |
| **Mule suspects** | Accounts the payment graph links to scam accounts, grouped by ring, with approve / reject. A suspect counts in live checks only after two different analysts approve it. |
| **Account explorer** | Any UPI ID's money flow in one picture: who sent “rewards” → which RUKO users → who they paid → where that money went next, with the money loop in red |
| **Evaluation** | Today's systems vs + phone episode vs + payment graph, and how early mules are found before the registry lists them |

The money-flow picture comes from `GET /v1/graph/story/{upi}`. The engine collapses the graph into
four columns plus any loop back, and writes the sentences shown above the picture
(`backend/graph/store.py`, `GraphStore.story`).

## Run it

The engine serves the built console, so normally you only need:

```bash
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -BaitPump
```

Then open http://127.0.0.1:8000/console/. The script builds the console if `console/dist/` is
missing; pass `-BuildConsole` to rebuild it after changes. It needs Node.js 18 or newer.

While working on the console itself:

```bash
cd console
npm install
npm run dev
```

The dev server runs at http://localhost:5173/console/ with hot reload. It proxies `/v1`, `/health`
and `/sim` to the engine on port 8000; set `RUKO_API` to use another address.

## Notes
- Users appear only as pseudonyms (`User 506119`). Payees, bait senders and cash-out accounts are
  shown in plain text, because analysts need to look them up.
- The raw score (`p_scam`) is never shown, only tiers, bands and reasons in words.
- Colours follow fixed roles and are always paired with a label or text:
  - orange: sent "rewards";
  - blue: RUKO users;
  - aqua: paid by users;
  - grey: money moved on;
  - red: money loop.
- Light and dark mode follow the OS setting.
