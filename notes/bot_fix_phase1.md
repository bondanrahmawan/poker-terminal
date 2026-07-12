# Bot AI Fix — Phase 1: Repair the wiring

Implementation spec. Companion to `notes/bot_ai_assessment.md` (bug IDs B1–B12
referenced below come from its Section 5), but this document is self-contained —
you do not need to read the assessment to implement this.

## Context

The bots in this repo are `BotPlayer` (`players/bot.py`) driven by
`DesignedBotStrategy` (`strategies/engine.py`). The strategy has opponent
modeling, table image, tilt, draw detection, and position-aware preflop
ranges — but several of these layers receive wrong or empty inputs at runtime.
This phase fixes the plumbing only. **No new features, no strategy redesign,
no tuning.** After this phase the already-written adaptive layers simply work.

## Ground rules

- Surgical changes only; match existing code style. Do not refactor or
  "improve" adjacent code.
- Work task by task, in order. After each task run the focused tests for that
  task, then the full suite: `python -m pytest tests/ -q`.
- Some existing tests encode the buggy behavior being fixed (especially draw
  detection). Update those tests to the corrected definitions — each such
  change must be justified by this spec, not convenience.
- Final verification (Task 10) must pass before you're done.

---

## Task 1 — Give the strategy its own identity (fixes B1)

**Problem:** `DesignedBotStrategy.decide()` guesses its own name as
`players_info[0][0]` (`strategies/engine.py:92-93`) — that's just whoever sits
in seat 0. `_extract_opponent_ids(players_info, '')` is called with an empty
string (`engine.py:164` and `:268`), so the bot's own name ends up in its
opponent list and it models/exploits itself. `self._bot_name` is read via
`getattr` at `engine.py:136` but never assigned anywhere.

**Change:**

1. In `core/game.py:_build_game_state` (around line 518), add two keys:
   `'self_id': p.player_id` and `'self_name': p.name`.
2. In `strategies/engine.py:decide()`, read `self_name = game_state.get('self_name', '')`
   and store it as `self._bot_name` (so `_record_opponent_actions` sees it).
3. Replace both `_extract_opponent_ids(players_info, '')` calls with
   `_extract_opponent_ids(players_info, self._bot_name)`.
4. Delete the seat-0 `bot_name` guess in `decide()`.
5. Update the `BotStrategy` docstring in `strategies/__init__.py` to list the
   new game_state keys.

**Verify:** new unit test — build a game_state dict with 3 players where the
bot is seat 1; assert the bot's own name is not in the ids passed to the
tracker (easiest: after several `decide()` calls, assert
`strategy.tracker.get_stats(<own name>).total_hands_seen == 0` while
opponents have data). Also assert `exploit_adjustment` is computed over 2
opponents, not 3.

---

## Task 2 — Consume structured events instead of parsing log strings (fixes B2, B3, B10)

**Problem:** `_record_opponent_actions` (`strategies/engine.py:124-146`)
parses the human-readable text log. Three consequences:

- It re-reads `hand_log[-20:]` on **every** `decide()` call with no cursor —
  the same actions get counted many times (`Game.logs` is never cleared).
- Every action is recorded with hard-coded `street='preflop'`, so
  `OpponentStats.fold_to_bet` is never populated → `opp_folds_often` is
  always False → the bluff-exploit and fold-equity paths never activate.
- Non-action log lines that happen to start with a player name (e.g. the
  showdown summary `"Bob folded on flop"`) are miscounted as actions, and
  player names containing spaces break parsing entirely.

The engine already emits exactly what's needed: `action_taken` events
(`core/game.py:480-482` and `:499-502`) carrying `player_id`, `name`,
`action` ('fold'/'check'/'call'/'raise'/'all_in'), `amount`, `all_in`.
Events have a monotonically increasing `seq` (`core/events.py`) that is NOT
reset when the event list is cleared per hand in simulation mode
(`game.py:244-245`), so a seq-based cursor is safe in both live and
simulation modes. Events are already passed to bots as `game_state['events']`
(`game.py:527`).

**Change:**

1. In `core/game.py`, add `street=self.current_street` to both
   `emit('action_taken', ...)` calls in `_apply_action`. Confirm
   `self.current_street` holds `'preflop'` during preflop (it is set for
   flop/turn/river in `_deal_community`; if preflop isn't set at hand start,
   set it where the PREFLOP street begins in `run_cycle`/`_start_new_hand`).
2. In `DesignedBotStrategy.__init__`, add `self._event_cursor = -1`.
3. Rewrite `_record_opponent_actions(self, game_state)` to:
   - iterate `game_state.get('events', [])`, skipping events with
     `seq <= self._event_cursor`; update `self._event_cursor` to the last
     seen seq;
   - for each `action_taken` event where `data['name'] != self._bot_name`
     (also skip if it equals `self._bot_name`'s id — compare against
     `data['player_id']` vs `game_state['self_id']` for robustness), call
     `self.tracker.record_action(data['name'], action, street)` where
     `action` maps `'all_in'` → `'raise'` if `amount > 0` was a raise —
     keep it simple: pass the event's action string through, mapping
     `'all_in'` to `'raise'` (matches the tracker's existing handling), and
     `street` comes from the event.
   - Distinguishing a postflop **call of a bet** vs a **check**: the events
     carry `'check'` and `'call'` separately already; the tracker's existing
     `record_action` semantics are unchanged.
4. Delete the old string-parsing body. Keep the method name and call sites.
5. `hand_log` stays in game_state (the web client and tests may use it) —
   just stop reading it in the strategy.

**Note on `record_missed_opportunity` (B10):** with real streets recorded,
preflop folds now increment VPIP denominators via the existing
`record_action(..., 'fold', 'preflop')` path — that is sufficient; do not
wire `record_missed_opportunity` anywhere.

**Verify:** new unit test — feed a fixed list of `GameEvent`s (one preflop
fold, one flop fold, one flop call by an opponent; plus actions by the bot
itself) through two consecutive `decide()` calls (same events list). Assert:
- each opponent action counted exactly once (cursor works);
- the flop fold incremented `bets_faced` and `folds_to_bet` (street respected);
- the bot's own actions recorded nowhere.
Also an integration test: run ~30 hands of a 3-bot game and assert some
opponent has `fold_to_bet > 0` in some bot's tracker (currently impossible).

---

## Task 3 — Route unopened pots through opening logic, and use the real position label (fixes B4, B8)

**Problem:** in `_decide_preflop` (`strategies/engine.py:150-247`) the test
`min_call == 0` is used to mean "I can open". Preflop, everyone except the
big blind owes at least the blind, so `min_call > 0` and the whole opening
block (position-aware ranges, open-raise sizing, desperation shove, premium
handling, late-position limp) is reachable **only by the BB checking its
option**. Every actual opening situation falls into the "facing a raise"
branch, so bots "open" via 3-bet logic and `position_to_range(...,
is_opening=False)` collapses every seat to the `'medium'` range.
Separately (B8), the engine recomputes its position label via
`_position_label()` from an index over all seats (including busted players)
mixed with an active-seat count — wrong once anyone busts — while the game
already passes a correct `player_role` string ('BTN', 'SB', 'BB', 'UTG',
'MP', 'CO', built in `game.py:_position_label`).

**Change:**

1. In `core/game.py:_build_game_state`, add `'big_blind': self.big_blind`
   and `'current_bet'`: the highest total street bet so far — use the
   `BetManager`'s existing notion (e.g. `self.bet_manager.current_bet` if the
   attribute exists; otherwise derive as
   `max(0, self.bet_manager.get_amount_to_call(p.player_id)) + <p's street investment>`
   — inspect `core/betting.py` and use whatever it already tracks; do not
   add new state to BetManager unless nothing exists).
2. In `DesignedBotStrategy.decide()`, set
   `self._position = game_state.get('player_role') or self._position_label(position_idx, num_active)`
   (keep `_position_label` only as fallback for tests that don't pass
   `player_role`). Map the game's `'BTN/SB'` heads-up label to `'BTN'`.
3. In `_decide_preflop`, compute
   `unopened = current_bet <= big_blind` (no voluntary raise yet).
   Restructure:
   - `is_opening = unopened` → use it for `position_to_range(self._position,
     is_opening=unopened)`.
   - If `min_call > 0 and unopened`: this is an **open/limp decision**, not a
     3-bet spot. Route it through the existing "Opening" block (the code
     currently under `min_call == 0`), with one change: where that block
     returns `CHECK` for weak hands, return `FOLD` instead when
     `min_call > 0` (you can't check facing the blind), and the "limp"
     branch calls `min_call` as before.
   - If `min_call > 0 and not unopened`: keep the existing facing-a-raise
     logic (3-bet / BB defend / call / fold) unchanged.
   - If `min_call == 0`: keep the existing BB-option behavior (check instead
     of fold with weak hands) — this is now the only situation that branch
     serves, which is correct.
4. Do not touch the range tables in `strategies/preflop_ranges.py`.

**Verify:** new unit test — simulate 2,000 preflop `decide()` calls per
position for a `BalancedStrategy` at difficulty 1.0 (no noise) with a fresh
strategy each call (avoid tracker drift), using an unopened game_state
(`current_bet == big_blind`, `min_call = big_blind`). Assert entry rate
(non-fold frequency) for `player_role='BTN'` is at least 1.5× the rate for
`'UTG'`. Currently both would be identical — this test is the proof the
ranges came alive.

---

## Task 4 — Record preflop folds into TableImage (fixes B5)

**Problem:** `TableImage.record_preflop_fold()` (`strategies/dynamic_behavior.py:111`)
is never called; only `record_preflop_enter`/`record_raise` are. `tightness`
is therefore permanently 0 ("very loose") and every image-based computation
is a constant.

**Change:** in `_decide_preflop`, at every `return PlayerAction.FOLD, 0`
path, call `self.image.record_preflop_fold()` first. (Only preflop folds —
postflop folds don't touch preflop image.)

**Verify:** unit test — a `NitStrategy` (difficulty 1.0) fed 50 junk-hand
preflop decisions has `image.tightness > 0.7`.

---

## Task 5 — Fix gutshot / double-gutshot detection (fixes B7)

**Problem:** `_has_gutshot` (`strategies/draw_detection.py:150-161`) requires
4 distinct ranks with `window[3] - window[0] == 5`, which is a two-gap
non-draw. A real gutshot is 4 ranks spanning exactly **4** with one missing
internal rank (e.g. 5-6-7-9 needs the 8). `_has_double_gutshot`
(`:164-175`) inherits the same span error. Consequences: real gutshots get 0
outs, junk gets 4–8 outs, and semi-bluff/equity numbers are wrong whenever a
straight draw is involved.

**Change:**

1. `_has_gutshot`: 4 distinct ranks where `window[3] - window[0] == 4`
   (one internal rank missing), at least one hole card in the window, and it
   is not already an open-ended draw. Also handle the ace-low wheel case:
   treat an ace as rank 1 as well as 14 when scanning (A-2-3-5 needs the 4).
   If wheel handling isn't already present for open-enders, add it for
   gutshots only — do not expand scope.
2. `_has_double_gutshot`: two *distinct* missing ranks, each of which would
   complete a straight (i.e., two different gutshot windows with different
   missing ranks). Rewrite using the corrected window definition.
3. Update the existing draw-detection tests in
   `tests/test_enhanced_strategies.py` that assert the old (wrong) spans, and
   add table-driven cases:
   - hole 8♠9♦, board 5♥6♣K♦ → ranks 5,6,8,9 (span 4, missing 7) →
     gutshot **True**
   - hole 5♠6♦, board 8♥10♣K♦ → ranks 5,6,8,10 (span 5, two gaps — the old
     code wrongly flags this) → gutshot **False**
   - hole A♠2♦, board 3♥5♣K♦ → wheel gutshot (needs the 4) → **True**
   - hole 9♠10♦, board 6♥7♣K♦ → ranks 6,7,9,10 (missing 8) → gutshot **True**
   - hole J♠10♦, board 9♥8♣K♦ → 8-9-10-J → `open_ended_straight_draw`
     **True**, gutshot **False**
   - hole 10♠9♦, board 6♥8♣Q♦ → ranks 6,8,9,10,Q: the 7 completes
     6-7-8-9-10 and the J completes 8-9-10-J-Q — two distinct straight-
     completing ranks → `double_gutshot` **True**, `straight_draw_outs == 8`

**Verify:** the table-driven tests above pass; full suite passes.

---

## Task 6 — Real `was_favorite` for tilt (fixes B6)

**Problem:** `core/game.py:699-700` passes `was_fav = won` (marked TODO), so
`TiltState.record_loss(..., was_favorite=True)` — the bad-beat trigger — can
never fire. Tilt is effectively inert.

**Change:** in `_handle_showdown` (or where `_last_hand_result` is built),
for hands that reach a **contested showdown**, determine who was ahead
before the river: evaluate each showdown participant's hand with
`HandEvaluator.evaluate(hole, community[:4])` (flop+turn only) and record the
leader. Store it (e.g. `self._preriver_leader: Optional[str]`) and in the
hand-end loop (`game.py:693-701`) pass
`was_favorite = (p.player_id == self._preriver_leader)`.
For hands decided by folds (no showdown), keep `was_favorite=False`.
Reset the field at hand start.

This is deliberately cheap (one extra evaluation per showdown player, no
Monte Carlo) and captures the classic "rivered" bad beat, which is what tilt
is meant to model.

**Verify:** unit test with a seeded/stacked deck (see how existing tests
force decks, e.g. via `seed`) or directly: construct the situation by calling
the new helper on fixed cards — leader on turn who loses at river yields
`was_favorite=True` in `record_hand_result`; assert the losing bot's
`tilt_level` rose by the bad-beat increment (0.15), not the normal 0.05.

---

## Task 7 — Stop adding fold equity to call decisions (fixes B12)

**Problem:** `engine.py:283` does `equity += fold_equity` unconditionally.
Fold equity (opponents folding to *your* bet) only exists when you bet or
raise; adding it before the pot-odds **call** comparison systematically
over-calls.

**Change:** in `_decide_postflop`, keep two numbers: `equity` (raw noisy
equity + `exploit['equity_boost']`, clamped) used for call/fold decisions and
made-hand thresholds, and `bet_equity = min(1.0, equity + fold_equity)` used
only inside the bluff / semi-bluff / value-bet / raise branches (i.e., pass
`bet_equity` to `should_semi_bluff`, `choose_bet_size`, `choose_raise_size`,
and the `is_strong_made`/`is_made_hand` *bet-decision* checks may stay on
`equity` — only the aggression paths get the bonus).

**Verify:** unit test — with a tracker reporting high opponent fold rates,
a facing-a-bet call decision with `equity` just below pot odds still folds
(fold equity must not rescue a bad call), while the same state with
`min_call == 0` still produces bets at least as often as before.

---

## Task 8 — Single return type for bet-sizing helpers (fixes B9)

**Problem:** `choose_bet_size` (`strategies/betsizing.py:74-169`) usually
returns `(BetSize, int)` but two branches return `(PlayerAction, int)`
(slow-play: `:104-112`, no-hand default: `:163-169`). The caller in
`engine.py` checks `isinstance(amt, int)`, which is true for *both* shapes —
if a `(PlayerAction.CALL, amount)` tuple ever came back it would be fed into
`_action_raise_or_all_in` as a raise. Currently latent (`is_slow_play` is
never passed), but it's a trap.

**Change:**

1. In `choose_bet_size`, delete the `is_slow_play` parameter and its branch
   (the engine handles slow-play before ever calling this), and change the
   final default branch to `return None` (meaning "no bet — caller decides
   check/fold").
2. Mirror in `choose_raise_size` (drop `is_slow_play` pass-through).
3. In `engine.py`, replace every `isinstance(amt, int)` dance with:
   `result = choose_bet_size(...)`; `if result is not None: size, amt = result;
   ...raise/all-in...` else fall through to the existing check/fold logic.
   (Four call sites: semi-bluff raise, value raise, bluff bet, semi-bluff
   bet, value bet — five, adjust all.)
4. Update `tests/test_enhanced_strategies.py` tests touching these helpers.

**Verify:** grep confirms no `isinstance(amt` remains in `engine.py`; suite
passes; a direct call `choose_bet_size(pot_size=100, min_call=0, ...)` with
no hand flags returns `None`.

---

## Task 9 — Update the memory-of-record docs

Append a short "Phase 1 implemented <date>" note to
`notes/bot_ai_assessment.md` under Section 8 / Phase 1 listing anything that
deviated from this spec. Do not rewrite the assessment.

---

## Task 10 — Final verification gate

1. `python -m pytest tests/ -q` — all green.
2. Benchmark smoke: run a small all-vs-all via the existing harness, e.g.
   ```python
   from core.benchmark import run_all_vs_all
   r = run_all_vs_all(num_tables=16, hands_per_table=100, starting_chips=1000,
                      big_blind=20, difficulty=0.6)
   ```
   Assert it completes without exceptions and print the per-archetype nets.
   Expected sanity (not hard assertions): TightAggressive near the top,
   Maniac highest variance. If Maniac suddenly dominates everything or any
   archetype never wins a hand, something regressed — investigate before
   finishing.
3. Launch the web game (`python run_web.py`), play 2–3 hands against 3 bots,
   confirm bots act without errors and the game completes hands normally.

## Out of scope (do NOT do these)

- Difficulty redesign (Phase 2), per-street style parameters (Phase 3),
  equity upgrades / `equity_vs_range` (Phase 4), any new archetype.
- Deleting `strategies/archetypes.py`, `adjust_for_desperation`,
  `stats_tracker_before.py`, or any other dead code.
- Tuning any profile constant in `strategies/profile.py`.
- Touching the web client (`web/`).
