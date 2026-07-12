# Web Client Improvements — v1.2 Assessment

**Status:** IMPLEMENTED — all three tiers (commits `bad5e30` Tier 1,
`35ef089` Tier 2, `5540b0f` Tier 3; 270 tests green). Kept for design record.
**Prereqs:** `notes/web_client_improvements.md` is fully DONE (commits `0ef7b87`,
`999ef44`, `10baa46`, `daa5509`; 265 tests green). Read
`notes/browser_play_assessment.md` §4 for the API contract. This doc is the
next tranche, found by auditing the running v1.1 client against the original
UX spec and the engine's unused capabilities.

Current client: `web/app.js` (523 lines), `web/index.html`, `web/style.css`.
Working: captions/history, simple+mobile mode, top-up, rebuy, game-over.

---

## Tier 1 — Reconnect & session restore (do first, own session)

**The gap:** refreshing the tab loses the game, even though the server keeps
the session alive for 2h and `localStorage["poker.gameId"]` is already written
(app.js:319) — it is just never read back. On mobile (the point of simple
mode) tab reloads are constant, so this is the most valuable remaining item.
Design reference: `browser_play_assessment.md` §7. Most machinery exists:
`backfillHistory()` already advances `S.lastSeq`, `applyView()` already snaps
the cursor, `GET /state` and `GET /events?since=` are live.

### R1. The auto-start landmine (fix first)

`ws.onopen` unconditionally POSTs `/hands` (app.js:58–66). With reconnect this
is wrong twice: mid-hand reconnect → spurious 409; between-hands reconnect →
silently starts a hand the player didn't ask for. Fix: only auto-start when
this is a brand-new game —

```js
ws.onopen = async () => {
  setStatus("");
  resetBackoff();
  if (S.view && S.view.hand_number === 0) { /* existing POST /hands */ }
  else await resyncEvents();   // R3
};
```

### R2. Restore on page load

On script start (before showing settings): if `localStorage["poker.gameId"]`
exists → `GET /games/{id}/state`. 404/network-fail → clear the key, show
settings. Success → `S.gameId`, `applyView(view)` (no animation),
`S.phase = "table"`, `render()`, `backfillHistory()` (fills the log AND sets
`lastSeq`), then `openWs()`. Mid-decision resume needs nothing extra: the view
carries `you.to_act` + `action_request`, so the action bar just reappears.

### R3. Reconnect with backoff

- `ws.onclose` → `setStatus("Reconnecting…")`, disable the action bar, retry
  `openWs()` after 1s, 2s, 4s… cap 10s (reset the delay on successful open).
  Do NOT reconnect after a deliberate close in `newGame()` — add a
  `S.closing` flag set there and checked in `onclose`.
- `resyncEvents()`: `GET /events?since=S.lastSeq` → feed through the normal
  queue/pump (animate if few, or append-only if you prefer — either is fine;
  dedupe makes it safe), then `GET /state` → `applyView` if the queue is idle.
  This is mandatory, not an optimization: the server's shared broadcast cursor
  means events pushed while this socket was down are never re-pushed
  (`browser_play_assessment.md` §4.5).

### R4. Acceptance criteria

- [ ] Refresh mid-decision → table restores, action bar shows the same
      choices, hand continues.
- [ ] Refresh between hands → table restores WITHOUT a new hand auto-starting;
      "Next hand" works.
- [ ] Kill the server, restart it (session gone) → client falls back to
      settings cleanly, no stuck "Reconnecting…".
- [ ] History panel is repopulated after refresh (backfill), no duplicate lines.
- [ ] `newGame()` does not trigger a reconnect loop.
- [ ] With devtools offline→online mid-hand: client recovers and shows the
      actions it missed (resync path).

---

## Tier 2 — Visibility & polish (client-only session)

### V1. Stats modal — the endpoint has NO UI today

`GET /games/{id}/stats` returns `{stats: {player_id: {...}}, hand_count}` but
the browser player can never see it. Add a **Stats** button next to the
history toggle → overlay modal, one row per player (names joined client-side
from `S.view.players`): hands played, hands won, win %, net
(`chips - total_invested`), best hand name, rebuys. Sort by net descending.
Close via ✕ / Escape / backdrop click. Session stats only (persistent stats
stay TUI-only).

### V2. Hand-end summary

The `hand_ended` caption is a flat "Hand over". Make the between-hands moment
informative, purely client-side: accumulate `pot_awarded` amounts per player
during the pump; on `hand_ended` set the caption to
`You won +240` / `Bot 2 wins 340 — you lose 60` (your delta =
winnings − `invested_this_hand` from the pre-hand view is overkill; just show
winners and your winnings if any). Clear the accumulator on `hand_started`.

### V3. Pacing nits (from the §2 review)

- Only dwell when there is a caption: in `pump()`, skip the sleep when
  `eventText(ev)` returned null — kills the 400ms dead air on your own
  `hole_cards_dealt`.
- Clear `#caption` and the `.acting` highlight on `hand_started` so stale
  lines never linger into the next hand.

### V4. Keyboard shortcuts (desktop QoL)

`keydown` on document, ignored when a modal is open or focus is in an input:
`f` fold, `c` check/call, `r` open raise panel, `a` all-in (still confirms),
`n` next hand, Enter confirms an open raise panel, Escape closes it. Only act
when the corresponding button is currently rendered+enabled — drive the
shortcuts by clicking the buttons (`btn.click()`), never by calling
`sendAction` directly, so gating stays in one place.

### V5. "Your turn" attention cue

When the action bar renders with `to_act`: pulse the bar (CSS animation) and
set `document.title = "● Your turn — Poker Terminal"`, restoring it otherwise.
Helps when the tab was backgrounded during bot play (auto-skip already
fast-forwards the queue).

### Acceptance criteria (Tier 2)

- [ ] Stats modal matches `GET /stats` numbers after 10+ hands with a rebuy.
- [ ] Hand end shows who won what; your wins clearly marked; resets next hand.
- [ ] No dead-air pauses at hand start; no stale caption after a new hand deals.
- [ ] All shortcuts work; typing in the raise number input never triggers them.

---

## Tier 3 — Gameplay features (server + client session; the only one touching Python)

All four are small additions to `core/views.py::build_view` + settings/session
plumbing + client rendering. Engine rules (`core/game.py` etc.) unchanged.
Run `python -m pytest tests/ -q` after each; extend `tests/test_views.py` /
`test_api.py` accordingly.

### G1. Cash-game mode option

Engine already supports `game_mode='cash'` (no blind escalation) — the TUI
benchmarks use it; `api/sessions.py:52` hardcodes `"tournament"`. Add a
`game_mode` radio (Tournament / Cash) to the settings form, pass it through
`CreateGameRequest` (validate: one of the two values) into the `Game(...)`
constructor. In cash mode, hide the "Level" from the header (client checks
`view.game_mode`). Test: 409-free hand flow + blinds unchanged after
`hands_per_level` hands.

### G2. Show your current hand strength

Under your hole cards, once the flop is out: "Two Pair — Kings and Fives".
Server-side (client can't evaluate): in `build_view`, when the viewer is
active and `len(game.community_cards) >= 3`, evaluate via
`HandEvaluator.evaluate(viewer.hole_cards, community, short_deck=...)` and add
`you.hand_name = HandRank.to_string(score[0], short_deck=...)`; else
`you.hand_name = None`. Import inside the function or at module top — views.py
is engine-pure, evaluator is fine. Cost is one 7-choose-5 evaluation per view
build for interactive games only — negligible. Tests: present on flop views,
None preflop, absent for spectators; leak test still green.

### G3. Bot style tags on seats

TUI parity: seats show `[TightAggressive, 0.6]` for bots (`main.py` turn-order
block does this via `strategy.profile`). Add to each player dict in
`build_view`: `"style": profile.name if bot has DesignedBotStrategy else null`
(pattern: `getattr(getattr(p, 'strategy', None), 'profile', None)`). Client
renders it as a small dim tag under the bot's name (both display modes).
Deliberate call: show it live (the TUI already does; this is single-player
practice, knowing the archetype is a feature).

### G4. Blind-level countdown

Header shows "Level 2" but not when it ends. Add to `build_view`'s blinds
dict: `"hands_to_level": game.hands_per_level - (game.hand_count % game.hands_per_level)`
when `game_mode == 'tournament'` else null. Client: "Level 2 · next in 3
hands". (Server-side because the client forgets `hands_per_level` after a
reconnect.)

### Acceptance criteria (Tier 3)

- [ ] Cash game: 20+ hands, blinds never escalate, header shows no level.
- [ ] Hand strength label correct through flop→turn→river (spot-check vs
      showdown result), absent preflop, never shown for opponents.
- [ ] Bot style tags visible in both display modes; humans have none.
- [ ] Countdown decrements each hand and resets on level-up;
      absent in cash mode. All existing tests still green.

---

## Deliberately NOT proposed (assessed and rejected for now)

- **WS keepalive/heartbeat** — uvicorn's websockets stack auto-pings (20s
  default); Tier 1 reconnect covers the residual risk. Revisit only if drops
  are observed in practice.
- **Multi-human tables, auth** — engine supports multiple AgentPlayers, but
  seat management/auth is a project-sized feature, not an increment.
- **Persistent stats in the browser** (`stats_persistent.py`) — cross-session
  identity for a browser player is ill-defined until there are accounts.
- **Chip/card movement animations, sounds** — §9 guardrail of the browser plan
  stands: captions carry the information; physics adds bug surface, not clarity.
- **PWA/installable app** — nice-to-have someday; requires a manifest +
  service worker and interacts badly with reconnect until Tier 1 is proven.
- **Server-side session persistence across restarts** — dev-tool scope creep
  for a single-player local game.

## Suggested sessions & kickoff prompts

One tier per fresh session, in order (1 → 2 → 3). Each tier = one commit
(`web: reconnect + session restore`, `web: stats modal + polish + shortcuts`,
`api+web: cash mode, hand strength, bot tags, blind countdown`).

> **Session 1:** Read `notes/web_client_improvements_v12.md` fully. Implement
> Tier 1 only (R1–R3), meeting the R4 criteria. Touch only `web/`. Do not
> start Tier 2 or 3.

> **Session 2:** Read `notes/web_client_improvements_v12.md` fully. Tier 1 is
> done. Implement Tier 2 only (V1–V5), meeting its criteria. Touch only `web/`.

> **Session 3:** Read `notes/web_client_improvements_v12.md` fully. Tiers 1–2
> are done. Implement Tier 3 (G1–G4), meeting its criteria. You may touch
> `core/views.py`, `api/schemas.py`, `api/sessions.py`, `tests/`, and `web/` —
> nothing else in `core/`. All 265+ tests must pass; add the new tests listed.
