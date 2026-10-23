# Mule rings, hubs and bot-scale rings

**What it does.** Finds the accounts behind scams, not just single payments. It shows groups of
mule accounts (rings), the accounts money flows through (hubs), and rings run by scripts or AI
chatbots at machine scale.

**Built from what RUKO could really see** (rule 9): the payment graph (`graph/store.py`) holds only
`/v1/decide` payments, `/v1/episode` accounts and the bank flows the visibility setting allows.
Never the simulator's ground truth.

**Suspects** (`graph/discover.py`): accounts ranked by crowd signal (many unrelated people paying),
money loops, fast pass-through and links to known mules.
- **Rule 11:** a discovered suspect affects live payments only after **two different analysts**
  approve it on the console's **Suspects** page.
- After approval, paying it lights the payee family (`payee_approved_suspect`).

**Rings and hubs** (`ring_view`, `hub_score`):
- **Ring:** suspects and known mules connected by money between them or by shared victims.
- **Hub score, 0 to 1,** from four plain parts:
  - fan-in: how many accounts pay it;
  - pass-through: money out / money in;
  - speed: money leaves within 30 minutes;
  - links to other ring members.
- **Console Scam rings page:** members, hubs, victims, money in and out, how fast it moves, and a
  graph per ring.

**Bot-scale ("automated") rings** (`graph/store.py` `automation`, numbers in `policy.yaml`
`automation:`): an account counts as automated when, over 7 days, at least 8 different people
are involved, the amounts per person are nearly the same (spread at most 10%), **and** the
timing is machine-like: either a steady rhythm (gap spread at most 35%) or a burst (new people under
a minute apart on average).

No human operation pays or collects ₹150 from 200 people, one every 4 minutes.
- **Engine:** `payee_automated` is payee-family evidence and gives reason R11 (ring link).
- **Console:** a "bot-scale" tag with the reason in words (e.g. "paid 212 people ₹150 each, one
  every 4 minutes").
- **Not tagged:** a real shop (varied amounts) and a payroll paying a few known workers.

**Tests:** `backend/tests/test_graph.py` (rings, hubs, two-analyst approval),
`backend/tests/test_automation.py`.
