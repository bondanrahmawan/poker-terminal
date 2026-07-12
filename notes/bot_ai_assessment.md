# Bot AI Deep Assessment — Styles, Difficulty, and Improvement Plan

Date: 2026-07-12
Scope: `players/bot.py`, `strategies/*` (engine, profile, opponent_model,
dynamic_behavior, draw_detection, betsizing, preflop_ranges, hand_score,
simple, utils, difficulty), and their runtime wiring in `core/game.py` and
`players/roster.py`.

This is an assessment + spec document. Nothing in the codebase was changed.
Sections 7–9 are written so a lesser model can implement them phase-by-phase
in fresh context windows (same workflow as `notes/gui_api_implementation_plan.md`).

---

## 1. Executive summary

**Usage verified first** (Section 3): every production entry point — browser
play, terminal play, benchmarks — instantiates `DesignedBotStrategy`
archetypes via the roster. There is no second, cruder bot secretly running;
`SimpleStrategy` is test-only. The catch is that the wiring bugs below make
the advanced bot's *effective* behavior collapse toward the simple one.

The bot architecture is **well-designed on paper and mostly well-tested at the
unit level, but a cluster of wiring bugs means several headline features are
dead or misfiring at runtime**:

- Opponent modeling runs, but each bot **tracks itself as an opponent**, counts
  every action as "preflop", and **re-counts the same log lines on every
  decision** — the stats it exploits are garbage-in.
- `fold_to_bet` is never populated, so `opp_folds_often` is always False —
  the bluff-exploitation and fold-equity machinery is effectively **static
  constants**, not adaptation.
- The **position-aware opening ranges are ~dead code**: preflop, every seat
  except the BB faces `min_call > 0` (the blind), so the "facing a raise"
  branch handles what should be opens. Bots "open" via 3-bet logic.
- Table image is permanently "very loose" because preflop folds are never
  recorded.
- Gutshot detection has an off-by-one (checks rank-span 5 instead of 4), so it
  flags non-draws and misses real gutshots.
- Tilt's bad-beat trigger never fires because `was_favorite` is a placeholder
  equal to `won` (a known TODO in `core/game.py`).

Despite this, the bots *play plausibly* — the profile parameters
(play_range/aggression/bluff_freq/call_freq) do most of the visible work, and
the equity + pot-odds core is sound. Fixing the wiring (Phase 1) is cheap and
would make the already-written exploitation/dynamic layers actually function.
After that, the highest-leverage improvements are a **mistake-based difficulty
model** (Phase 2) and **structured event input instead of log-string parsing**
(part of Phase 1). A genuinely new variant is optional (Section 9).

---

## 2. Architecture map (as-is)

```
BotPlayer (players/bot.py)
  └─ strategy.decide(game_state: dict, PlayerView) -> (PlayerAction, int)
       ├─ SimpleStrategy (strategies/simple.py)      — 1-param equity/pot-odds bot
       └─ DesignedBotStrategy (strategies/engine.py) — the real bot, used by roster
            ├─ StyleProfile (profile.py)             — 8 named personalities
            ├─ difficulty float 0.2–1.0 (difficulty.py) — noise injection
            ├─ OpponentTracker (opponent_model.py)   — VPIP/PFR/fold-to-bet + exploits
            ├─ TiltState, TableImage (dynamic_behavior.py)
            ├─ detect_draws / advanced_equity / monte_carlo_equity (draw_detection.py)
            ├─ choose_bet_size / choose_raise_size (betsizing.py)
            ├─ preflop ranges + 3-bet + BB defend (preflop_ranges.py)
            └─ score_starting_hand (hand_score.py)   — 0–100 preflop table
```

Inputs from `core/game.py:_build_game_state` (game.py:518-528): `min_call`,
`min_raise`, `pot_size`, `community_cards`, `players_info` (name, chips,
is_active — all seats), `position` (0 = BTN), `player_role` (correct label,
computed by the engine), `num_active`, `hand_log` (the raw text log),
`events` (structured events — currently unused by bots).

Feedback loop: `game.py:693-701` calls `record_hand_result(won, amount,
was_favorite=won)` on every bot after each hand.

Roster (`players/roster.py`): 12 named bots over 8 archetypes; global
difficulty from web settings (easy 0.4 / normal 0.6 / hard 0.75), with three
per-bot overrides (Frank plays HARD, Iris/Jack play EASY at normal).

Validation surface that already exists and should anchor all future work:
`core/benchmark.py` all-vs-all archetype tournaments + `tests/` (260+ tests,
including `test_strategies.py`, `test_enhanced_strategies.py`).

---

## 3. Which bot code actually runs (usage verification)

Question audited: *is the sophisticated bot actually the one sitting at the
table, or do games secretly run a simpler implementation?*

**Answer: the advanced bot is the production bot.** Every play path was
traced to its `BotPlayer` construction site:

| Entry point | Construction path | Bot code used |
|-------------|-------------------|---------------|
| Browser play (`run_web.py`) | `api/sessions.py:63` → `create_bots()` (`players/roster.py:34`) | Roster of 12 named bots, **all `DesignedBotStrategy` archetypes** from `strategies/engine.py`; difficulty easy 0.4 / normal 0.6 / hard 0.75 from session settings |
| Terminal play | `main.py:786` → `create_bots()` | Same roster |
| Benchmarks / simulations | `core/benchmark.py:76,162-163,234-243` (via `api/simulations.py` or `main.py` menu) | Archetype classes directly (all `DesignedBotStrategy`) |
| Test suite | `tests/*` | Mostly `SimpleStrategy` (cheap, predictable) |

`SimpleStrategy` appears in **no production path**. It survives only as
(a) the implicit default of a bare `BotPlayer(...)` with no strategy argument
(`players/bot.py:22`) — exercised only by `tests/test_game.py` — and (b) the
explicit strategy in most engine-level tests, which is fine and even desirable
(tests shouldn't depend on the fancy bot's randomness).

**The nuance that makes the worry half-right:** production runs the advanced
bot, but because of the wiring bugs in Section 5, its adaptive layers receive
degenerate inputs. What actually expresses at the table is roughly
"`SimpleStrategy` + personality floats + draw-aware equity + varied bet
sizing" — sophisticated code running in a partially degraded mode, not a
different bot.

### Confirmed-unused / leftover bot-related code

(Flagged per repo policy — mentioned, not deleted.)

- `strategies/archetypes.py` — pure re-export shim; **nothing imports it**
  (roster and benchmark import from `strategies.engine` directly). Its
  `CallingStationStrategy` alias is unused.
- `strategies/dynamic_behavior.py:adjust_for_desperation()` — imported by
  `engine.py:26` but never called; only its own unit tests exercise it.
- `strategies/draw_detection.py:equity_vs_range()` — never called anywhere
  (Phase 4 proposes finally using it).
- `strategies/difficulty.py`: `very_easy` (0.2), `expert` (0.9) and
  `perfect` (1.0) are unreachable from any play UI — the web exposes only
  easy/normal/hard, and roster overrides use EASY/NORMAL/HARD. (Benchmark
  API accepts expert.)
- `betsizing.BetSize.MIN_RAISE` — defined but never chosen by
  `choose_bet_size`.
- `stats_tracker_before.py` (repo root, untracked-looking) — appears to be a
  pre-refactor backup of `core/stats_tracker.py`; not bot code, but noticed
  during this audit.

---

## 4. What is genuinely good

- **Clean separation**: BotPlayer is a shell; strategies are swappable and
  registered by name. Adding a variant costs one class.
- **StyleProfile as data**: 8 archetypes from 5 floats — easy to tune, easy to
  extend, benchmarkable.
- **Solid core loop**: equity estimate vs pot odds, with draw awareness and
  varied bet sizing. This is the right skeleton for a game bot.
- **Deception exists**: slow-play (Trapper), semi-bluff, board-texture bluffs
  — the *concepts* players notice are all present.
- **Unit test coverage** of the strategy components is real. The bugs below
  are integration/wiring bugs, which the unit tests can't see.
- **Benchmark harness** (`core/benchmark.py`) means improvements can be
  measured, not guessed.

---

## 5. Findings — bugs and dead wiring

Severity: **H** = feature silently dead/corrupt, **M** = wrong in common
situations, **L** = latent/edge.

| # | Sev | Where | Finding |
|---|-----|-------|---------|
| B1 | H | engine.py:92-93, 164, 268 | Bot never knows its own identity. `bot_name` is read as `players_info[0][0]` (just the first seat), and `_extract_opponent_ids(players_info, '')` is called with `''` — so **the bot's own name is included in `opponent_ids`** and it exploits/models itself. `self._bot_name` (engine.py:136) is read via `getattr` but **never assigned**, so its own actions are also recorded into its opponent tracker. |
| B2 | H | engine.py:124-146 | `_record_opponent_actions` re-parses `hand_log[-20:]` on **every** `decide()` call, with no cursor/dedup, and `Game.logs` is never cleared between hands — the same action lines are counted many times, inflating all counters. It also matches non-action lines (e.g. the showdown summary `"X folded on flop"` → counted as another fold). Names with spaces (human players) break `parts[0]` parsing. |
| B3 | H | engine.py:140-146 | Every recorded action is hard-coded `street='preflop'`. Consequences: postflop calls/raises inflate VPIP; **`bets_faced`/`folds_to_bet` are never incremented**, so `fold_to_bet` stays at its 0.3 prior forever → `opp_folds_often` is always False → the bluff-vs-folders exploit, big-bluff sizing, and semi-bluff-vs-folders paths never trigger, and `opponent_fold_equity()` returns a constant ≈0.045 that is **always added to equity** (engine.py:283) — a flat optimism bias rather than adaptation. |
| B4 | H | engine.py:168, preflop_ranges.py:173-187 | **Opening ranges are ~dead.** `is_opening=(min_call == 0)` is only true for the BB checking its option (everyone else must at least call the blind preflop). So: (a) `position_to_range(..., is_opening=False)` collapses to `'medium'` for all seats; (b) the entire "Opening" block (engine.py:203-247 — open-raise sizing, desperation shove, premium trap, late-position limp) is reachable **only by the BB**; (c) an unopened pot is handled by the "facing a raise" branch, so bot opens are actually `should_3bet` hits + flat calls. The carefully-built tight/wide/very_wide/sb_wide ranges and the BTN/CO limp branch are dead weight. |
| B5 | H | dynamic_behavior.py:111, engine.py | `TableImage.record_preflop_fold()` is **never called** (only `record_preflop_enter`/`record_raise` are). `tightness` → 0 permanently, so the image is always "very loose", which suppresses `should_slow_play`'s image bonus and makes `bluff_success_rate`/`value_bet_call_rate` constants. |
| B6 | M | game.py:699-700 | `was_favorite = won` placeholder (marked TODO). Bad-beat tilt (`record_loss(..., was_favorite=True)`) can never fire; tilt only accrues +0.05/loss and decays faster than it builds in practice. Tilt is near-inert. |
| B7 | M | draw_detection.py:150-175 | Gutshot off-by-one: a gutshot is 4 ranks spanning **4** (e.g. 5-6-7-9); the code requires span `== 5`, which instead matches double-gap non-draws (e.g. 5-6-8-10) and misses every real gutshot. `_has_double_gutshot` inherits the same bug. Net effect: 4-out draws are misclassified in both directions; `total_outs`, semi-bluff triggers, and draw equity are wrong whenever a straight draw is involved. |
| B8 | M | engine.py:107-120 vs game.py:522-525 | The engine recomputes its position label from `position` (indexed over **all** seats incl. busted) but maps it with `num_active` (active seats only) — labels are wrong once anyone busts. Meanwhile the game already passes a correct `player_role` string that the bot ignores. |
| B9 | L | engine.py:337-356, betsizing.py:104-112 | `choose_raise_size` can return `(PlayerAction, int)` tuples (slow-play/default branches); the caller's `isinstance(amt, int)` check would then feed a CALL amount into `_action_raise_or_all_in`. Currently unreachable (`is_slow_play` is never passed), but it's a trap. |
| B10 | L | opponent_model.py:121-126 | `record_missed_opportunity()` is never called; VPIP denominators only grow via the buggy log parsing above. |
| B11 | L | simple.py / draw_detection.py:229-232 | Preflop equity is binary (0.55 strong / 0.32 weak) — `score_starting_hand`'s 0–100 table exists but isn't used for equity. AA and 66 preflop look identical to SimpleStrategy and to `advanced_equity` preflop. |
| B12 | L | engine.py:283-285 | Fold equity is added to *equity* before the pot-odds **call** decision. Fold equity only exists when you bet/raise (a call can't make anyone fold); adding it to call decisions systematically over-calls. |

**Meta-finding:** the root cause of B1–B3 is that bots consume the
**human-readable text log** as their data source. The engine already emits
structured events (`core/events.py`, passed as `game_state['events']`) with
player ids, action types and streets — the bots just don't use them.

---

## 6. Styles assessment

### 6.1 How a profile becomes behavior

Each style is a `StyleProfile` of five floats (profile.py:8-23). Where each
one bites in `DesignedBotStrategy`:

- **`play_range`** → preflop entry threshold: `threshold = (1-play_range)*100`
  compared against the 0–100 `score_starting_hand` table (engine.py:173).
  0.25 means "needs a ~75+ score hand", 0.95 means "plays almost any two".
- **`aggression`** → probability of raising in every spot that allows it
  (open, 3-bet gate, postflop value raise), plus raise sizing
  (`fraction = 0.5 + aggression*0.5` → half-pot to full-pot), plus inputs to
  slow-play/semi-bluff chance.
- **`bluff_freq`** → gate on the postflop no-bet bluff check
  (`_should_bluff_v2`, engine.py:431).
- **`call_freq`** → probability of actually calling once pot odds justify it
  (both preflop in-range calls and postflop equity calls).
- **`slow_play_freq`** → chance to check/call instead of betting with
  trips+/75%-equity hands (engine.py:320-329). Only Trapper sets it.

### 6.2 The 8 archetypes — parameters and table character

| Style | play_range | aggression | bluff_freq | call_freq | slow_play |
|-------|-----------|------------|------------|-----------|-----------|
| tight_passive | 0.25 | 0.15 | 0.05 | 0.80 | — |
| tight_aggressive | 0.25 | 0.80 | 0.30 | 0.20 | — |
| loose_passive | 0.75 | 0.15 | 0.05 | 0.85 | — |
| loose_aggressive | 0.75 | 0.80 | 0.60 | 0.40 | — |
| maniac | 0.95 | 0.95 | 0.80 | 0.50 | — |
| nit | 0.10 | 0.40 | 0.03 | 0.20 | — |
| balanced | 0.50 | 0.50 | 0.25 | 0.50 | — |
| trapper | 0.30 | 0.20 | 0.10 | 0.85 | 0.75 |

What each one looks like from the human's seat (current build, bugs and all):

- **Tight-Passive ("the rock caller")** — enters ~1 in 4 hands, then mostly
  flat-calls (80% call gate) and almost never raises. Postflop it check-calls
  with equity and gives up without. A raise from this bot ≈ a monster.
  Counter: value-bet it relentlessly; fold to its aggression.
- **Tight-Aggressive (TAG, "the reg")** — same tight entry, but raises 80% of
  the time it plays, 3-bets its premium range, value-raises strong hands and
  semi-bluffs draws; low call_freq (0.20) means it raises-or-folds rather than
  calls. The most fundamentally sound archetype; usually tops the benchmark.
- **Loose-Passive ("the calling station")** — plays 3 of 4 hands, calls
  almost anything (0.85), raises almost never, bluffs almost never. The
  classic fish. Counter: value-bet thin, never bluff it.
- **Loose-Aggressive (LAG)** — plays 3 of 4 hands *and* raises 80% of the
  time with a 0.60 bluff base. Constant pressure, big variance. Counter:
  call down lighter, let it barrel into your made hands.
- **Maniac** — 95% of hands, 95% raise rate, 80% bluff rate. A chaos
  generator that inflates every pot; typically busts fast or steamrolls a
  short session. Counter: wait for a real hand, then let it hang itself.
- **Nit** — plays only ~10% of hands (roughly TT+/AQ+ territory on the score
  table), rarely bluffs (0.03), folds to pressure (call 0.20). Its money goes
  in only with the goods. Counter: steal its blinds forever; fold when it
  wakes up.
- **Balanced** — 0.50 across the board; the "average opponent" and the
  default archetype (3 of the 12 roster seats). Hardest to type-cast, and the
  natural baseline for benchmarking other styles.
- **Trapper** — tight-ish entry, passive line, but slow-plays 75% of its
  strong made hands: check/calls trips+ to spring river raises. The only
  profile exercising `slow_play_freq`, and its branch is correctly wired.
  Reads as a weak-passive player until the trap closes. Counter: pot-control
  when it check-calls twice.

### 6.3 Who actually sits at the table (roster mapping)

`players/roster.py` — seats are taken in list order unless
`shuffle_bots` is on, so **a default 3-bot game is always Alice + Bob +
Charlie = Balanced + TAG + Calling-Station**:

| Seat | Archetype | Difficulty quirk |
|------|-----------|------------------|
| Bot_Alice | Balanced | table setting |
| Bot_Bob | TightAggressive | table setting |
| Bot_Charlie | LoosePassive | table setting |
| Bot_Dave | TightPassive | table setting |
| Bot_Eve | Balanced | table setting |
| Bot_Frank | TightAggressive | forced HARD when table ≥ normal |
| Bot_Grace | Nit | table setting |
| Bot_Hank | LooseAggressive | table setting |
| Bot_Iris | Balanced | forced EASY when table ≤ normal |
| Bot_Jack | TightAggressive | forced EASY when table ≤ normal |
| Bot_Mike | Maniac | table setting |
| Bot_Victoria | Trapper | table setting |

The Frank/Iris/Jack overrides are a nice touch (skill spread within one
table) but are invisible to the player — nothing in the UI hints that Frank
plays sharper than Jack. Worth surfacing (or at least documenting) once
difficulty means more (Phase 2).

### 6.4 Assessment

The grid is a good spread on the classic tight↔loose / passive↔aggressive
axes, plus the four corner personalities. Observations:

- **Distinctiveness is carried almost entirely by the 5 profile floats.**
  Because the exploitation/image/tilt layers are inert (Section 5), what a
  player actually experiences is: how often the bot enters pots, how often it
  raises, and its bluff frequency. That's still enough for the styles to
  *feel* different — TAG vs calling-station vs maniac are visibly distinct in
  play — but "adaptive" styles (Trapper's image-based trapping, exploit-driven
  adjustments) don't actually materialize.
- **`play_range` and the range tables fight each other.** Preflop entry is
  gated by `in_range or score >= threshold - 10` where `threshold =
  (1-play_range)*100` — two overlapping systems (percentile score vs explicit
  combo lists) that disagree at the margins. Post-B4-fix, pick one as primary
  (recommend: score threshold derived from `play_range`, with the combo
  tables reserved for 3-bet/defend decisions).
- **No per-street personality.** All styles use the same postflop shape;
  there is no c-bet frequency, check-raise tendency, river-overbet-bluff
  tendency, or positional aggression parameter. These are the cheapest way to
  make styles feel deeper (see Phase 3).
- **Trapper works** (its `slow_play_freq=0.75` branch is correctly wired,
  engine.py:320-329) and is the only profile using the 5th parameter.

## 7. Difficulty assessment

Current model: one float, three noise injections (score ±30·(1-d), equity
±0.25·(1-d), pot-odds ±0.15·(1-d)) plus two feature gates (Monte-Carlo equity
at d≥0.75 on turn/river; texture-aware bluffing at d≥0.4).

Critique:

1. **Symmetric noise makes bots erratic, not weak.** A very_easy bot
   overfolds exactly as often as it overcalls; over a session its EV loss is
   real but its *behavior* reads as random, not beginner-like. Randomness is
   also inherently hard to exploit — arguably easy bots are *less* readable
   than normal ones, which is backwards for a training game.
2. **Human beginners make *biased* mistakes**: they call too much (never fold
   a pair), overvalue top-pair/any-ace, chase draws without odds, under-bluff,
   bet too small with monsters, ignore position. Difficulty should be a
   **mistake profile**, not a noise amplitude.
3. Monte-Carlo trials are `int(50·d)` — at hard that is 37 trials (±8pp
   standard error), which is itself just noise with extra CPU. Either raise
   trials to ≥200 (it's cheap — the evaluator handles it) or drop MC below
   expert.
4. The web UI exposes easy/normal/hard only; expert (0.9) and perfect (1.0)
   exist but are unreachable in normal play, and `perfect` merely means
   "no noise", not "plays well". Post-fix, hard/expert with working
   exploitation would be meaningfully stronger.

### Proposed difficulty redesign (mistake-based)

Replace noise-only with a per-level `MistakeProfile` applied at decision
points (keep a small residual noise for humanity):

| Level | Overcall bias | Overvalue pairs/aces | Chases bad draws | Position aware | Uses opponent model | Bluffs |
|-------|--------------|----------------------|------------------|----------------|---------------------|--------|
| very_easy | +0.15 equity on calls | yes (+0.10) | always | no | no | random 30% |
| easy | +0.10 | yes (+0.05) | if any outs | no | no | random, texture-blind |
| normal | +0.04 | slight | pot-odds ±0.10 | yes | no | texture-aware |
| hard | 0 | no | correct | yes | yes (after 10 hands) | texture + image |
| expert | 0 | no | correct + implied odds | yes | yes (after 5 hands) | balanced + exploit |

This keeps the single float as an index but makes each level *feel* like a
recognizable player type. Implementation: a small `MistakeProfile` dataclass
consulted in `_decide_preflop`/`_decide_postflop`; the existing `_noisy_*`
helpers stay but with reduced amplitude (e.g. half current values).

---

## 8. Improvement plan (phased, verifiable)

Each phase is independently shippable and ends with a benchmark run
(`core/benchmark.py` all-vs-all, ≥64 tables × 200 hands) plus the test suite.

### Phase 1 — Fix the wiring (highest value, no new features)

1. **Identity**: add the bot's own `player_id`/`name` to `game_state` in
   `_build_game_state` (or set it on the strategy at construction via
   `BotPlayer`). Use it for `_extract_opponent_ids` and self-filtering.
   → verify: unit test that a bot's own actions never appear in its tracker.
2. **Consume structured events, not log strings.** Replace
   `_record_opponent_actions`'s log parsing with consumption of
   `game_state['events']` (they carry player_id, action, street). Keep a
   per-strategy cursor (index of last event seen) so each event is recorded
   exactly once, with its real street.
   → verify: VPIP/PFR/fold_to_bet from a scripted hand match hand-computed
   values; `fold_to_bet` becomes nonzero after postflop folds.
3. **Fix opening detection.** Preflop "unopened" = no voluntary raise yet
   (min_call == big blind and no raiser), not `min_call == 0`. Route unopened
   pots through the opening block with the real position range; keep the
   3-bet logic for genuinely raised pots. Use `player_role` from game_state
   instead of recomputing labels (fixes B8 too).
   → verify: BTN open frequency >> UTG open frequency over 10k simulated
   preflop decisions per archetype.
4. **Record preflop folds** into TableImage (and the tracker's
   `record_missed_opportunity`).
   → verify: a nit's `image.tightness` > 0.7 after 50 hands.
5. **Gutshot span fix** (span == 4 with one missing internal rank; double
   gutshot = two distinct missing-rank candidates).
   → verify: table-driven tests: 5♠6♦7♥ + 9♣x = gutshot; 5-6-8-10 ≠ gutshot;
   J9 on Q-T-x = open-ended… etc.
6. **`was_favorite`**: compute cheap pre-showdown equity for bots that reach
   showdown (one `monte_carlo_equity` call at river, 200 trials) and pass
   `was_favorite = equity > 0.5 and not won`. Gate behind showdown-only so
   cost is negligible.
   → verify: tilt rises after a scripted bad beat.
7. Small correctness items: only add fold equity when considering a bet/raise
   (B12); make `choose_bet_size`/`choose_raise_size` return a single
   `Decision` type instead of mixed tuples (B9).

**Phase 1 implemented 2026-07-12** — per `notes/bot_fix_phase1.md` (Tasks
1–8), full test suite green, benchmark smoke run and manual web-game hands
verified (Task 10). Deviations from this section's sketch:

- **B6 (`was_favorite`)**: implemented as a deterministic hand-strength
  comparison (`HandEvaluator.evaluate` on hole + flop/turn, no river) rather
  than the Monte-Carlo-equity-at-river sketch above — cheaper (one extra
  5-card-combo evaluation per showdown participant, no trials) and sufficient
  to catch the classic "rivered" bad beat, per `bot_fix_phase1.md` Task 6.
- **B9 (bet-sizing return type)**: unified on `Optional[tuple]` — `(BetSize,
  amount)` or `None` for "no bet, caller decides check/fold" — rather than a
  new `Decision` dataclass; smaller diff, same effect (callers now branch on
  `is not None` instead of `isinstance(amt, int)`).
- **B10** (`record_missed_opportunity`): left unwired, as `bot_fix_phase1.md`
  Task 2 explicitly calls out that real per-street `record_action` calls
  already grow the VPIP denominator correctly; wiring the extra method would
  be redundant.

### Phase 2 — Mistake-based difficulty (Section 7 table)

Add `MistakeProfile` per level; keep API/labels unchanged (easy/normal/hard,
plus optionally expose expert in the web settings). Reduce noise amplitudes.
→ verify: benchmark ladder — same archetype at easy vs normal vs hard vs
expert in all-vs-all; expected monotone net-chip ordering with clear gaps
(this is currently *not* guaranteed by noise-only difficulty).

**Phase 2 implemented 2026-07-12** — per `notes/bot_fix_phase2.md` (Tasks
1–8), full test suite green (334 tests), difficulty ladder and archetype
sanity rerun both pass, manual web games at Easy and Expert verified
(Task 10). Deviations from this section's sketch and the spec:

- **Bot_Frank (`players/roster.py`)**: changed to `TightAggressiveStrategy(max(d,
  HARD))` exactly as the spec's Task 8 item 4 literally states, not
  `max(d, HARD) if d >= NORMAL else d`. This means Frank now always plays at
  *at least* HARD even at an Easy/Normal table, not only at Expert — a wider
  behavior change than the "don't downgrade Frank at expert" problem
  statement, but it's what the spec's replacement line says verbatim.
- **Draw-chase cap wording (Task 4)**: implemented literally — the
  half-stack cap on chasing is skipped *only* for `chase_draws == 'always'`
  (very_easy), so a very-easy bot still chases a draw facing a bet of half
  its stack or more, while every other mode respects the cap. The spec's own
  parenthetical ("even beginners hesitate for half their stack") reads as if
  it should apply to `'always'` too, but the preceding sentence explicitly
  carves out `'always'` as the exception, so the literal instruction won.
- **Difficulty-ladder acceptance check**: added as
  `tests/difficulty_ladder_check.py` — a plain script (no `test_` prefix, so
  pytest doesn't collect it), not a slow-marked pytest test, since this repo
  has no marker infrastructure (no `pytest.ini`/`conftest.py`) and one full
  run takes ~7 minutes (200-trial Monte Carlo equity at HARD/EXPERT on every
  turn/river decision, 48 tables x 150 hands x 4 levels). Run manually with
  `python tests/difficulty_ladder_check.py`.
- **Persistent stats (Task 8 item 5)**: `core/stats_persistent.py` already
  mapped an "Expert" label end to end (`_difficulty_to_label`/
  `_label_to_difficulty`); no changes were needed there. The simulation
  form's Expert `<option>` (`web/index.html`) also already existed — only
  the new-game difficulty radio group and the stats-viewer difficulty filter
  needed the addition.
- **Unrelated flaky-test fix**: `test_integration_fold_to_bet_populated`
  (added in Phase 1, `tests/test_enhanced_strategies.py`) relied on the old
  call-gate bug to produce a postflop fold-to-bet with its fixed seed — once
  Task 3 stopped mis-folding profitable calls, that exact 3-identical-Balanced-
  bots/tournament-mode setup no longer reliably reached a genuine bad-odds
  spot within a reasonable hand count (blind-reset tournaments also spend
  long stretches heads-up-or-less between resets). Switched it to a
  Maniac + Nit + Balanced mix in cash mode with rebuys, which reliably forces
  real bad-odds folds — not a Phase 2 behavior change, just a test made
  robust to one.

**Benchmark results recorded 2026-07-12** (see baseline in the Task 10
spec header, `notes/bot_fix_phase2.md`):

Archetype sanity rerun — `run_all_vs_all(num_tables=32, hands_per_table=150,
starting_chips=1000, big_blind=20, difficulty=0.6)`, elapsed 12.3s:

```
TightAggressive +446k | TightPassive +354k | Trapper +332k | Balanced +206k
LooseAggressive +196k | Nit +184k | Maniac -843k | LoosePassive -875k
```

TightAggressive went from **-37k (baseline, bottom half)** to **+446k
(top of the table)** — the Task 3 call-gate fix was the single biggest
lever; TAG's raise-or-fold shape no longer burns its own made hands to a
low `call_freq`. Maniac and LoosePassive losing big is correct poker, not a
regression.

Difficulty ladder — one `BalancedStrategy(level)` vs. three
`BalancedStrategy(NORMAL)`, 48 tables x 150 hands per level, elapsed 424s:

```
EASY +34.7k | NORMAL +115.2k | HARD +389.1k | EXPERT +415.9k
```

Monotone as required, with a wide margin between the extremes (EASY to
EXPERT is a ~381k swing on the same profile) — proof the mistake profiles
cost/save real EV in the intended order.

No `strategies/profile.py` values were tuned; the wide TightAggressive swing
above is entirely a wiring/call-gate effect, not a personality-float change.

### Phase 3 — Style depth (feel, not strength)

Extend `StyleProfile` with per-street parameters (all default to current
behavior so existing profiles are unchanged until tuned):
`cbet_freq`, `check_raise_freq`, `river_bluff_freq`, `positional_awareness`
(0–1 scaling of positional adjustments), `limp_freq`.
Then differentiate: e.g. TAG = high c-bet/low limp; LAG = high river bluffs;
Maniac = high check-raise; Nit = near-zero bluff but *does* value-bet big.
Optionally add 1–2 new archetypes ("Shark" = hard+exploit-forward,
"Gambler" = variance-seeking: chases every draw, min-raises constantly).
→ verify: per-archetype action-frequency fingerprints (VPIP/PFR/c-bet/AF)
from a 10k-hand sim, asserted within target bands in tests.

### Phase 4 — Equity quality

- Preflop: derive equity from `score_starting_hand` (map 0–100 → ~0.30–0.85
  vs one opponent, with multiway scaling) instead of the 0.55/0.32 binary.
- Postflop: raise MC trials (200–300) for hard+, and/or cache per
  (hole, board) within a decision.
- Optional: `equity_vs_range` — weight opponent hands by their observed
  VPIP/PFR instead of uniform random hands (this is where Phase 1's tracker
  starts paying rent). This is the single biggest *strength* upgrade
  available without changing architecture.
→ verify: equity calibration test — bucket MC-estimated equity vs actual
win rate over 50k simulated hands; mean absolute error < 5pp.

---

## 9. Variant options (new implementations)

Considered, with a recommendation. None of these should start before Phase 1
(they'd inherit the same corrupted inputs).

| Option | Idea | Cost | Verdict |
|--------|------|------|---------|
| **A. Range-tracking exploiter** | Keep a weighted hand-range per opponent, narrowed by their actions (preflop range from position + observed VPIP; postflop Bayesian-ish pruning by bet/check). Decisions = equity vs tracked range. | Medium (builds on Phase 4's `equity_vs_range`) | **Recommended** — natural evolution of what exists, produces visible "it's reading me" moments, fully offline. |
| B. Nash push/fold module | Precomputed push/fold charts for ≤15bb stacks (well-known tables). Bolt onto DesignedBot as a short-stack override. | Small | **Recommended as a mini-phase** — cheap, makes endgame/tournament play dramatically more credible, replaces the crude `desperation_factor` shoves. |
| C. Monte-Carlo tree / simulation bot | Simulate action sequences, pick max-EV line. | High (needs opponent action model + performance work) | Defer — big effort, and the benchmark can't currently prove it's more *fun*, only stronger. |
| D. CFR-trained strategy | Offline counterfactual-regret training on an abstracted game. | Very high | Out of scope for this project's goals (fun opponents, not a solver). |
| E. LLM-personality bot | API-driven table talk / decisions. | External dependency, latency, cost | Out of scope; table-talk could be faked locally with templates + events later. |

Suggested sequencing if a variant is wanted: **Phase 1 → Phase 2 → B (push/fold)
→ Phase 4 → A (range exploiter)**, with Phase 3 slotted anywhere for feel.

### 2026-07-13 — Variant B implemented

Implemented per `notes/bot_variant_b_pushfold.md` (Tasks 1-8). Summary:

- New `strategies/push_fold.py`: a combo-weighted `score_cutoff_for_fraction`
  table built from `score_starting_hand`, plus the spec's jam chart
  (`_JAM_FRACTIONS`, stack bands 5/8/12/15bb × UTG/MP/CO/BTN/SB) and call
  chart (`_CALL_FRACTIONS`, same bands × heads-up/players-behind, with a
  ≥2-all-ins override to a flat 0.05). `jam_fraction`/`call_fraction` apply
  the style-aggression tint (`0.9 + 0.2 * aggression`) and the
  `push_fold_skill` jam-tightening/call-widening from Task 3.
- `MistakeProfile.push_fold_skill`: very_easy 0.2, easy 0.4, normal 0.7,
  hard 0.95, expert 1.0, perfect 1.0 — "does this bot know jam-or-fold
  charts exist" as its own difficulty axis, separate from noise/bias.
- Engine hook (`strategies/engine.py:_decide_preflop`) inserted right after
  `_record_opponent_actions`/`unopened`, gated by `use_charts = random() <
  push_fold_skill`: (a) facing a preflop all-in always runs a chart call/fold
  decision if charts are "known" this decision, regardless of the bot's own
  stack depth; (b) own stack ≤15bb and charts known → jam-or-fold (or check
  the free BB option) instead of the old range/score logic. `is_premium`
  (raw score ≥90) short-circuits to call/jam *inside* those branches only —
  it does not force `use_charts` on, so a beginner who "doesn't know the
  charts" can still limp/call AA off a short stack sometimes, per spec.
- Deleted the `des >= 0.7` desperation shove block and the
  `desperation_factor`/`adjust_for_desperation` imports from `engine.py`
  (the functions themselves and their tests in `dynamic_behavior.py` /
  `test_enhanced_strategies.py` are untouched, per the spec's "out of
  scope" list).
- **`players_behind` computation**: used the spec's approximate fallback
  rather than seat-order derivation — `max(0, num_active - 2 -
  len(self._preflop_actors))`, where `_preflop_actors` is a per-hand set of
  opponent names (excluding self) seen acting on the preflop street via the
  structured event log, reset on `hand_started`. Exact seat-order-from-`players_info`
  was avoidable complexity: `players_info` is absolute table order, not
  relative to the acting bot, and the spec explicitly allows this clamp as
  "an acceptable approximation."
- **Known simplification**: charts ignore the ante setting (per spec's
  out-of-scope list) — an ante effectively shortens everyone's stack in bb
  terms without changing pot geometry the same way a bigger blind would, so
  ante tables will jam slightly tighter than a true ante-adjusted chart
  would.
- No deviations from the spec beyond the two notes above.

**Verification gate (Task 8) results:**

- `python -m pytest tests/ -q`: 353 passed (includes the new
  `tests/test_push_fold.py`, 19 tests covering charts, event tracking,
  the difficulty dial, the engine hook's jam/call rates, the BB option,
  the AA-never-folds invariant, and the Task 6 regression tests).
- Full difficulty ladder (`python -m tests.difficulty_ladder_check`, 48
  tables × 150 hands per level, ~402s): monotone —
  EASY −78,780 < NORMAL +29,371 < HARD +338,480 < EXPERT +502,556.
  (Absolute numbers shifted from the pre-Variant-B baseline below, as
  expected — short-stack hands now play differently — but the ordering and
  the EASY↔EXPERT gap both held.)
- All-vs-all rerun @ NORMAL (0.6), 32 tables × 150 hands:

  | Archetype | Baseline (pre-Variant-B) | Post-Variant-B |
  |---|---|---|
  | TightPassive | +456k | **+681,356** |
  | Nit | +117k | **+382,880** |
  | TightAggressive | +654k | **+255,534** |
  | Balanced | +221k | **+231,295** |
  | Trapper | −21k | **+74,842** |
  | LooseAggressive | −350k | **−457,720** |
  | LoosePassive | −367k | **−558,150** |
  | Maniac | −710k | **−610,037** |

  Ordering stays poker-sane (tight/disciplined archetypes — TightPassive,
  Nit, TightAggressive, Balanced — occupy the top half; Maniac,
  LooseAggressive, LoosePassive the bottom), matching the spec's acceptance
  bar. The individual rankings reshuffled (Nit and TightPassive jumped
  above TightAggressive) because short-stack discipline now rewards tight
  ranges more than raw aggression — an expected consequence of replacing
  the old wide desperation shove with real jam/fold ranges, not a
  regression.
- Manual tournament check via `python run_web.py` (tournament mode, 300
  starting chips / 20 big blind = 15bb start, so short-stack play begins
  immediately): at Expert difficulty, `tight_aggressive` correctly jammed
  all-in from the button at exactly 15bb into an unopened pot, and both
  other bots folded appropriately to the shove; the hand resolved cleanly
  with no errors. At Easy difficulty, the same short-stack spot showed both
  sides of the intended split: one hand a `balanced` bot in the small blind
  jammed all-in per the chart, and the next hand a `balanced` bot on the
  button at 16bb called a raise instead of jamming — the legacy
  limp/call leak Easy is supposed to still exhibit per
  `push_fold_skill=0.4`. No errors to hand completion in either table.

---

## 10. Open questions

1. Priority: make bots *feel better* (Phases 2–3) or *play stronger*
   (Phases 1+4, Variant A)? Phase 1 serves both and should go first either way.
2. Should expert difficulty be exposed in the web UI once it actually means
   something?
3. Is tournament credibility (short-stack push/fold, Variant B) important, or
   is the project primarily cash-game oriented?
4. Keep `SimpleStrategy` as the default for bare `BotPlayer()` construction,
   or retire it once DesignedBot is fixed? (It's only a fallback today; the
   roster never uses it.)
