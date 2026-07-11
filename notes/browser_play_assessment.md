# Browser Play Assessment — Making Poker Terminal Playable in a Browser

**Status:** Backend (engine plan Phases 1–4) is IMPLEMENTED and tested; the
browser client (Phase 5, `web/`) is NOT yet built — that is the remaining work.
**Relationship to other docs:** This builds ON TOP of
`notes/gui_api_implementation_plan.md` (the engine/API plan). This document
assesses what *browser play specifically* requires beyond that plan, decides the
frontend stack, and specs the client as **Phase 5**. §4 documents the API
contract **as actually built** — where this doc's prose and the running code in
`api/` disagree, the code wins.

**Audience:** an implementer starting with a fresh context window.

---

## 1. Verdict / TL;DR

Making this game playable in a browser is very achievable and the engine work is
already fully specified. The genuinely new work is:

1. **A frontend client.** Recommendation: a **single-page vanilla-JS client with no
   build step** (one `index.html` + `app.js` + `style.css`, served as static files
   by the same FastAPI process). No React, no Vite, no npm. Rationale in §3.
2. **One backend line:** the StaticFiles mount (§4 item 1). The REST/WS API is
   already implemented and tested; §4 records its as-built contract, including
   the reconnect model (REST snapshot + event backfill).
3. **A small amount of UX design** that has no terminal equivalent: table layout,
   action bar with bet sizing, event pacing/animation (the engine resolves all bot
   actions instantly — the browser must *replay* them at human speed), and
   between-hands flow (next hand / rebuy / game over).

Total new code estimate: ~600–900 lines of JS/HTML/CSS + ~10 lines in
`api/server.py` (the static mount). Nothing in `core/`, `players/`, or `strategies/` changes beyond
what the engine plan already specifies.

The single biggest design issue unique to the browser is **event pacing** (§6.3):
after the human acts, the engine synchronously plays every bot until it's the
human's turn again, so the client receives a burst of events at once and must
animate them sequentially or the game feels like a slot machine. This is a
client-side queue problem, not an engine change.

---

## 2. What already covers us vs. what's new

| Need for browser play | Covered by engine plan? | Where |
|---|---|---|
| Engine pauses for human input | ✅ Phase 2 (`advance`/`submit_action`, `AgentPlayer`) | gui_api_implementation_plan.md §4 |
| JSON game state, hidden-info filtering | ✅ Phase 3 (`view_for`, `events_for`) | §5 |
| HTTP + WebSocket transport | ✅ Phase 4 (FastAPI) | §6 |
| Serving the web page itself | ❌ new | this doc §5.1 |
| Frontend app (rendering, input) | ❌ new | this doc §6 |
| Event pacing / animation | ❌ new | this doc §6.3 |
| Reconnect after refresh/tab close | ⚠️ partially (events cursor exists); needs a contract | this doc §7 |
| Between-hands flow (next hand, rebuy, game over) | ⚠️ endpoint exists (`POST /hands`); needs UI flow | this doc §6.5 |
| Settings screen (replaces `main.py` prompts) | ⚠️ `POST /games` exists; needs UI | this doc §6.4 |
| Stats screen | ⚠️ `GET /stats` exists; needs UI | this doc §6.6 |

Out of scope for v1 (deliberate cuts): multiplayer humans, auth/accounts, benchmark
modes in the browser (they stay TUI-only), persistent stats browsing UI
(`stats_persistent.py` stays terminal), mobile-first layout (desktop-first, but use
responsive units so it degrades acceptably), sound.

---

## 3. Frontend stack decision

Three candidates were considered. **Choose Option A.**

### Option A — Vanilla JS single-page app, no build step ✅ RECOMMENDED

`web/index.html` + `web/app.js` + `web/style.css`, served by FastAPI's
`StaticFiles`. ES modules if file-splitting is wanted, but plain `<script>` is fine.

- **Pros:** zero toolchain (project currently has *no* Node, no npm, no bundler —
  and the Python side is stdlib + FastAPI only); one process serves everything
  (`uvicorn api.server:app` → open `http://localhost:8000`); trivially debuggable;
  a lesser model cannot get lost in webpack/Vite config; card rendering is just
  text (`A♠`) + CSS — no assets needed.
- **Cons:** manual DOM updates; state management is hand-rolled. At this app's size
  (one table, ~6 screens-worth of UI) that is genuinely fine.

### Option B — React (or Svelte/Vue) + Vite

- **Pros:** declarative rendering suits "state snapshot → UI" well.
- **Cons:** introduces Node/npm toolchain, a build step, `node_modules`, and a
  second dev server with proxying to FastAPI. For a single-table hobby game this
  is machinery without payoff, and it doubles the surface where an implementing
  model can go wrong. Rejected for v1; nothing in the design blocks migrating
  later (the client talks to a clean JSON API either way).

### Option C — Server-rendered (Jinja templates + HTMX)

- **Cons:** poker is a push-driven realtime UI (opponent actions arrive while you
  idle); HTMX-over-WS works but fights the grain, and animating event bursts is
  awkward. Rejected.

---

## 4. Amendments this makes to Phase 4 of the engine plan

> **UPDATE (2026-07-12): Phases 1–4 are implemented and merged** (`core/events.py`,
> `core/action_request.py`, `core/views.py`, `players/agent.py`, `api/` package;
> 262 tests green including `tests/test_api.py`). The backend was built from the
> engine plan as written, WITHOUT some amendments this section originally proposed.
> **The as-built API below is now the contract — adapt the client to it; do not
> change working, tested endpoints.** The ONE remaining server change is the
> StaticFiles mount (item 1).

1. **Static serving (the only backend change left):** in `api/server.py`
   (inside `create_app()`, after all routes are registered), add:
   ```python
   from fastapi.staticfiles import StaticFiles
   app.mount("/", StaticFiles(directory="web", html=True), name="web")
   ```
   There is NO `/api` prefix — routes live at `/games/...`. That is fine: routes
   registered before the mount take precedence, so `/games/...` still resolves to
   the API and everything else falls through to `web/`.
2. **Same-origin only, no CORS config.** The page is served by the same process as
   the API. Do not add CORS middleware — its absence is a feature (nothing else
   should call this).
3. **Division of labor (as built): WS for in-hand play, REST for everything else.**
   - WS `ws://…/games/{id}/ws` — receive pushes; send actions while in a hand.
   - REST — create game, start next hand (incl. rebuy), reconnect sync, stats:
     `POST /games`, `POST /games/{id}/hands`, `GET /games/{id}/state`,
     `GET /games/{id}/events?since=`, `GET /games/{id}/stats`, `DELETE /games/{id}`.
4. **WS message protocol as built (server → client):**
   ```jsonc
   {"type": "view",   "view": { ...view_for("h1")... }}       // full snapshot; also sent once on connect
   {"type": "events", "events": [ {seq, type, data}, ... ]}   // incremental
   {"type": "error",  "reason": "no_pending"|"bad_action"|"illegal", "detail": "..."}
   ```
   **(client → server)** — a single flat message shape, no `type` envelope:
   ```jsonc
   {"action": "fold"|"check"|"call"|"raise"|"all-in", "amount": 0}
   ```
   There is **no `next_hand` and no `sync` over WS.** Starting the next hand is
   `POST /games/{id}/hands` (body `{"rebuy": true}` when rebuying); it returns
   `409 {"reason": "busted"|"game_over"|"hand_in_progress", ...}` for the special
   cases (`game_over` includes `"winner"`). Reconnect sync is REST (§7).
   After every successful state change the server broadcasts `events` (since the
   previous broadcast) then `view` to ALL sockets of the session. Errors go only
   to the offending socket; game state is unchanged.
5. **Idempotency guard:** the server keeps ONE shared broadcast cursor per session
   (`drain_new_events`), not per connection. Consequences the client must handle:
   (a) drop any event with `seq <= lastSeenSeq` (dedupe is the client's job — it
   is the entire consistency model); (b) a socket that was disconnected during a
   broadcast has PERMANENTLY missed those events on the WS — recover via REST
   `GET /events?since=lastSeq`, never by waiting for a re-push.
6. **One session, many tabs:** allowed by design (broadcast to all sockets). No
   seat locking needed since every socket controls the same single human seat;
   last write wins, engine validation makes races harmless (second action gets an
   `error` with reason `no_pending`/`illegal`).

---

## 5. New deliverables (Phase 5)

### 5.1 File layout

```
web/
  index.html      # all screens as hidden/shown <section>s; no router
  app.js          # state, WS client, event queue, renderers (~400–600 lines)
  style.css       # table layout, cards, action bar (~200 lines)
```

Plus in `api/server.py`: ONLY the StaticFiles mount from §4 item 1. The rest of
the API is already implemented and tested — do not modify it.

### 5.2 Client state model (keep it this small)

```js
const S = {
  gameId: null,          // persisted to localStorage["poker.gameId"]
  view: null,            // last full view snapshot (source of truth for rendering)
  lastSeq: -1,           // highest event seq applied/animated
  eventQueue: [],        // events not yet animated (§6.3)
  animating: false,
  ws: null,
  phase: "settings" | "table" | "between_hands" | "game_over",
};
```

Rendering rule: **the view snapshot is truth; events drive animation only.** After
the event queue drains, re-render everything from `S.view`. This means animation
bugs can never corrupt game state display — worst case a snapshot render snaps
things to correct values.

---

## 6. Client UX spec

### 6.1 Screens (all in one HTML file, toggled by `S.phase`)

1. **Settings** — form mirroring `main.py::_collect_settings` fields: name,
   bot count (1..MAX_BOTS — hardcode the max to match `players/roster.py`),
   difficulty (easy/normal/hard radio), starting chips, big blind, hands/level,
   ante toggle, short-deck toggle, shuffle-seats toggle. Submit → `POST /api/games`
   → store `gameId` → open WS → send `next_hand` → phase `table`.
2. **Table** — the main screen (§6.2).
3. **Between hands** — overlay on the table showing the last `hand_ended` summary
   with buttons: **Next hand**, **View stats**, **Quit table**. If the human busted:
   **Rebuy & continue** / **Quit** instead (§6.5).
4. **Game over** — winner banner + final stats + "New game" (back to settings,
   clears localStorage key).

### 6.2 Table layout

Text-first aesthetic is fine and on-brand (the project is "poker *terminal*");
cards are text glyphs styled by CSS — red for ♥/♦ via a class on the card span
(`view` card dicts carry `suit`, so no parsing of the display string).

- Oval/rect table, up to 9 seats positioned by CSS (precompute seat coordinate
  classes for 2–9 players; human always bottom-center).
- Per seat: name, chips, role badge (`BTN`/`SB`/`BB`/…), bet-this-round chips in
  front of the seat, status dimming (folded → 40% opacity, busted → grayed,
  all-in → badge), and a turn highlight ring driven by... nothing in the view says
  whose turn a *bot* is — turn highlight is driven by the event animation (§6.3):
  highlight the seat of the event currently being animated.
- Center: community cards (5 fixed slots, face-down placeholders), pot total,
  and pot breakdown at showdown (`view.pots`).
- Human's hole cards rendered large near the action bar.
- A collapsible **hand log** panel (right side): human-readable rendering of the
  event stream, the browser equivalent of the TUI's history — reuse the same
  event→text mapping as animation captions.

### 6.3 Event pacing (THE browser-specific problem)

When the human acts (or a hand starts), the server replies with a burst: every bot
action, street deal, and possibly full showdown in one `events` push, because the
engine runs synchronously until it next needs human input. Rendering that
instantly is unplayable UX.

**Design: a serialized animation queue.**

- All incoming events (after seq-dedupe) append to `S.eventQueue`.
- A queue pump takes one event at a time, applies its visual (see table below),
  waits that event's dwell time, then proceeds. `async/await` + `setTimeout`
  promise is sufficient.
- The **fresh `view` snapshot is held back** until the queue drains, then applied
  (otherwise the pot/chips would jump ahead of the animation). Keep at most one
  pending snapshot; newer replaces older.
- The action bar unlocks only when the queue is empty AND `view.you.to_act`.
- A "skip" affordance: clicking anywhere on the table fast-forwards the queue
  (dwell times → 0). Essential for impatient players and for testing.

Suggested dwell times (constants at top of `app.js`):

| event | visual | dwell |
|---|---|---|
| `hand_started` | clear table, move dealer button, banner "Hand #N — blinds X/Y" | 800ms |
| `seating` | (re)position seats | 0 |
| `hole_cards_dealt` (yours) | flip your two cards up | 400ms |
| `blind_posted` | chips slide from seat, caption "posts SB 10" | 250ms |
| `street_started` | reveal community card(s) one by one | 400ms/card |
| `action_taken` | highlight seat, caption "Bot 3 raises 60", chips move | 650ms (fold: 350ms) |
| `hole_cards_shown` | flip opponent cards face-up + hand name label | 700ms |
| `pot_awarded` | pot slides to winner, "+340" float | 900ms |
| `hand_ended` | dim table, open between-hands overlay | 0 (terminal) |
| `blinds_raised` | toast "Blinds now 20/40" | 600ms |

### 6.4 Action bar

Visible only when it's the human's turn (`view.you.to_act`), populated from
`view.you.action_request`:

- Buttons rendered from `legal_actions` only: **Fold** / **Check** or
  **Call 20** / **Raise** / **All-in 880**.
- Raise flow: clicking Raise reveals a slider + number input, range
  `[min_raise_total, max_raise_total]`, with shortcut chips **Min / ½ Pot / Pot /
  Max** computed exactly like `players/terminal.py` does:
  `half = max(min_raise_total, floor(pot/2) + min_call)`,
  `pot = max(min_raise_total, pot + min_call)`, both clamped to stack.
  **Remember amounts are deltas** (chips pushed now), per the engine plan §1.4 —
  label the UI "raise **by** / total to put in" carefully; show the resulting
  total-in-front for clarity: `you're putting in {amt} (total this round {amt + bet_this_round})`.
- All-in gets a confirm (double-click or a 2-step button), mirroring the TUI.
- Keyboard shortcuts: `f` fold, `c` check/call, `r` focus raise input, `a` all-in.
- No action timer in v1 (single-player vs bots; nobody is waiting).

### 6.5 Between-hands & rebuy flow

Mirrors `main.py::_run_session` semantics, driven by the client:

- On `hand_ended`: overlay with chip deltas for the hand; **Next hand** does
  `POST /games/{id}/hands` (empty body). The resulting events/view arrive over
  the WS broadcast — the client does not need the POST response body beyond the
  status code.
- `409 {"reason": "busted"}`: client shows **Rebuy for {starting_chips}** →
  `POST /games/{id}/hands` with `{"rebuy": true}`. Rebuy bookkeeping is
  server-side, identical to the TUI path (adds to `total_invested` and `rebuys`).
- `409 {"reason": "game_over", "winner": "..."}` (or the client detects ≤1 funded
  player from the view): phase → `game_over`.
- `409 {"reason": "hand_in_progress"}`: client is out of sync — do a REST
  resync (§7 step 1) instead of retrying.

### 6.6 Stats screen

v1: a modal that renders `GET /games/{id}/stats` as a table — hands
played/won, win rate, net, best hand, rebuys per player. This is session stats
only (`game.stats`); the persistent cross-session stats system stays TUI-only.

---

## 7. Refresh / reconnect contract

Browser tabs die; this must be first-class, and it's cheap given Phase 3:

1. On page load: if `localStorage["poker.gameId"]` exists →
   `GET /games/{id}/state`. `404` (expired/unknown) → clear key, show settings.
   Otherwise: render snapshot immediately (no animation), set
   `lastSeq = view.last_event_seq`, append the log panel's history from
   `GET /games/{id}/events?since=-1` if desired, then open the WS. The server
   sends a fresh `{"type":"view"}` on connect — apply it (it may be newer than
   the REST snapshot).
2. Mid-game WS drop: auto-reconnect with exponential backoff (1s, 2s, 4s… cap
   10s). Because the server's broadcast cursor is shared (§4.5), events pushed
   while this socket was down are gone from the WS — so on every (re)connect,
   after the connect-time `view` arrives, fetch `GET /games/{id}/events?since={lastSeq}`
   to backfill the log/animation gap. Show a thin "reconnecting…" banner and
   disable the action bar while disconnected.
3. Server side: sessions already outlive sockets (SessionManager owns the Game;
   sockets are ephemeral) — the 2h idle TTL in `api/sessions.py` is the only cleanup.
   A paused game waiting on `pending_request` keeps waiting forever until TTL;
   that's correct for single-player.

Edge case: the human refreshes while it's their turn → the fresh `view` has
`you.to_act == true` and the full `action_request`, so the action bar reappears
with no server changes needed. This "resume mid-decision" case must be in tests.

---

## 8. Implementation order & effort

Prereqs: engine plan Phases 1–4 — **ALL DONE** (see §4 update box). Then:

| step | work | size |
|---|---|---|
| 5.0 | Add the StaticFiles mount to `api/server.py` (§4 item 1) + `web/` dir with a hello-world `index.html`; verify `python -m api.server` serves it | ~10 lines |
| 5.1 | Static skeleton: settings form → create game → WS connect → dump raw view as JSON on page (walking skeleton, proves the pipe) | ~120 lines |
| 5.2 | Table rendering from `view` snapshot only (no animation): seats, cards, pot, action bar, full hand playable | ~300 lines |
| 5.3 | Event queue + pacing + captions + hand log panel | ~150 lines |
| 5.4 | Between-hands / rebuy / game-over flows + stats modal | ~100 lines |
| 5.5 | Reconnect handshake + backoff + localStorage | ~60 lines |
| 5.6 | Polish: keyboard shortcuts, skip-animation, red suits, turn ring | ~80 lines |

Each step leaves the game playable end-to-end (5.2 onward). Commit per step.

**Testing:** `tests/test_api.py` already covers the REST/WS backend. Add WS tests
via `TestClient.websocket_connect` only for gaps found while building the client
(e.g. two-socket broadcast, reconnect backfill semantics, busted→rebuy over REST
while a WS is attached).
Client JS gets no test framework in v1 (would drag in Node); correctness leans on
the "snapshot is truth" rendering rule + manual checklist in the PR description.

---

## 9. Risks & open questions

1. **Event pacing complexity creep** — the queue in §6.3 is the part most likely
   to balloon. Guardrail: captions + CSS transitions only; no canvas, no chip
   physics. If an animation is hard, replace it with a caption + dwell.
2. **Delta-vs-total raise confusion** — highest-probability functional bug
   (engine plan pitfall #6). The action bar must display the computed outcome
   ("putting in 60 now") and tests must cover a re-raise after a prior call.
3. **Two sources of truth drifting** (animated state vs snapshot) — mitigated by
   the hold-back-snapshot rule; the final render always comes from `view`.
4. **Windows dev loop:** `uvicorn --reload` watches `web/` only if
   `--reload-dir web` is added; document the run command in README:
   `uvicorn api.server:app --reload --reload-dir api --reload-dir web`.
5. **Open question (non-blocking, default = no):** should bot "thinking" get an
   artificial server-side delay instead of client pacing? Decision: **no** —
   keep the engine instant (benchmarks depend on it) and pace purely client-side;
   it's also the only way "skip animation" can be instant.
6. **Open question (non-blocking, default = keep):** keep the TUI's
   `TerminalPlayer` on the blocking path indefinitely? Decision: **keep** — the
   browser client makes migrating the TUI to `AgentPlayer` pointless work.

---

## 10. Definition of done (v1 browser play)

- [ ] `uvicorn api.server:app` then opening `http://localhost:8000` lets a user:
      configure a table → play unlimited hands vs bots → raise via slider and
      shortcuts → see showdowns revealed at readable pace → rebuy when busted →
      reach game over → view session stats → start a new game.
- [ ] Refreshing the tab at ANY point (including mid-decision) resumes correctly.
- [ ] No opponent hole cards appear in any network payload before showdown
      (verify in devtools + automated leak test from engine plan Phase 3/4).
- [ ] `python main.py` TUI and all benchmark modes still work unchanged.
- [ ] `pytest` green, including new WS tests.
