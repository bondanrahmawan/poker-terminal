# GUI API Implementation Plan — Decoupling the Engine from the TUI

**Status:** Implemented (Phases 1–4). See `core/events.py`, `core/action_request.py`,
`core/errors.py`, `core/views.py`, `players/agent.py`, and `api/`, with tests in
`tests/test_events.py`, `tests/test_resumable_engine.py`, `tests/test_views.py`,
`tests/test_api.py`.
**Audience:** An implementer starting with a fresh context window. This document is
self-contained: it describes the current architecture, the exact problems, the target
design, and a phase-by-phase implementation guide with acceptance criteria. Read the
whole document before writing any code.

---

## 0. Goal

Today the game is playable only through a terminal (`main.py` + `players/terminal.py`).
The goal is to expose the poker engine through a **UI-agnostic API** so a GUI (web or
desktop) can drive it, while keeping the existing TUI and all simulation/benchmark
modes working unchanged.

The work is split into 4 phases. Phases 1–3 are pure engine refactors with no new
dependencies. Phase 4 adds an HTTP/WebSocket transport (FastAPI) — only needed for a
web GUI; a desktop GUI can call the Phase 2 API in-process.

**Ground rules (from CLAUDE.md, apply throughout):**
- Touch only what each phase requires. Do not refactor adjacent code.
- After every phase, ALL existing tests in `tests/` must pass and the TUI
  (`python main.py`) must behave identically.
- No new dependencies until Phase 4 (the project is pure stdlib today; there is no
  `requirements.txt`).
- Windows note: run with `PYTHONIOENCODING=utf-8` for suit symbols.

---

## 1. Current Architecture (as of this writing)

```
main.py                  # TUI entry point: settings prompts, session loop, benchmarks, stats printing
core/
  game.py                # Game — the engine state machine (THE file most phases touch)
  state.py               # GameState(Enum): WAITING, DEAL, PREFLOP, FLOP, TURN, RIVER, SHOWDOWN, END
  player.py              # Player base class + PlayerAction(Enum): FOLD/CALL/RAISE/CHECK/ALL_IN
  card.py                # Card, Suit, Rank (plain classes, NOT enums)
  deck.py                # Deck (uses global `random`, not seedable)
  betting.py             # BetManager (per-round bets, min-raise) + PotManager (contributions, side pots)
  showdown.py            # ShowdownHandler (evaluate + distribute) + ShowdownResult
  evaluator.py           # HandEvaluator — best 5 of 7, short-deck aware
  blind_scheduler.py     # BlindScheduler — escalation levels, antes
  stats_tracker.py       # StatsTracker — per-player session stats, prints tables
  stats_persistent.py    # PersistentStatsManager — cross-session persistence
  simulation_stats.py    # SimulationStatsManager — benchmark result persistence
players/
  terminal.py            # TerminalPlayer — human via input()/print()  [TUI-only]
  bot.py                 # BotPlayer — synchronous, delegates to a strategy
  roster.py              # create_bots() factory, MAX_BOTS
strategies/              # Bot AI. DO NOT TOUCH in any phase.
tests/                   # pytest suite. Must stay green.
```

### 1.1 How a hand runs today (the blocking loop)

`Game.start_game()` (core/game.py) sets `state = GameState.DEAL` and calls
`run_cycle()`, which loops over the state machine **until the hand is fully over**:

```
DEAL → PREFLOP(bet) → FLOP(deal+bet) → TURN(deal+bet) → RIVER(deal+bet) → SHOWDOWN → END → WAITING
```

Each betting street calls `Game._handle_betting_round()`, which loops over players and
calls `p.get_action(game_state_data)` **synchronously**. For bots this returns
immediately. For `TerminalPlayer` it blocks on `input()`. This is the single biggest
obstacle to a GUI: **control never returns to the caller mid-hand.**

Key mechanics inside `_handle_betting_round()` you must preserve exactly
(core/game.py, ~lines 255–377):

1. **Blind posting** happens at the top of the PREFLOP branch (antes first if enabled,
   then SB, then BB), routed through `player.lose_chips()`, `pot_manager.add_contribution()`,
   `bet_manager.process_bet()`, and `street_investments` tracking.
2. **Turn order:** heads-up preflop the dealer/SB acts first; heads-up postflop the BB
   acts first. Full ring preflop UTG (dealer+3) acts first; postflop first active seat
   after the dealer acts first.
3. **`players_to_act`** is a list of players who still owe a decision. A **raise
   (or all-in that exceeds the amount-to-call) re-opens betting**: it resets
   `players_to_act = [everyone who can_act() except the raiser]`. A call/check/fold
   just removes the actor from the list.
4. Players who went all-in are removed from `players_to_act` lazily when the loop
   reaches them (`can_act()` returns False).
5. `iterations_without_progress` / `max_iterations` is an infinite-loop safety net.
6. The round ends early if only one player remains active.
7. `lose_chips(amount)` clamps to the player's stack and sets `is_all_in`; the engine
   always uses the returned actual amount.

### 1.2 The `game_state` dict passed to `get_action()`

Built fresh per action in `_handle_betting_round()`:

```python
{
    'min_call':        bet_manager.get_amount_to_call(p.player_id),  # int
    'min_raise':       bet_manager.min_raise,                        # int (increment, not total)
    'pot_size':        pot_manager.total_pot(),                      # int
    'community_cards': self.community_cards,                         # List[Card]
    'players_info':    [(name, chips, is_active), ...],              # opponents' hole cards NOT included (good)
    'position':        (seat_idx - dealer_idx) % n,                  # int
    'player_role':     'SB'|'BB'|'BTN'|'CO'|'HJ'|'UTG'|'MP'|'BTN/SB',
    'num_active':      int,
    'hand_log':        list(self.logs),   # FULL COPY of every log line so far — O(n²) over a session
}
```

Bots (`players/bot.py`) consume `min_call`, `min_raise`, `pot_size`,
`community_cards`, `players_info`, `player_role`, `num_active` via their strategy.
**Bots never read `hand_log`.** Only `TerminalPlayer` reads `hand_log` — it re-parses
the formatted strings with keyword matching to show "what happened since your last
turn". This string re-parsing is exactly what Phase 1's structured events replace.

### 1.3 Output today

`Game.log(msg)` appends to `self.logs` (list of strings) and `print()`s if
`live_output=True`. All output is pre-formatted, column-aligned, sometimes
ANSI-colored terminal text. There is no structured record of what happened.

### 1.4 Action semantics (IMPORTANT — amounts are deltas, not totals)

`get_action()` returns `(PlayerAction, amount)` where **`amount` is the number of
chips pushed in right now** (a delta), not the player's total bet this round.
- CHECK → `(CHECK, 0)`
- CALL → `(CALL, min_call)` clamped to stack
- RAISE → `(RAISE, amt)` where `amt >= min_call + min_raise` (i.e., call portion +
  raise increment) and `amt <= chips`
- ALL_IN → `(ALL_IN, chips)`
- FOLD → `(FOLD, 0)`

The engine decides whether a RAISE/ALL_IN actually re-opens betting by checking
`actual_deducted > bet_manager.get_amount_to_call(p.player_id)`.

### 1.5 Callers of the engine (all must keep working)

- **TUI tournament** (`main.py::_run_session`): calls `g.start_game()` once per hand
  in a while-loop; handles human rebuy between hands.
- **Benchmarks** (`main.py::_run_strategy_benchmark`, `_run_h2h_benchmark`,
  `_run_parameter_sweep`): create bot-only `Game(live_output=False)` instances and
  call `g.start_game()` tens of thousands of times. **Performance matters here** —
  do not add per-action overhead that is more than trivially cheap, and do not copy
  the full log per action for bot-only games (see Phase 1 note on fixing the existing
  O(n²) `hand_log` copy).
- **Tests** (`tests/test_game.py`, `tests/test_automated_play.py`, etc.).

### 1.6 Other current facts you will need

- `Card` has `rank: int (2–14)`, `suit: str ('Spades'|'Hearts'|'Diamonds'|'Clubs')`,
  `__repr__` like `"A♠"`, `__eq__`/`__hash__`/`__lt__`. No `to_dict()`.
- `Deck.reset()` rebuilds and shuffles using the **global** `random` module — not
  seedable per game.
- `Pot` has `amount: int`, `eligible_players: set[str]`. `PotManager.contributions`
  maps player_id → total contributed this hand.
- `ShowdownResult` has `winners: List[str]`, `winnings: Dict[str, int]`,
  `hand_scores: Dict[str, tuple]`.
- `Game.stats` property proxies `stats_tracker.stats` (dict per player_id with
  `hands_played`, `hands_won`, `total_invested`, `rebuys`, `best_hand_rank`,
  `best_hand_name`, …).
- Blind escalation happens in `_handle_end()` (tournament mode only); a level-up
  message is stashed in `game.pending_msg` and logged at the start of the next hand.
- Dealer rotation in `_handle_end()` skips busted players.
- `TerminalPlayer.get_action` is annotated `-> Tuple[str, int]` but actually returns
  `Tuple[PlayerAction, int]` — fix the annotation when you touch that file, nothing else.

---

## 2. Target Architecture

```
                    ┌────────────────────────────────────────────┐
                    │                 Clients                    │
                    │  TUI driver   web GUI    desktop GUI       │
                    └──────┬───────────┬────────────┬────────────┘
                           │      (Phase 4: FastAPI + WebSocket)  │
                           │           │            │ (in-process)
                    ┌──────▼───────────▼────────────▼────────────┐
                    │       Engine API (Phase 2 + 3)             │
                    │  game.advance() -> ActionRequest | None    │
                    │  game.submit_action(pid, action, amount)   │
                    │  game.view_for(player_id) -> dict          │
                    │  game.events -> List[GameEvent] (Phase 1)  │
                    └──────────────────┬─────────────────────────┘
                    ┌──────────────────▼─────────────────────────┐
                    │  Existing engine internals (unchanged      │
                    │  semantics): BetManager, PotManager,       │
                    │  ShowdownHandler, BlindScheduler,          │
                    │  StatsTracker, strategies/                 │
                    └────────────────────────────────────────────┘
```

Core ideas:

1. **Events, not strings** (Phase 1): every meaningful moment emits a typed
   `GameEvent`. String logs are derived *from* events, not the other way round.
2. **Inversion of control** (Phase 2): the engine pauses when an *interactive*
   player must act, returning an `ActionRequest`. Bots keep being called
   synchronously inside the engine — zero changes to `strategies/`.
3. **Per-viewer snapshots** (Phase 3): `view_for(player_id)` returns a JSON-safe
   dict with hidden information filtered (only your own hole cards, opponents'
   revealed only at showdown via events).
4. **Transport is a thin shell** (Phase 4): session registry + REST + WebSocket
   around the Phase 2/3 API.

---

## 3. Phase 1 — Structured Event Stream

**Goal:** `Game` emits typed events alongside its existing string logs. TUI output
must remain byte-identical. This phase is low-risk and independently shippable.

### 3.1 New file: `core/events.py`

```python
"""Structured game events. The single source of truth for 'what happened'."""
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class GameEvent:
    seq: int                    # monotonically increasing per Game instance, from 0
    type: str                   # one of the EVENT TYPES below
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"seq": self.seq, "type": self.type, "data": self.data}
```

Keep it this simple. Do **not** create one dataclass per event type — a `type` string
plus a data dict is easier to serialize in Phase 4 and easier to extend.

### 3.2 Event types and payloads (the contract)

All card values in event payloads are **display strings** (e.g. `"A♠"`) in Phase 1;
Phase 3 upgrades them to card dicts. Amounts are ints. `pot` is the total pot after
the event applied.

| type              | data                                                                                   | emitted from                    |
|-------------------|----------------------------------------------------------------------------------------|---------------------------------|
| `hand_started`    | `hand_number, small_blind, big_blind, ante, level, game_mode, dealer_player_id`        | `_handle_deal`                  |
| `seating`         | `order: [{player_id, name, role, chips, is_human}]` in SB-first order                   | `_handle_deal`                  |
| `hole_cards_dealt`| `player_id, cards` (emit one event per active player)                                   | `_handle_deal`                  |
| `blind_posted`    | `player_id, kind: "ante"\|"small"\|"big", amount, pot`                                  | `_handle_betting_round` preflop |
| `street_started`  | `street: "preflop"\|"flop"\|"turn"\|"river", cards_dealt: [..], community: [..]`        | `_handle_betting_round` / `_deal_community` |
| `action_taken`    | `player_id, action: "fold"\|"check"\|"call"\|"raise"\|"all-in", amount, pot, all_in: bool` | `_handle_betting_round`      |
| `showdown_started`| `community: [..]`                                                                       | `_handle_showdown`              |
| `hole_cards_shown`| `player_id, cards, hand_name, best_five: str`                                           | `_handle_showdown`              |
| `pot_awarded`     | `player_id, amount, pot_index, pot_label: "Main Pot"\|"Side Pot N"`                     | `_handle_showdown`              |
| `hand_ended`      | `hand_number, chip_counts: {player_id: chips}, busted: [player_id]`                     | `_handle_end`                   |
| `blinds_raised`   | `small_blind, big_blind, ante, level`                                                    | `_handle_end`                   |

Notes:
- `hole_cards_dealt` is **private information**. Phase 1 just stores it in the event
  list (single-process TUI, no leak). Phase 3/4 must filter it per viewer — see §5.3.
- For `pot_awarded`, today `_handle_showdown` logs aggregate winnings from
  `ShowdownResult.winnings`. Emit one event per (winner, aggregate amount) with
  `pot_index=-1, pot_label="total"` if per-pot attribution is awkward; per-pot
  attribution is nice-to-have, not required.

### 3.3 Changes to `core/game.py`

1. `__init__`: add `self.events: List[GameEvent] = []` and `self._event_seq = 0`.
2. Add method:
   ```python
   def emit(self, type_: str, **data) -> None:
       self.events.append(GameEvent(self._event_seq, type_, data))
       self._event_seq += 1
   ```
3. At each location listed in the table above, add an `emit(...)` call **next to**
   the existing `self.log(...)` call. Do not remove or alter any `log()` call —
   TUI output must not change.
4. **Fix the O(n²) log copy while you are here** (this is the one permitted cleanup,
   it directly serves the phase): in `_handle_betting_round`, `game_state_data`
   contains `'hand_log': list(self.logs)`. Only `TerminalPlayer` uses it. Replace
   with a lazy reference: `'hand_log': self.logs` (no copy). `TerminalPlayer` only
   reads/slices it, never mutates, so passing the live list is safe. Verify with a
   quick benchmark run (`main.py` → mode 2 → small run) that nothing broke.
5. Memory guard: in `_handle_deal`, if `not self.live_output` (simulation mode),
   clear `self.events` at the start of each hand the same way you'd want logs
   bounded. (Today `self.logs` grows unboundedly in simulations too — leave that
   as-is, just don't make it worse: keep events bounded in sim mode.)

### 3.4 Changes to `players/terminal.py`

Replace `_show_recent_actions`'s keyword parsing of `hand_log` with consumption of
`game.events`. To do that, add `'events': self.events` to `game_state_data` in
`_handle_betting_round` (live reference, same as hand_log). TerminalPlayer keeps a
`_last_event_seq` cursor and renders new events since then:

- `action_taken` → `"  {name} {action} {amount}    Pot: {pot}"`
- `street_started` → `"  --- {STREET} ---  {cards}"`
- `blind_posted`, `pot_awarded`, `hand_started` similar.

You need a player_id→name mapping; include `'player_names': {pid: name}` in
`game_state_data` or carry names inside the events (carry names inside events —
simpler for GUI clients too; add `name` to `action_taken`, `blind_posted`,
`pot_awarded`, `hole_cards_shown` payloads).

Reset the cursor on `hand_started`. Keep `(h)istory` working off `hand_log` — that
feature can keep using strings.

The rendered "recent actions" text does not need to be byte-identical to the old
keyword-filtered version (it was lossy anyway), but must show the same information:
opponent actions, street changes, showdown results since the player's last prompt.

### 3.5 Phase 1 acceptance criteria

- [ ] `pytest tests/` fully green, unchanged.
- [ ] New test file `tests/test_events.py`:
  - Play a scripted bot-only hand (fixed players, e.g. reuse patterns from
    `tests/test_automated_play.py`); assert the event sequence starts with
    `hand_started`, `seating`, N×`hole_cards_dealt`, `blind_posted`(SB), `blind_posted`(BB), …
  - Assert every `action_taken.pot` equals `pot_manager` state at that time
    (or simply: final pot equals sum of winnings).
  - Assert `seq` is strictly increasing and dense (0,1,2,…).
- [ ] Run a 5-table benchmark and confirm runtime is not slower than before the
  change (the hand_log fix should make it *faster*).
- [ ] Manual TUI smoke test: play 2–3 hands; engine log lines identical; the
  "recent actions" panel shows opponent actions correctly.

---

## 4. Phase 2 — Resumable Engine (`advance` / `submit_action`)

**Goal:** the engine can pause when an interactive player must act, and resume when
an action is submitted. Bot-only games keep running to completion synchronously with
identical results. This is the hardest phase — read §4.4 carefully.

### 4.1 New concepts

**`core/player.py`** — add one class attribute:

```python
class Player:
    interactive = False   # engine pauses for this player instead of calling get_action()
```

**New file `players/agent.py`:**

```python
"""AgentPlayer — a human seat driven externally via Game.advance()/submit_action()."""
from core.player import Player


class AgentPlayer(Player):
    interactive = True

    def get_action(self, game_state: dict):
        # Never called: the engine pauses for interactive players instead.
        raise RuntimeError("AgentPlayer actions must be supplied via Game.submit_action()")
```

`TerminalPlayer` and `BotPlayer` keep `interactive = False` — the TUI keeps working
through the old blocking path with zero behavior change. (Migrating the TUI onto the
driver loop is optional follow-up work, not part of this phase.)

**New file `core/action_request.py`:**

```python
from dataclasses import dataclass
from typing import List


@dataclass
class ActionRequest:
    player_id: str
    street: str                  # 'preflop'|'flop'|'turn'|'river'
    legal_actions: List[str]     # subset of ['fold','check','call','raise','all-in']
    min_call: int                # chips owed to call (already clamped ≥ 0, NOT clamped to stack)
    min_raise_total: int         # minimum total delta for a legal raise = min_call + bet_manager.min_raise, clamped to stack
    max_raise_total: int         # player's stack (no-limit)
    pot_size: int
    seq: int                     # event seq at time of request (client sync cursor)
```

Legal-actions rules:
- `check` iff `min_call == 0`; `call` iff `min_call > 0`.
- `raise` iff player's stack `> min_call` and stack `>= min_raise_total`
  (if the stack is bigger than a call but smaller than a legal min-raise, the only
  aggressive option is `all-in`, which is always legal while the player can act).
- `fold` and `all-in` are always legal.

### 4.2 Public API on `Game`

```python
def start_hand(self) -> Optional[ActionRequest]:
    """Begin a new hand and run it forward until either the hand completes
    (returns None) or an interactive player must act (returns ActionRequest)."""

def advance(self) -> Optional[ActionRequest]:
    """Resume processing. Returns the next ActionRequest, or None when the
    hand is complete (state is back to WAITING)."""

def submit_action(self, player_id: str, action: PlayerAction, amount: int = 0
                  ) -> Optional[ActionRequest]:
    """Apply an interactive player's action, then advance. Raises
    IllegalActionError on any violation (see §4.5). Returns like advance()."""

@property
def pending_request(self) -> Optional[ActionRequest]:
    """The outstanding request if the game is paused, else None."""
```

`start_game()` (the existing method) becomes:

```python
def start_game(self) -> None:
    req = self.start_hand()
    if req is not None:
        raise RuntimeError(
            "start_game() is synchronous-only; this table has interactive "
            "players — drive it with start_hand()/submit_action()")
```

Bot-only callers (benchmarks, tests, current TUI with blocking TerminalPlayer) are
untouched: with no interactive players, `start_hand()` always runs to completion and
returns None, so `start_game()` behaves exactly as before.

### 4.3 New error type (in `core/game.py` or `core/errors.py`)

```python
class IllegalActionError(Exception):
    """Raised by submit_action for out-of-turn or invalid actions."""
```

### 4.4 The refactor of `run_cycle` / `_handle_betting_round` (the hard part)

The current `_handle_betting_round` is one while-loop containing blind posting, the
action loop, and per-action bookkeeping. It must become **suspendable**: exit when
an interactive player is up, and continue later exactly where it left off.

**Approach: explicit persisted loop context.** Do NOT use generators/coroutines —
an explicit context object is easier to reason about, serialize, and debug.

Add to `Game.__init__`:

```python
self._round_ctx = None          # per-betting-round loop state, None between rounds
self._pending_request = None    # ActionRequest currently awaiting submit_action
```

**Step 1 — split `_handle_betting_round` into three methods:**

```python
def _begin_betting_round(self) -> None:
    """Everything before the action loop: the can_act() short-circuit check,
    computing heads_up / start_idx, and (preflop only) posting antes + blinds.
    Ends by storing the loop context:
        self._round_ctx = {
            'players_to_act': [p for p in self.players if p.can_act()],
            'current_idx': start_idx,
            'iterations': 0,
            'max_iterations': len(players_to_act) * 2 + 10,
        }
    If the round is a no-op (<=1 player can act), set self._round_ctx = None."""

def _continue_betting_round(self) -> Optional[ActionRequest]:
    """The action while-loop, reading/writing self._round_ctx. Behavior per
    iteration is IDENTICAL to today with ONE addition: when the player to act
    has p.interactive == True, build an ActionRequest (see §4.1), store it in
    self._pending_request, and RETURN it — leaving _round_ctx untouched so the
    loop resumes at the same player. For non-interactive players call
    p.get_action(...) and feed the result to _apply_action(...) exactly as the
    current loop body does. When the loop finishes (players_to_act empty, or
    max_iterations hit, or one active player left), set self._round_ctx = None
    and return None."""

def _apply_action(self, p, action, amt) -> None:
    """The current loop body's action-application block, extracted verbatim:
    fold handling (+fold_streets), lose_chips + street_investments +
    pot contributions, the raise-reopens-betting players_to_act reset,
    bet_manager.process_bet with is_raise flag, _log_action, all-in log line,
    and the Phase 1 action_taken event emit. Mutates self._round_ctx
    ('players_to_act', and increments 'iterations')."""
```

Critical details to carry over exactly:
- The skip logic at the top of each loop iteration (player not in
  `players_to_act` or `not can_act()` → remove if newly unable, advance
  `current_idx`, `continue`).
- `iterations` increments once per player reached who can act (i.e., where the
  current code does `iterations_without_progress += 1` — *before* getting the
  action), including when we pause for an interactive player? **No** — increment
  only when an action is actually applied, otherwise a pause/resume cycle would
  double-count. Move the increment into `_apply_action`. This is a deliberate,
  safe deviation: the counter exists only as an infinite-loop guard.
- The raise-reopen rule: reset `players_to_act` only when
  `action in (RAISE, ALL_IN) and actual_deducted > bet_manager.get_amount_to_call(p.player_id)`
  — note the comparison uses the amount-to-call **before** `process_bet` is called,
  exactly as today.
- After applying any action: `current_idx = (current_idx + 1) % n`, then break the
  loop if only one active player remains.
- **Resume-at-same-player rule:** when pausing for an interactive player, do NOT
  advance `current_idx`. When `submit_action` later applies the action, THEN
  advance `current_idx` (inside the normal flow) and continue the loop.

**Step 2 — make `run_cycle` resumable.** Replace the body of `run_cycle` with a
loop that can exit early:

```python
def run_cycle(self) -> Optional[ActionRequest]:
    while self.state != GameState.WAITING:
        if self.state == GameState.DEAL:
            self._handle_deal()          # unchanged; may set WAITING if <2 players
        elif self.state in (GameState.PREFLOP, GameState.FLOP,
                            GameState.TURN, GameState.RIVER):
            if self._round_ctx is None:
                if self.state != GameState.PREFLOP:
                    self._deal_community(3 if self.state == GameState.FLOP else 1)
                self._begin_betting_round()
            req = self._continue_betting_round()
            if req is not None:
                return req                                   # paused
            # round complete → transition exactly as today:
            if self.state == GameState.RIVER:
                self.state = GameState.SHOWDOWN
            else:
                self.state = (GameState.SHOWDOWN if self._is_hand_over()
                              else _NEXT_STREET[self.state])  # PREFLOP→FLOP→TURN→RIVER
        elif self.state == GameState.SHOWDOWN:
            self._handle_showdown()
            self.state = GameState.END
        elif self.state == GameState.END:
            self._handle_end()
            self.state = GameState.WAITING
    return None
```

Guard against re-dealing community cards on resume: `_deal_community` and
`_begin_betting_round` run only when `self._round_ctx is None` **and** the round
hasn't started. Use a second flag if needed: set `self._round_started = True` inside
`_begin_betting_round`, clear it on round completion and in `_handle_deal`. The
simplest correct scheme: `_round_ctx is None and not self._round_started` → begin;
after `_continue_betting_round()` returns None → `self._round_started = False`.
(When a round is a no-op — everyone all-in — `_begin_betting_round` sets ctx None;
`_continue_betting_round` must treat `ctx is None` as "round already complete,
return None".)

**Step 3 — wire the public API:**

```python
def start_hand(self):
    if len(self.players) < 2:
        self.log("Not enough players to start."); return None
    if self._pending_request is not None:
        raise IllegalActionError("A hand is already in progress awaiting an action")
    self.state = GameState.DEAL
    return self.advance()

def advance(self):
    if self._pending_request is not None:
        return self._pending_request         # still waiting; idempotent
    req = self.run_cycle()
    self._pending_request = req
    return req

def submit_action(self, player_id, action, amount=0):
    req = self._pending_request
    if req is None:
        raise IllegalActionError("No action is pending")
    if player_id != req.player_id:
        raise IllegalActionError(f"Not {player_id}'s turn (waiting on {req.player_id})")
    self._validate_action(req, action, amount)   # §4.5
    self._pending_request = None
    p = next(pl for pl in self.players if pl.player_id == player_id)
    self._apply_action(p, action, amount)        # includes players_to_act bookkeeping
    # advance current_idx past the actor + check one-active-player break,
    # mirroring the tail of the loop iteration, then:
    return self.advance()
```

The cleanest way to avoid duplicating the "tail of the loop iteration" is to have
`_apply_action` itself do the `current_idx` advance and store an `abort_round` flag
in ctx when only one active player remains; `_continue_betting_round` checks that
flag at loop top. Then `submit_action` is just: validate → `_apply_action` →
`advance()`.

### 4.5 `_validate_action(req, action, amount)` rules

Raise `IllegalActionError` unless:
- `action.value in req.legal_actions`.
- FOLD/CHECK → require `amount == 0` (or ignore amount; pick one, document it —
  recommend: ignore and force 0).
- CALL → engine sets `amount = min(p.chips, req.min_call)` itself; ignore the
  client-provided amount. If that equals the stack, convert to ALL_IN
  (mirror `TerminalPlayer`'s behavior at players/terminal.py:126–129).
- RAISE → require `req.min_raise_total <= amount <= p.chips`; if
  `amount == p.chips`, convert to ALL_IN.
- ALL_IN → engine forces `amount = p.chips`.

Normalizing (converting/clamping) rather than rejecting keeps clients simple and
matches what the TUI already does.

### 4.6 What explicitly does NOT change in Phase 2

- `strategies/` — nothing.
- `players/bot.py`, `players/roster.py` — nothing.
- `players/terminal.py` — nothing (still blocking, still works, because
  `interactive = False`).
- `main.py` — nothing. Benchmarks and TUI run the same code path.
- Blind posting, showdown, stats, blind escalation logic — moved but not modified.

### 4.7 Phase 2 acceptance criteria

- [ ] `pytest tests/` green, unchanged tests untouched.
- [ ] New `tests/test_resumable_engine.py`:
  1. **Equivalence test (the important one):** seed determinism is Phase 3, so use
     this trick instead — create two games with identical players where the human
     seat is (a) a scripted `Player` subclass returning actions from a list
     synchronously, (b) an `AgentPlayer` fed the same list via
     `start_hand()/submit_action()`. Monkeypatch `Deck.reset` to produce an
     identical card order for both (e.g. patch `random.shuffle` to a fixed
     permutation for the test). Assert final chip counts, pot events, and winners
     are identical.
  2. **Pause/resume mechanics:** with 1 AgentPlayer + 2 bots, `start_hand()`
     returns an ActionRequest with the agent's id when it's their turn;
     `pending_request` is stable across repeated `advance()` calls; submitting
     out-of-turn player_id raises; submitting illegal raise size raises;
     after a FOLD the hand runs to completion (returns None) without further input.
  3. **Raise re-opens betting:** agent calls, bot raises, assert the agent gets a
     second ActionRequest on the same street with updated `min_call`.
  4. **All-in agent:** agent goes all-in preflop; assert no further requests and
     hand completes.
  5. **Bot-only regression:** `start_game()` on an 8-bot table for 200 hands
     completes with no exception and total chips conserved
     (`sum(p.chips) + 0 == n_players * starting_chips` given no rebuys).
- [ ] Benchmark timing within noise of pre-refactor (bot-only path adds only an
  `interactive` attribute check per action).
- [ ] Manual TUI smoke test: identical experience.

---

## 5. Phase 3 — Serialization & Per-Viewer Snapshots

**Goal:** everything a GUI needs to render, as JSON-safe dicts, with hidden
information filtered per viewer. Plus a seedable deck for tests/replays.

### 5.1 Card serialization (`core/card.py`)

Add (do not change existing methods):

```python
SUIT_CODE = {Suit.SPADES: 'S', Suit.HEARTS: 'H', Suit.DIAMONDS: 'D', Suit.CLUBS: 'C'}

class Card:
    def to_dict(self) -> dict:
        return {"rank": self.rank,                    # 2..14
                "suit": SUIT_CODE[self.suit],          # 'S'|'H'|'D'|'C'
                "display": repr(self)}                 # e.g. "A♠"
```

### 5.2 Seedable deck (`core/deck.py`)

```python
class Deck:
    def __init__(self, min_rank: int = 2, seed: int | None = None):
        self._rng = random.Random(seed) if seed is not None else random
        ...
    def shuffle(self):
        self._rng.shuffle(self.cards)
```

Add `seed: int | None = None` parameter to `Game.__init__`, passed through to
`Deck`. Default None → behavior identical to today.

### 5.3 Per-viewer snapshot: `Game.view_for(viewer_id)`

New method on `Game` (or a new `core/views.py` module with
`build_view(game, viewer_id)` — prefer the separate module to keep `game.py` from
growing). Contract:

```jsonc
{
  "hand_number": 12,
  "state": "FLOP",                      // GameState.value; "WAITING" between hands
  "street": "flop",
  "community_cards": [{"rank": 14, "suit": "S", "display": "A♠"}, ...],
  "pot": 340,
  "pots": [ {"amount": 300, "eligible": ["h1","b2"]}, ... ],   // only populated at showdown; [] mid-hand
  "blinds": {"small": 10, "big": 20, "ante": 0, "level": 1},
  "dealer_player_id": "b2",
  "game_mode": "tournament",
  "short_deck": false,
  "players": [
    {
      "player_id": "h1",
      "name": "Player 1",
      "chips": 880,
      "is_active": true,
      "is_all_in": false,
      "role": "BB",                      // from game.player_roles; "" between hands
      "bet_this_round": 40,              // bet_manager.player_bets_this_round
      "invested_this_hand": 60,          // pot_manager.contributions
      "is_you": true,
      "hole_cards": [{...}, {...}]       // ONLY when is_you; else key omitted entirely
    },
    ...
  ],
  "you": {
    "player_id": "h1",
    "to_act": true,                      // pending_request.player_id == viewer_id
    "action_request": {                  // null unless to_act
      "legal_actions": ["fold","call","raise","all-in"],
      "min_call": 20, "min_raise_total": 60, "max_raise_total": 880,
      "pot_size": 340, "street": "flop", "seq": 187
    }
  },
  "last_event_seq": 187
}
```

Rules:
- **Never include another player's `hole_cards`** in a view — not even folded ones.
  Showdown reveals happen exclusively through `hole_cards_shown` events. Omit the
  key rather than sending null/empty (makes leaks grep-able in tests).
- `viewer_id=None` (spectator) → no hole cards at all, `you` is null.
- Everything must survive `json.dumps(view)` — test that exact call.

### 5.4 Upgrade event payloads

Change card-bearing event payloads (`hole_cards_dealt`, `street_started`,
`hole_cards_shown`, `seating` untouched) from display strings to
`Card.to_dict()` lists. Update the Phase 1 TerminalPlayer event renderer to use
`["display"]`. Add:

```python
def events_for(self, viewer_id, since_seq: int = -1) -> list[dict]:
    """Serialized events after since_seq, with hole_cards_dealt filtered:
    included only when data['player_id'] == viewer_id."""
```

### 5.5 Phase 3 acceptance criteria

- [ ] `pytest` green; new `tests/test_views.py`:
  - `json.dumps(game.view_for(...))` succeeds mid-hand, at showdown, between hands.
  - Viewer sees own hole cards; assert `'hole_cards' not in` every other player
    dict; spectator sees none.
  - `events_for("h1")` never contains a `hole_cards_dealt` for another player.
  - Two games constructed with `seed=42` deal identical cards for 20 hands
    (equal event streams modulo nothing — they should be exactly equal with
    scripted identical actions).
- [ ] `view_for` correctness spot-checks: `pot` equals `pot_manager.total_pot()`;
  `bet_this_round` matches `bet_manager`; `to_act` consistent with
  `pending_request`.

---

## 6. Phase 4 — Transport (Web API)

**Only for a web GUI.** A desktop GUI (tkinter/pygame) needs nothing from this
phase — it calls `start_hand`/`submit_action`/`view_for` in-process.

### 6.1 Dependencies (first ones in the project)

Create `requirements.txt`:

```
fastapi
uvicorn[standard]
```

(WebSocket support comes via uvicorn's `websockets` extra. Pydantic ships with
FastAPI; use it only at the transport boundary — the engine stays dependency-free.)

### 6.2 New package layout

```
api/
  __init__.py
  server.py        # FastAPI app factory, uvicorn entry (`python -m api.server`)
  sessions.py      # GameSession + in-memory SessionManager
  schemas.py       # Pydantic request/response models
```

Do not modify anything in `core/` or `players/` in this phase (that's the proof the
earlier phases worked).

### 6.3 `sessions.py`

```python
class GameSession:
    """One table. Owns a Game, a threading.Lock, and per-connection event queues."""
    def __init__(self, session_id: str, settings: dict): ...
    # builds Game + AgentPlayer("h1", name, chips) + create_bots(...) same as
    # main.py::_build_game but with AgentPlayer instead of TerminalPlayer,
    # game_mode='tournament', live_output=False, seed from settings (optional)
```

Concurrency model — keep it simple and correct:
- The engine is synchronous, single-table, and fast between human actions (bots
  decide in microseconds). **One `threading.Lock` per session**; every endpoint
  that touches the Game acquires it. Run engine calls via
  `await asyncio.to_thread(...)` in FastAPI handlers so the event loop is never
  blocked while a lock is held.
- `SessionManager`: dict `session_id → GameSession`, `create()`, `get()`,
  `remove()`, plus an idle TTL sweep (e.g. drop sessions untouched for 2h) so the
  process doesn't leak tables. `session_id = uuid4().hex`.
- Single human seat per table in v1 (`player_id` fixed as `"h1"`). Multi-human
  tables are out of scope — the engine supports it (multiple AgentPlayers), but
  auth/seat management is not v1.

### 6.4 Endpoints

| method | path | body → response |
|--------|------|-----------------|
| POST   | `/games` | settings `{player_name, num_bots, difficulty: "easy"\|"normal"\|"hard", starting_chips, big_blind, hands_per_level, enable_ante, short_deck, shuffle_bots, seed?}` → `201 {game_id, view}` (game created, hand NOT started) |
| POST   | `/games/{id}/hands` | start next hand → `{view}`; `409` if a hand is in progress; auto-applies the between-hands logic from `main.py::_run_session`: if human chips == 0, require `{"rebuy": true}` in body else `409 {"reason": "busted"}`; if ≤1 active player total → `409 {"reason": "game_over", "winner": ...}` |
| GET    | `/games/{id}/state` | → `view_for("h1")` |
| GET    | `/games/{id}/events?since={seq}` | → `{"events": events_for("h1", since)}` (polling fallback) |
| POST   | `/games/{id}/action` | `{action: "fold"\|"check"\|"call"\|"raise"\|"all-in", amount?: int}` → `{view}`; `IllegalActionError` → `422 {"detail": str(e)}`; not your turn / no pending → `409` |
| GET    | `/games/{id}/stats` | → JSON of `game.stats` per player + `hand_count` |
| DELETE | `/games/{id}` | end session → `204` |
| WS     | `/games/{id}/ws` | server pushes `{"type": "events", "events": [...]}` after every state change, plus `{"type": "view", "view": {...}}`; client may send actions over the socket too (same schema as POST /action) |

Every POST handler's flow: lock → engine call → collect
`events_for("h1", since=cursor)` → broadcast to that session's WS connections →
return the fresh view. Map action strings to `PlayerAction` via
`PlayerAction(action_str)` (the enum values already match: `"all-in"` etc.).

Difficulty mapping: reuse `strategies.difficulty.EASY/NORMAL/HARD` exactly as
`main.py::_collect_settings` does.

### 6.5 Phase 4 acceptance criteria

- [ ] `tests/test_api.py` using `fastapi.testclient.TestClient`:
  - create game (seeded) → start hand → poll state → play a full hand to
    completion via `/action` responding to `you.to_act` / `action_request`
    (write a tiny "always call" driver loop); assert `hand_ended` event arrives
    and chips conserve.
  - illegal action → 422; wrong-turn action → 409; unknown game → 404.
  - no hole-card leakage anywhere in any response payload
    (recursive scan for `hole_cards` keys not belonging to `h1`).
- [ ] Manual: `uvicorn api.server:app`, drive a hand with `curl`.
- [ ] `python main.py` still fully functional (TUI untouched).

---

## 7. Known Pitfalls (read before coding, re-read when stuck)

1. **Raise re-opens betting.** The `players_to_act` reset on raise is the #1 place
   the resumable refactor can silently diverge. The equivalence test in §4.7 exists
   for exactly this.
2. **All-in blind posters.** `players_to_act` is built AFTER blind posting so a
   player who went all-in posting a blind is excluded (they `can_act() == False`).
   Preserve that ordering in `_begin_betting_round`.
3. **Heads-up order flips.** SB/dealer acts first preflop, BB first postflop.
   ActionRequests must respect this — covered if you preserve `start_idx` logic.
4. **`min_raise` semantics.** `bet_manager.min_raise` is the raise *increment*; the
   minimum legal *delta* to push is `min_call + min_raise`, clamped to stack. The
   TUI already computes it this way (`min_raise_total` in players/terminal.py:80).
5. **CALL converting to ALL_IN.** When `min_call >= chips`, the correct action is
   ALL_IN for the stack. Normalize in `_validate_action`, don't reject.
6. **Amounts are deltas** (§1.4). GUI clients will be tempted to send raise-to
   totals. The API contract is delta; document it in `schemas.py` docstrings and
   keep `ActionRequest.min_raise_total` naming explicit.
7. **`_handle_deal` can bail to WAITING** (fewer than 2 funded players). `advance()`
   then returns None with no hand played — the Phase 4 `/hands` endpoint must
   detect this (`game.hand_count` unchanged) and return the game-over 409.
8. **Split-pot remainder** goes to the winner closest left of the dealer
   (core/showdown.py:124–130). Don't touch; just make sure `pot_awarded` events sum
   correctly.
9. **`pending_msg`** (blind level-up notice) is logged at the start of the *next*
   hand. Emit `blinds_raised` at escalation time in `_handle_end` regardless — the
   event stream should not inherit the string-log's deferral quirk.
10. **Simulation memory.** Benchmarks run ~500k hands in one `Game`. Anything you
    accumulate per action must be cleared per hand when `live_output=False` (§3.3.5).
11. **Do not add `to_dict` calls in hot bot paths.** Serialization happens only in
    `view_for`/`events_for`, which only interactive clients call.
12. **`fold_streets` bookkeeping** feeds the showdown "folded on X" display; it's
    updated inside the fold branch — keep it inside `_apply_action`.

---

## 8. Suggested Commit Sequence

1. `Phase 1: structured GameEvent stream + terminal renders events` (+ tests)
2. `Phase 1.1: pass logs by reference (fix O(n²) hand_log copy)`
3. `Phase 2a: extract _apply_action + split betting round begin/continue` (pure
   mechanical move, everything still synchronous — tests green proves the split)
4. `Phase 2b: resumable run_cycle + AgentPlayer + advance/submit_action` (+ tests)
5. `Phase 3: card/event serialization, seedable deck, view_for` (+ tests)
6. `Phase 4: FastAPI transport (api/ package)` (+ tests, requirements.txt)

Each commit independently leaves `pytest` green and the TUI working. Do not combine
3 and 4 — the mechanical split (3) being verified separately is what makes the
behavioral change (4) reviewable.
