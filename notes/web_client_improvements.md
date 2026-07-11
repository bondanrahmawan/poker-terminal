# Web Client Improvements — v1.1

**Status:** §1 (baseline commit) and §2 (event captions + history) are DONE
(commits `0ef7b87`, `999ef44`, verified against A5). Remaining work: §3 and §4.
Note: an uncommitted one-line fix in `web/app.js` guards the skip flag with
`S.animating` (a stray felt-click between hands used to fast-forward the next
hand's animation) — include it in your first commit.
**Audience:** an implementer in a fresh context window. Read
`notes/browser_play_assessment.md` first (§4 = the as-built API contract,
§6 = the client UX spec). This document covers four user-requested improvements
plus the glue they need, grounded in the code that actually exists today.

---

## 0. Current client state (verified 2026-07-12)

Implemented (uncommitted — see §1): steps 5.0–5.2 of the browser plan.

```
web/index.html   (60 lines)   settings form + table skeleton + raw-view <details>
web/app.js       (277 lines)  snapshot-only rendering; WS "events" IGNORED (app.js:48)
web/style.css    (99 lines)   dark felt theme, absolute-positioned seats on an ellipse
api/server.py                 + StaticFiles mount (only diff vs committed version)
run_web.py, play.bat          launcher: free port + auto-open browser
```

What works: create table → play hands end-to-end over WS → raise slider with
Min/½ Pot/Pot/Max shortcuts → "Next hand" button.

What is missing (and why the four complaints happen):

- **`ws.onmessage` drops `"events"` messages** (app.js:40–49). After you act, the
  server resolves every bot action instantly and the client just re-renders the
  final snapshot → opponent actions are invisible (complaint 3) and there is no
  data feed for a history panel (complaint 4).
- **No layout alternative** — the ellipse table needs a wide viewport; on a phone
  the absolutely-positioned seats overlap (complaint 1).
- **No chip refill** — the server only supports rebuy-at-zero via
  `POST /games/{id}/hands {"rebuy": true}`, and the client doesn't even call
  that; `nextHand()` (app.js:60) surfaces raw 409 reasons as status text
  (complaint 2, plus the missing §6.5 flow).
- Also missing from the v1 spec (not requested, but intersects — see §6):
  reconnect/restore (`localStorage["poker.gameId"]` is written, never read),
  between-hands overlay, keyboard shortcuts.

Known landmine for whoever adds reconnect: **`ws.onopen` auto-POSTs `/hands`
every time the socket opens** (app.js:30–38). Correct today (socket opens once,
right after game creation) but wrong the moment reconnect exists — a mid-hand
reconnect would 409, and a between-hands reconnect would silently start a hand.
Fix as part of A2 below: only auto-start when `S.view.hand_number === 0`.

---

## 1. Before any work: commit the baseline

`web/`, `run_web.py`, `play.bat` are untracked and the `api/server.py` static
mount is an uncommitted modification. First commit them as-is (message like
`web client v1: snapshot rendering (steps 5.0-5.2)`), so each improvement below
lands as its own reviewable commit on top of a known-good baseline.

---

## 2. Improvement A — opponent actions visible + history panel (complaints 3 & 4)

These two share one foundation — consuming the event stream — so build them
together. This is steps 5.3 of the browser plan (§6.3 has the full design and
dwell-time table); below is the integration guide against the current `app.js`.

### A1. Event plumbing

Extend client state:

```js
const S = {
  ...existing,
  lastSeq: -1,        // highest event seq seen (dedupe + backfill cursor)
  queue: [],          // events awaiting animation
  animating: false,
  pendingView: null,  // snapshot held back until the queue drains
  skip: false,        // fast-forward flag
};
```

`ws.onmessage` becomes:

- `"events"` → filter `ev.seq > S.lastSeq` (THE dedupe rule — the server may
  resend), push to `S.queue`, start the pump if idle.
- `"view"` → if `S.animating || S.queue.length` hold it in `S.pendingView`
  (newer replaces older); else apply + `render()`. Also: whenever a view is
  applied and `S.lastSeq < view.last_event_seq` with an empty queue (e.g. the
  connect-time view), snap `S.lastSeq = view.last_event_seq`.

### A2. The pump (keep it minimal — captions, not choreography)

```js
async function pump() {
  S.animating = true;
  while (S.queue.length) {
    const ev = S.queue.shift();
    S.lastSeq = ev.seq;
    appendHistory(ev);                       // A4 — every event, always
    const line = eventText(ev);              // A3
    if (line) showCaption(ev, line);         // banner + seat highlight
    await sleep(S.skip ? 0 : dwellFor(ev));  // §6.3 table; skip → 0
  }
  S.skip = false; S.animating = false;
  if (S.pendingView) { S.view = S.pendingView; S.pendingView = null; render(); }
}
```

Visuals per event stay cheap (browser plan §9 guardrail): a caption banner
(fixed strip between `#felt` and `#hole`, id `#caption`) plus a `.acting` CSS
class on the actor's seat (gold outline, removed when the next event starts).
No chip movement, no card-flip animation in this pass. Reveal of community
cards may simply wait for the final snapshot — the `street_started` caption
("FLOP — 7♠ K♦ 2♥") carries the information.

Skip affordance: a click anywhere on `#felt` sets `S.skip = true` (drains
instantly). Also auto-skip when `document.hidden` (mobile tab switch).

**Action-bar gating:** `renderActionBar` currently runs on every snapshot.
Gate it: while `S.animating`, render the bar disabled — otherwise the bar
unlocks before the player has seen why it's their turn.

### A3. `eventText(ev)` — one renderer, two consumers

A pure function `event → string | null`, used by both captions and the history
panel. Payload fields per `notes/gui_api_implementation_plan.md` §3.2; player
names are inside the payloads (`data.name`) — no id→name lookup needed.

| type | text (null = no caption, history-only) |
|---|---|
| `hand_started` | `— Hand #12 · blinds 10/20 —` |
| `seating` | null |
| `hole_cards_dealt` | null (it's always your own after filtering; the hole-card render covers it) |
| `blind_posted` | `Bot 2 posts SB 10` / `… posts ante 5` |
| `street_started` | `FLOP · 7♠ K♦ 2♥` (cards from `data.cards_dealt[].display`) |
| `action_taken` | `Bot 3 raises 60 · pot 180` (folds: `Bot 3 folds`) |
| `showdown_started` | `— Showdown —` |
| `hole_cards_shown` | `Bot 1 shows A♠ K♦ — Two Pair` |
| `pot_awarded` | `Bot 1 wins 340` |
| `hand_ended` | `Hand over` |
| `blinds_raised` | `Blinds up: 20/40` |

### A4. History panel

- Markup: `<div id="history"></div>` — on desktop a right-hand column
  (`#table` becomes a two-column flex: main column + 260px history), on
  narrow screens / simple mode (§3) a block under the action bar. Collapsible
  via a header button; collapsed state in `localStorage["poker.history"]`.
- `appendHistory(ev)` appends `eventText(ev)` (skip nulls), auto-scrolls to
  bottom, caps at the **last 300 lines** (drop from the top). `hand_started`
  lines get a separator style.
- **Backfill:** on entering the table (and later on every reconnect), fetch
  `GET /games/{id}/events?since=-1`, run each through `appendHistory` WITHOUT
  animating, and set `S.lastSeq` to the last seq. (Server already filters hole
  cards per viewer — `events_for("h1")`.)

### A5. Acceptance criteria

- [ ] After the human folds preflop, the remaining bot-vs-bot hand plays out
      visibly (captions sequence at readable pace) instead of snapping.
- [ ] Clicking the felt fast-forwards instantly to the final state.
- [ ] History shows the full hand including blinds, streets with cards,
      showdown reveals, and winnings; survives 50+ hands without slowdown
      (300-line cap working).
- [ ] Action bar never enabled while captions are still playing.
- [ ] No event rendered twice (dedupe) — verify by watching seq order in
      history after several hands.

---

## 3. Improvement B — simple display mode + mobile (complaint 1)

A compact list layout: no felt ellipse, no absolute positioning — just stacked
rows. This is ALSO the mobile layout, so one feature solves both.

### B1. Mechanism: CSS-only mode switch

The seat/center DOM already carries all information; only the geometry is
fancy. Absolute positioning is applied via `left/top` inline styles +
`position: absolute` in CSS — and inline `left/top` are inert once
`position: static`. So simple mode is a body class, zero JS rendering changes:

```css
body.simple #felt { height: auto; background: none; border: none; border-radius: 0; }
body.simple #seats { position: static; display: flex; flex-direction: column; gap: 4px; }
body.simple .seat  { position: static; transform: none; width: 100%;
                     display: flex; gap: .6rem; align-items: baseline; text-align: left; }
body.simple #center { position: static; transform: none; margin: .6rem 0; }
```

Seat row content order works as-is (name+badges, chips, bet). Add a small
`role` alignment tweak if needed, but resist restructuring the DOM.

### B2. Toggle + persistence + auto-default

- A `Simple view` toggle in `#table-header` (checkbox or button).
- Persist in `localStorage["poker.simple"]` (`"1"`/`"0"`).
- Default when unset: ON if `matchMedia("(max-width: 640px)").matches`.
- Apply on load: `document.body.classList.toggle("simple", isSimple())`.

### B3. Mobile touch pass (small, do in the same commit)

- Buttons: `min-height: 2.75rem` under `@media (max-width: 640px)`; raise
  slider `width: 100%`.
- `#table` two-column layout (from A4) collapses to one column under 640px,
  history below the action bar.
- Seat font down to `0.8rem`; caption strip stays visible without scrolling
  (action area anchored near the bottom of the viewport).

### B4. Acceptance criteria

- [ ] In simple mode everything fits a 375px-wide viewport with **no
      horizontal scroll** and no overlapping seats (test devtools iPhone SE).
- [ ] Toggle persists across reload; first visit on a phone defaults to simple.
- [ ] Full (felt) mode is pixel-identical to today when the toggle is off.
- [ ] A complete hand incl. raise via slider is playable by touch only.

---

## 4. Improvement C — chip refill / top-up (complaint 2)

Rebuy today only exists at exactly 0 chips (server: `sessions.py::start_next_hand`).
The request is refilling at will — e.g. short-stacked at 120 chips. This needs a
small server addition; it's the only backend change in this doc.

### C1. Server — `GameSession.topup()` (api/sessions.py)

```python
def topup(self) -> None:
    """Add starting_chips to the human stack. Only between hands."""
    if self.game.pending_request is not None or self.game.state != GameState.WAITING:
        raise HandInProgressError()
    human = self._human()
    amount = self.settings["starting_chips"]
    human.chips += amount
    self.game.stats[human.player_id]["total_invested"] += amount
    self.game.stats[human.player_id]["rebuys"] += 1
```

Import `GameState` from `core.state`. Design decisions (deliberate, keep):
- **Fixed amount = starting_chips**, mirroring the TUI rebuy and the benchmark
  rebuy semantics — no arbitrary amounts in v1 (keeps stats interpretation
  clean: `net = chips - total_invested` stays honest, `rebuys` counts top-ups).
- **Between hands only** — mid-hand chip injection would corrupt pot logic.
- Allowed even when not short-stacked (harmless; it's single-player).
- No engine (`core/`) changes — chips/stats mutation from the session layer is
  exactly what `start_next_hand`'s rebuy already does.

### C2. Server — endpoint (api/server.py)

`POST /games/{game_id}/topup` — same shape as the other mutating endpoints:
lock → `session.touch()` → `session.topup()` → on `HandInProgressError` return
`409 {"reason": "hand_in_progress"}` → else `_broadcast(session)` and return
`{"view": session.view()}`.

### C3. Server — tests (tests/test_api.py, extend)

- [ ] Top-up before any hand: chips double, `total_invested` doubles,
      `rebuys == 1`.
- [ ] Top-up while a hand awaits the human's action → 409, chips unchanged.
- [ ] After top-up, a hand plays normally and chip conservation holds.

### C4. Client

- **Add chips** button rendered next to **Next hand** (the
  `state === "END" || state === "WAITING"` branch of `renderActionBar`),
  labelled `Add chips +{starting_chips}`. The client knows starting_chips from
  the settings form; simpler and more robust: read it from the POST response
  view — add nothing, just label it `Add chips` and let the resulting view
  broadcast update the stack display.
- While in there, finish the §6.5 flow that `nextHand()` stubs out
  (app.js:60–67): on `409 busted` show a **Rebuy & continue** button (POST
  `/hands` with `{"rebuy": true}`); on `409 game_over` swap the action bar for
  a `Game over — {winner} wins` banner + **New game** (clear
  `localStorage["poker.gameId"]`, back to settings).

### C5. Acceptance criteria

- [ ] Short-stacked (not busted) player can add chips between hands; stack and
      history/status reflect it immediately (broadcast received).
- [ ] Mid-hand the button is absent; a raced request shows the rejection
      without breaking the session.
- [ ] Busted → Rebuy button works; game-over → New game works.
- [ ] `GET /stats` shows the top-ups in `rebuys`/`total_invested`.

---

## 5. Suggested order & commits

| # | commit | contents |
|---|---|---|
| 0 | `web client v1: snapshot rendering` | commit the existing baseline (§1) |
| 1 | `web: event captions + history panel` | §2 (A1–A5) — biggest UX win first |
| 2 | `web: simple/mobile display mode` | §3 |
| 3 | `api+web: chip top-up + rebuy/game-over flow` | §4 (only commit touching Python; run `pytest`) |

Each commit leaves the game fully playable. Test after every commit:
`python run_web.py`, play ≥2 hands; for commit 3 also `python -m pytest tests/ -q`.

## 6. Explicitly out of scope (v1.2 candidates, do not drift into them)

- Reconnect/session restore (browser plan §7) — the natural next item,
  especially for mobile, but it interacts with the `ws.onopen` auto-start
  landmine (§0) and deserves its own pass.
- Keyboard shortcuts, sounds, chip/card animations beyond captions.
- Arbitrary top-up amounts, cash-game mode in the browser, multi-human tables.
