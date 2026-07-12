# Bot AI — Variant B: Nash-style push/fold for short stacks

Implementation spec, self-contained. Follows `notes/bot_fix_phase1.md`
(commit f9f6a1e) and `notes/bot_fix_phase2.md` (commit 8d799f1). Companion
analysis: `notes/bot_ai_assessment.md` Section 9 — not required reading.

## Context

Below ~15 big blinds, normal poker strategy stops applying: there is no room
to raise-and-fold or to play streets, and the game collapses to
**jam-or-fold**, which has well-known near-equilibrium ("Nash") solutions.
The bots currently handle this regime with a crude rule
(`strategies/dynamic_behavior.py:desperation_factor` + the shove block at
`strategies/engine.py` in `_decide_preflop`): at ≤10bb, shove any hand with
score > 25, ignoring position and callers. It shoves 93o from UTG and can
fail to shove A9s at 6bb. Calling someone else's shove goes through the
generic call gate, which knows nothing about shove ranges.

This variant adds a **push/fold mode** to `DesignedBotStrategy` — a chart
lookup that activates for *every archetype* when its stack is short (it is a
mode, not a new bot), replaces the desperation shove, and integrates with
Phase 2's difficulty system (experts follow the charts; beginners deviate in
realistic directions or don't know the charts at all).

**Honesty note on "Nash":** the ranges below are standard chart
*approximations* expressed as "top X% of hands", using the existing
`score_starting_hand` table as the hand ordering. True Nash orderings value
suitedness/blockers slightly differently (K2s jams before QJo at 5bb), but
the score-table proxy is consistent with the rest of the codebase and easily
within "credible endgame" tolerance. Do not attempt to solve or import exact
CFR ranges.

## Ground rules

- Surgical changes; match existing style; tasks in order; after each task run
  its tests then `python -m pytest tests/ -q`.
- The Phase 2 acceptance property must survive: the difficulty ladder
  (`python -m tests.difficulty_ladder_check` — run **as a module**, ~7 min)
  must remain monotone at the end (Task 8).
- Do not touch postflop logic, `strategies/profile.py` values, or anything in
  "Out of scope".

### Baseline (recorded 2026-07-12, post-Phase-2)

- Ladder: EASY +2k < NORMAL +103k < HARD +334k < EXPERT +487k (48 tables ×
  150 hands per level).
- All-vs-all @ 0.6, 32 tables × 150 hands: TAG +654k, TP +456k, Bal +221k,
  Nit +117k, Trapper −21k, LAG −350k, LP −367k, Maniac −710k.

---

## Task 1 — `strategies/push_fold.py`: charts and range helper

New module with no imports from `engine.py` (avoid cycles). Contents:

### 1a. Score cutoff for a hand fraction

```python
def score_cutoff_for_fraction(fraction: float) -> int:
    """Score s such that hands scoring >= s make up ~`fraction` of all
    starting hands, weighted by combos (pair=6, suited=4, offsuit=12)."""
```

Build once at import: enumerate the 169 starting-hand classes via
`score_starting_hand` (construct `Card` pairs — one of each rank pair suited
and offsuit, and pocket pairs), weight each class by its combo count
(pairs 6, suited 4, offsuit 12; total 1326), sort by score descending, and
record the cumulative fraction at each distinct score. `score_cutoff_for_fraction`
walks that cached list. Clamp inputs to [0.01, 1.0].

### 1b. Jam chart — unopened pot, % of hands to shove

```python
_JAM_FRACTIONS = {          # stack band (bb) -> {position: fraction}
    5:  {'UTG': 0.25, 'MP': 0.30, 'CO': 0.40, 'BTN': 0.55, 'SB': 0.75},
    8:  {'UTG': 0.18, 'MP': 0.22, 'CO': 0.30, 'BTN': 0.42, 'SB': 0.60},
    12: {'UTG': 0.12, 'MP': 0.15, 'CO': 0.22, 'BTN': 0.32, 'SB': 0.45},
    15: {'UTG': 0.08, 'MP': 0.10, 'CO': 0.15, 'BTN': 0.22, 'SB': 0.32},
}
```

Band selection: smallest key ≥ stack_bb (a 6.5bb stack uses the 8 row; ≤5
uses 5; >15 = mode not active). Unknown positions (e.g. tests passing odd
labels) fall back to 'MP'. 'BB' is handled in Task 4 (option/limp cases),
not by this chart.

### 1c. Call chart — facing a jam, % of hands to call

```python
_CALL_FRACTIONS = {         # jam size band (bb) -> (heads_up, players_behind)
    5:  (0.35, 0.22),
    8:  (0.25, 0.15),
    12: (0.18, 0.11),
    15: (0.13, 0.08),
}
```

`heads_up` applies when nobody is left to act behind the caller;
`players_behind` when at least one player still waits. If **two or more**
all-ins are already in front, override both: call only with the top 0.05.

### 1d. Public API

```python
def jam_fraction(stack_bb: float, position: str, aggression: float) -> float:
    """Chart fraction, tinted by style: fraction * (0.9 + 0.2 * aggression)."""

def call_fraction(jam_bb: float, players_behind: int, num_all_ins: int) -> float

def should_jam(score: int, stack_bb: float, position: str,
               aggression: float) -> bool
    # score >= score_cutoff_for_fraction(jam_fraction(...))

def should_call_jam(score: int, jam_bb: float, players_behind: int,
                    num_all_ins: int, widen: float = 0.0) -> bool
    # widen: added to the fraction (difficulty overcall, Task 3)
```

The style tint keeps personalities visible but subtle (passive ×0.93,
maniac ×1.09). Cap all fractions at 1.0.

**Verify (unit tests, new file `tests/test_push_fold.py`):**
- `score_cutoff_for_fraction` monotone: cutoff(0.05) > cutoff(0.20) >
  cutoff(0.60); cutoff(0.05) ≥ 85; cutoff(1.0) ≤ 5.
- AA (score 100) jams at every stack/position; 72o (score 5) never jams
  above 5bb from UTG.
- Jam range widens with later position and shorter stack: A7o (score 55)
  folds UTG@12bb (top 12% needs ~72+) but jams SB@5bb (top 75%).
- `should_call_jam` tighter with players behind and with 2+ all-ins.

---

## Task 2 — Track preflop all-ins per hand (event flags)

The strategy needs to know, at decision time, whether it faces a preflop
all-in and how many. `_record_opponent_actions` (`engine.py`) already
consumes `action_taken` events with an `all_in` flag and a seq cursor
(Phase 1); `hand_started` events mark hand boundaries.

In `DesignedBotStrategy`:

1. `__init__`: add `self._preflop_all_ins: list = []` (names or ids of
   preflop all-in players this hand) and reset it when the event loop in
   `_record_opponent_actions` encounters a `hand_started` event.
2. In the same event loop, when an `action_taken` event has
   `data.get('all_in')` true, `data['street'] == 'preflop'`, and
   `data['amount'] > 0`, append `(data['name'], data['amount'])`.
3. Helper `self._facing_preflop_jam(big_blind)` → `(num_all_ins,
   largest_jam_bb)` computed from that list; `(0, 0.0)` when empty.

Do not change what gets recorded into the tracker.

**Verify:** unit test — feed a `hand_started` event, two `action_taken`
events (one all-in preflop amount 400, one normal call), then another
`hand_started`; assert the flag list fills and resets correctly across the
two hands.

---

## Task 3 — Difficulty dial: `push_fold_skill`

Extend `MistakeProfile` (`strategies/difficulty.py`) with one field:

```python
push_fold_skill: float   # 1.0 = follows the charts exactly; 0.0 = doesn't know them
```

Values: very_easy 0.2, easy 0.4, normal 0.7, hard 0.95, expert 1.0,
perfect 1.0. (Frozen dataclass — update all six entries and any
constructor-shape tests.)

Semantics, applied in Task 4's engine hook:

- With probability `1 − push_fold_skill`, the bot **ignores push/fold mode
  for this decision** and falls through to the legacy preflop logic — a
  beginner who has never heard of jam-or-fold limps and calls off a short
  stack, which is exactly the leak humans exploit.
- When the charts *are* used: jam fraction is multiplied by
  `1 − 0.3 * (1 − push_fold_skill)` (beginners jam too tight — they "wait
  for a real hand"), and `should_call_jam` gets
  `widen = self.mistakes.overcall_bias` (beginners call jams too loose —
  "I already have chips in").
- The score fed to the charts is the existing `_noisy_score` output, so
  per-level noise wobbles the chart edges for free.

**Verify:** boundary tests for the new field via `mistakes_for`; a
statistical test that at `EASY` a 10bb BTN spot uses legacy logic ≈ 60% of
the time (mockable by counting jam decisions vs a chart-following EXPERT in
the same seeded loop).

---

## Task 4 — Engine hook: push/fold mode in `_decide_preflop`

All changes in `strategies/engine.py`, inserted **after**
`_record_opponent_actions(game_state)` and the `unopened` computation, and
**before** the existing range/score logic. Let
`stack_bb = player.chips / big_blind`.

```
skill = self.mistakes.push_fold_skill
use_charts = random.random() < skill

# (a) Facing a preflop all-in — applies at ANY stack size (calling a jam
#     is a chart decision even for a big stack; risk is capped by the jam).
num_jams, jam_bb = self._facing_preflop_jam(big_blind)
if num_jams > 0 and min_call > 0 and use_charts:
    players_behind = <count of active players still to act after us — see note>
    if should_call_jam(score, min(jam_bb, stack_bb), players_behind,
                       num_jams, widen=self.mistakes.overcall_bias):
        return self._make_call(player.chips, min_call)
    self.image.record_preflop_fold()
    return PlayerAction.FOLD, 0

# (b) Short-stack jam-or-fold — own stack <= 15bb.
if stack_bb <= 15 and use_charts:
    if self._position == 'BB' and min_call == 0:
        pass          # BB option: fall through to normal logic (check is free)
    elif unopened:
        if should_jam(score, stack_bb, self._position, self.profile.aggression):
            self.image.record_raise()
            return PlayerAction.ALL_IN, player.chips
        if min_call == 0:
            return PlayerAction.CHECK, 0
        self.image.record_preflop_fold()
        return PlayerAction.FOLD, 0
    else:
        # Facing a normal (non-all-in) raise while short: jam or fold.
        # Jamming over a raise ~ the tightness of a calling range.
        if should_call_jam(score, stack_bb, 0, 0):
            self.image.record_raise()
            return PlayerAction.ALL_IN, player.chips
        self.image.record_preflop_fold()
        return PlayerAction.FOLD, 0
```

Notes:

- `score` here is the noisy score already computed in `_decide_preflop`
  (move its computation above the hook if needed).
- **players_behind:** derive from `players_info` (list of
  `(name, chips, is_active)` in seat order) — count active players other
  than self who appear **after** the bot in action order. If that's awkward
  to compute exactly from the available fields, `num_active − 2 − <players
  who already acted this street per the event list>` clamped to ≥0 is an
  acceptable approximation; note the choice in the Task 7 doc note.
- Premium override: `is_premium` hands (raw score ≥ 90) must never be folded
  by chart wobble in branches (a)/(b) — short-circuit them to call/jam.
- When `use_charts` is False, execution falls through to the existing logic
  untouched (that *is* the beginner mistake).

**Delete the desperation shove:** remove the
`des = desperation_factor(...)` block (the `des >= 0.7` shove) from
`_decide_preflop`, and remove `desperation_factor` (and the long-dead
`adjust_for_desperation`) from `engine.py`'s import list — this change makes
them unused there. Leave `strategies/dynamic_behavior.py` itself untouched
(its functions keep their unit tests).

**Verify:**
- Seeded loop: `BalancedStrategy(PERFECT)` at 8bb BTN, unopened, 2,000
  decisions with random hole cards → jam rate within ±8pp of the charted
  `0.42 × (0.9 + 0.2·0.5) = 0.42` (style tint for aggression 0.5 = ×1.0).
- Same at 8bb UTG → jam rate ≈ 0.18; BTN rate > UTG rate (position lives).
- Facing a 10bb jam heads-up at PERFECT: 72o always folds, AA always calls,
  and overall call rate ≈ 0.18.
- BB with `min_call == 0` at 6bb still checks its option with junk (never
  auto-jams the free option with 72o... unless the jam branch was skipped —
  assert CHECK happens with score-5 hands).
- AA is never folded preflop at any stack/difficulty (extend the existing
  Phase-2 premium test to a 5bb stack).

---

## Task 5 — Legacy interactions

1. `main.py` / `core/benchmark.py`: no changes needed (they only construct
   strategies), but confirm by grep that nothing else calls
   `desperation_factor` besides `dynamic_behavior` tests.
2. The web client needs no changes — ALL_IN preflop actions already render.
3. `strategies/__init__.py` re-exports: add `should_jam`, `should_call_jam`,
   `score_cutoff_for_fraction` to the convenience re-export block.

---

## Task 6 — Style/difficulty regression tests

Add to `tests/test_push_fold.py`:

- **Ladder still monotone (fast proxy):** the full ladder script is ~7 min;
  add a *reduced* pytest-marked-slow variant (12 tables × 100 hands) that
  asserts EASY < HARD net for the Balanced subject — a smoke canary, with
  the full script remaining the real gate (Task 8).
- **Maniac vs Nit tint:** at PERFECT, 8bb CO over 2,000 hands, Maniac's jam
  rate > Nit's jam rate (aggression tint).
- **No regression at deep stacks:** a 60bb bot's preflop decisions are
  byte-identical in distribution to pre-change behavior (seeded comparison:
  the push/fold hook must not fire above 15bb except branch (a), and branch
  (a) only fires when an actual all-in occurred).

---

## Task 7 — Docs note

Append a dated "Variant B implemented" note under
`notes/bot_ai_assessment.md` Section 9 (the variant table), recording: chart
fractions used, the `players_behind` computation chosen, and any deviation
from this spec.

---

## Task 8 — Verification gate

1. `python -m pytest tests/ -q` — all green.
2. **Full difficulty ladder** — `python -m tests.difficulty_ladder_check`
   (module form!). Must stay monotone EASY < NORMAL < HARD < EXPERT. Expect
   the absolute numbers to shift (short-stack hands now play differently);
   monotonicity is the requirement, not the old values.
3. **All-vs-all rerun** @ 0.6, 32 tables × 150 hands (same call as the
   baseline above). Expected: ordering stays poker-sane (TAG/TightPassive
   top half; Maniac/LAG/LoosePassive bottom). Include the table in the
   Task 7 note next to the baseline.
4. **Tournament manual check:** `python run_web.py`, start a *tournament*
   mode game (blinds escalate), play until stacks get short (or set small
   starting chips, e.g. 300 at 10/20). Confirm: short bots jam-or-fold
   rather than limp-call, an Expert table's short-stack play looks
   disciplined, and an Easy table still shows limpy/cally short-stack leaks.
   No errors to hand completion.

## Out of scope (do NOT do these)

- Exact Nash/CFR range solving or importing external chart files.
- Any postflop change; any change to `strategies/profile.py` floats.
- Re-raising ("resteal") jam logic over an opener deeper than 15bb.
- Ante-adjusted charts (the ante setting exists; charts ignore it — note it
  as a known simplification in the Task 7 note).
- New archetypes, UI changes, per-bot difficulty.
- Deleting `desperation_factor`/`adjust_for_desperation` from
  `dynamic_behavior.py` (only their `engine.py` imports go).
