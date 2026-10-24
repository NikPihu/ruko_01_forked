# Red / Blue console redesign: build brief

The new look for the red-team / blue-team console (`red_team_blue_team/blue_team/console.html`,
served by `blue_team/webapp.py`). This folder holds the approved mockups and everything needed to
build them. **Design only: nothing here is wired yet.**

- **Live mockups (clickable):** https://claude.ai/artifact/9xdc3rsC2fBWN43XMrmANb (the owner must
  share it with you from the page's Share menu).
- **Mockup source:** the six `*.dc.html` files here. Each one is a page mockup; the markup inside
  `<x-dc>` is the layout, and the data in `renderVals()` at the bottom is **sample data only**.
  The red-team playbook names and evasion tricks are real; every count is made up.
  They load `./support.js` from the design tool and won't open on their own: read them as
  layout and style references.
- **Owner:** `red_team_blue_team/` is Diwansu's folder (see `CLAUDE.md`). Agree with him before
  replacing `console.html`.

## The idea

Today there are 11 pages and you jump between them in no fixed order. The new console has
**4 tabs that follow the loop, left to right**, and replaces long explanations with short legend
rows:

| New tab | Mockup | Replaces today's pages |
|---|---|---|
| Overview | `Main.dc.html` | Overview, Scorecard |
| 1 · Attack | `Attack.dc.html` | Red team (runner, inbox, build world), Generate |
| 2 · Investigate | `Investigate.dc.html` | Complaints, Patterns (HDBSCAN), Timeline |
| 3 · Playbooks | `Playbooks.dc.html` + `PlaybookDetail.dc.html` | Review, Playbooks (database), Generator agent, Analyst agent |
| Live check (a side panel from the top bar, not a tab) | `LiveCheck.dc.html` | Live check (`#/demo`) |

Old hash links (`#/complaints`, `#/hdbscan`, `#/scorecard`, `#/run`, `#/generator`, `#/analyst`,
`#/database`, `#/demo`, `#/redteam`, `#/playbooks`) should redirect to their new place.

## Page by page, with data sources

Endpoints are the existing ones in `blue_team/webapp.py` unless marked **NEW**.

### Overview (`Main.dc.html`)
- **Loop strip** (4 cards: Attack, Investigate, Playbooks, Live check). Each shows one number and a
  state; the step that needs a human ("Your turn") is highlighted orange. Sources:
  `/api/redteam/runner` (got through / judged), `/api/runs/{run}/clusters` (groups, complaints),
  `/api/cards` (waiting / approved), `/api/scenario` (before → after).
- **Scam groups** (the main new idea, see "Scam groups" below). One card per group: how many of
  its attacks got through, the % of its scam payments RUKO called normal, complaints, and its
  playbook and that playbook's state. Filter: All / Leaking / New. Clicking a card opens Attack,
  filtered to that group.
- **Waiting for you:** cards in review that pass the gates (`/api/cards`), linking to the
  playbook page.

### 1 · Attack (`Attack.dc.html`)
- **Run bar:** set (`r.sets`), world size, progress, and **"Hand N breakthroughs to the blue
  team"**, which is today's "Build the attack world" (`POST /api/redteam/build`). Header buttons:
  Generate (red_team generator) and Run red team (`POST /api/redteam/runner`).
- **Attacks by group:** collapsible group rows (got through x of y, a red/blue bar, % called
  normal), each expanding to its playbooks with tricks (`TECH_SHORT`), called-normal % and
  Got through / Caught. Source: `/api/redteam` + `/api/redteam/runner` verdicts.
- **Right panel, selected attack:** description, tricks, 3 numbers, "Where RUKO lost it" (by step
  of the scam), a threat-score histogram with the 70 line, and links to its script and its
  complaints. Same data as the Streamlit `playbook_detail()` in `red_team/ui.py`
  (`results.csv` per playbook): **NEW** endpoint `GET /api/redteam/playbooks/{name}/detail`.

### 2 · Investigate (`Investigate.dc.html`)
- **Run progress strip** (replaces the Timeline page): Complaints → Got past RUKO → Grouped →
  Drafted → Checked → People. Source: `/api/runs/{run}/events` and `/clusters`. "New blue-team
  run" in the header (`POST /api/runs`).
- **Left list: groups** (HDBSCAN clusters + "misnamed?" subgroups), each with a kind chip
  (New / Known / Misnamed?), a missed-vs-unnamed bar, complaint count and next step.
- **Right: selected group:** map (today's scatter), "signals they share" (`top_tokens` as
  share bars), missed · unnamed, money lost, closest known playbook + similarity
  (`nearest_playbook`, `similarity`), "Open drafted playbook", and the complaints table with a
  legend for Missed / Unnamed / Held (`/api/runs/{run}/cases`).

### 3 · Playbooks (`Playbooks.dc.html`)
- One table for the review queue and the library: segmented filter Waiting / Live / Rejected /
  All, plus a group filter. Columns: playbook + one-line title, group, the analyst agent's verdict,
  Catches (`backtest.cluster_case_recall`), Honest / 1k (`legit_payments_named_per_1000`),
  Effect (Warns · families / Names only), sign-off avatars. Source: `/api/cards`.
- **Live in the engine:** the playbook file's order (built-in + approved), from `/api/database`.

### Playbook detail: "why it was chosen" (`PlaybookDetail.dc.html`)
The page that must explain itself. Source: `/api/cards/{name}` (+ `/yaml`, `/verify`).
- **Header:** name, state, New scam / Variant chip, Approve / Reject.
- **4 key numbers:** catches, scam payments named, honest per 1,000 (with the limit), effect.
- **"Why this playbook": a 7-step trail**, each with its evidence link:
  1. complaints RUKO let through (missed / unnamed, money lost) → Investigate;
  2. why they were grouped: the shared signals as chips;
  3. why it is not a known scam: closest playbook + similarity vs the "known" threshold
     (`known_similarity` in config);
  4. the generator agent's draft (link to its turns, today's Generator page, now a drawer);
  5. the analyst agent's verdict with a short quote of its `rationale` (link to its turns);
  6. code checks (gates) with their numbers and limits;
  7. people: who approved, who is still needed.
- **"The rule, condition by condition":** each rule leaf with its family badge (C/L/P/B),
  % of the group's complaints that have it, honest payments per 1k that have it, and one line on
  why. A last row for "all together". **NEW:** per-leaf backtest numbers (today `matcher.py`
  only backtests the whole rule).
- **"Why not a playbook we already have":** this group vs the 2 closest known playbooks, signal by
  signal. **NEW:** top-2 nearest with similarity (today the cluster keeps only the nearest one).
- **What the user sees:** `advice_en` / `advice_hi`; the stored YAML in a collapsed block.
- **Right rail:** sign-off (two slots, name, note, Approve / Reject; same rules as today: two
  different analysts, a note to reject), "After approval" (today's verify checks) and mule
  accounts going to graph review.

### Live check (`LiveCheck.dc.html`)
A glass side panel over the dimmed page, opened from the top bar. Steps: build world → round 1 →
review → round 2; three before → after bars (interrupted, named correctly, honest per 1k) and a
per-group table. Buttons: Start a new demo / Rerun with approved playbooks, agent picker.
Source: `/api/scenario` + `start` / `rerun`.

## Scam groups (NEW, the user's main ask)

Today the red-team numbers are one cumulative total. The new console shows **stats per group of
scams**, never one grand total. A group is a scam type:

1. A red-team playbook belongs to the group of the **known scam type it is closest to**: the
   cluster it dominates (`scorecard` rows already map playbook → groups), then that cluster's
   `nearest_playbook` when the analyst verdict is `variant_of_known` or the cluster is `known`.
2. If its cluster's drafted playbook got the analyst verdict **`new_scam`**, that playbook starts a
   **new group** (purple "New group"), named after the drafted playbook's title.
3. Not grouped yet (no complaints, or too few): fall back to its main lure tag (`task_job`,
   `kyc`, `arrest_threat`, …), shown as that known group with a "not grouped yet" note.

Suggested endpoint: **NEW** `GET /api/groups?run=` → `[{group, kind: known|new, playbook,
playbook_state, attacks, got_through, scam_payments, called_normal, complaints, members: [...]}]`,
used by Overview, Attack and the Playbooks group filter.

## Look and feel

AWS-console-like, but quieter. Values are in the mockups' inline styles; the main ones:

- **Ground** `#eef1f5`. **Top bar** `rgba(15,22,32,0.88)` with `backdrop-filter: blur(14px)`,
  sticky. Under it a **navy band** `#0f1620` with the page title in white; the first cards
  overlap the band (`margin-top: -76px`).
- **Cards:** `rgba(255,255,255,0.86)` + `blur(18px)`, border `rgba(15,23,42,0.08)`, radius
  14 to 16 px, shadow `0 12px 32px rgba(15,23,42,0.06)`. Glass is used only there, on the top bar
  and on the Live check panel.
- **Text:** ink `#0f141a`, secondary `#414d5c`, muted `#5f6b7a`. Fonts: Inter, JetBrains Mono for
  ids, Noto Sans Devanagari for Hindi.
- **Accent:** orange `#ff9900` for primary buttons (dark text `#0f141a`), the active tab underline
  and "your turn". Links `#0972d3`.
- **Meaning colours:** got through / missed `#d91515` (chip `#fdecea` / `#b0120d`), caught /
  interrupted `#0972d3` (chip `#e8f2fd` / `#0758a8`), new group `#5b2ca0` on `#f1ebfb`, waiting
  `#7a5300` on `#fff4d6`, approved `#036b0a` on `#e7f5e9`.
- **Legends, not paragraphs:** every chart or table has one legend row (coloured square + a few
  words). Term definitions go in the legend or the "?" button in the top bar, never in body text.

## Rules that still hold

- No LLM decides anything about a payment (CLAUDE.md rule 13): agents draft, code checks, two
  people approve.
- Two different analysts approve each playbook; a note is needed to reject (as today).
- The answer key (which journey ran which playbook) is used only for grading: the scorecard and
  group stats, never by the pipeline (rule 9). Say so in the "?" legend.

## Suggested build order

1. `GET /api/groups` + the Overview page (loop strip, group cards, waiting list).
2. The Playbooks table and the playbook detail page (trail first; per-leaf stats and top-2 nearest
   after).
3. Investigate (merge Complaints + Patterns + Timeline).
4. Attack (merge the Red team page + the per-attack detail endpoint).
5. The Live check panel, redirects for old links, and removing the old pages.

Keep the same stack as today (one `console.html`, no build step) unless the owner prefers
otherwise.
