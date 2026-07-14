# Bot AI Fix — Phase 2: Mistake-based difficulty

Implementation spec, self-contained. Follows `notes/bot_fix_phase1.md`
(implemented in commit f9f6a1e). Companion analysis: `notes/bot_ai_assessment.md`
Section 7 — not required reading.

## Context

Bot difficulty today is **symmetric noise**: `DesignedBotStrategy`
(`strategies/engine.py`) perturbs its hand score (±30·(1−d)), equity
(±0.25·(1−d)) and pot odds (±0.15·(1−d)). Two problems:

1. Symmetric noise makes low-difficulty bots *erratic*, not *beginner-like*.
   They overfold as often as they overcall; nothing about their play reads as
   a beginner a human can learn to exploit. Real beginners make **biased**
   mistakes: call too much, overvalue any pair or any ace, chase draws
   without odds, ignore position, under-adapt.
2. There is a style-independent EV leak: the engine gates even **correct
   calls** behind `profile.call_freq` (`engine.py:387-391` postflop,
   `engine.py:201-204` preflop). TightAggressive (call_freq 0.20) folds ~80%
   of its +EV calls and **loses** in benchmarks (baseline below) even though
   it should be the strongest archetype. "Folds winning hands" must become a
   *difficulty mistake*, not a permanent personality tax.

This phase replaces noise-only difficulty with a **mistake profile** per
level, fixes the call gate, and exposes the `expert` level end to end.
**No new archetypes, no profile-float tuning, no new strategy features.**

### Baseline to beat (recorded 2026-07-12, post-Phase-1)

`run_all_vs_all(num_tables=32, hands_per_table=150, starting_chips=1000,
big_blind=20, difficulty=0.6)` — net chips:

```
Trapper +191k | TightPassive +161k | LoosePassive +13k | Balanced -11k
Nit -30k | TightAggressive -37k | LooseAggressive -131k | Maniac -156k
```

The known anomaly is TightAggressive being negative. After this phase it
should rank in the top half at normal difficulty (see Task 10).

## Ground rules

- Surgical changes; match existing style; work tasks in order.
- After each task: run that task's tests, then `python -m pytest tests/ -q`.
- Existing tests that assert the old noise formulas may need updating —
  justified by this spec only.
- Do NOT touch `strategies/profile.py` values, the web client beyond Task 8,
  or anything in the "Out of scope" list.

---

## Task 1 — `MistakeProfile` dataclass and level table

In `strategies/difficulty.py`, add:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class MistakeProfile:
    label: str
    overcall_bias: float    # added to equity ONLY in facing-a-bet call decisions
    overvalue_bias: float   # added to equity when holding any pair or an ace
    chase_draws: str        # 'always' | 'any_outs' | 'sloppy' | 'correct'
    position_aware: bool    # False -> use the 'medium' range for every seat
    opp_model_min_hands: int  # min observed hands before exploit adjustments apply; -1 = never
    bluff_mode: str         # 'random' | 'texture' | 'texture_image'
    score_noise: float      # ± points on the 0-100 preflop score
    equity_noise: float     # ± on postflop equity
    odds_noise: float       # ± on pot odds
```

And the level table (module constant `MISTAKE_PROFILES: Dict[str, MistakeProfile]`):

| label | overcall | overvalue | chase | pos_aware | opp_model | bluff_mode | score_n | equity_n | odds_n |
|-------|---------|-----------|-------|-----------|-----------|------------|---------|----------|--------|
| very_easy | 0.15 | 0.10 | always | False | -1 | random | 15 | 0.12 | 0.08 |
| easy | 0.10 | 0.05 | any_outs | False | -1 | random | 10 | 0.08 | 0.05 |
| normal | 0.04 | 0.02 | sloppy | True | -1 | texture | 6 | 0.05 | 0.03 |
| hard | 0.0 | 0.0 | correct | True | 10 | texture | 3 | 0.03 | 0.02 |
| expert | 0.0 | 0.0 | correct | True | 5 | texture_image | 1 | 0.01 | 0.01 |
| perfect | 0.0 | 0.0 | correct | True | 3 | texture_image | 0 | 0.0 | 0.0 |

Add `def mistakes_for(difficulty: float) -> MistakeProfile` mapping the float
to the nearest level at or below it (0.2→very_easy, 0.4→easy, 0.6→normal,
0.75→hard, 0.9→expert, 1.0→perfect; values in between round down, e.g.
0.7→normal). Keep `DIFFICULTY_LEVELS` and the float constants unchanged.

In `DesignedBotStrategy.__init__`, add
`self.mistakes = mistakes_for(difficulty)`.

**Verify:** unit tests for the float→profile mapping (boundaries 0.2, 0.59,
0.6, 0.74, 0.75, 1.0) and frozen-ness.

---

## Task 2 — Noise comes from the profile

Replace the amplitude formulas in `_noisy_score` / `_noisy_equity` /
`_noisy_odds` (`engine.py:474-490`) with the profile amplitudes:
`self.mistakes.score_noise`, `.equity_noise`, `.odds_noise` (uniform ±,
clamped as now). Keep the `difficulty >= 1.0` early-outs or make them fall
out naturally from the 0.0 amplitudes — implementer's choice, behavior
identical.

**Verify:** update existing noise tests; at perfect, outputs are exact; at
very_easy, equity varies within ±0.12.

---

## Task 3 — Fix the call gate (the TightAggressive leak)

**Postflop** (`engine.py:387-391`). Current:

```python
if equity > odds + exploit['caution_penalty']:
    call_freq = self.profile.call_freq + exploit['equity_boost']
    if random.random() < call_freq:
        return self._make_call(...)
```

Replace with a margin-scaled gate:

```python
margin = equity - (odds + exploit['caution_penalty'])
if margin > 0:
    p_call = self.profile.call_freq + exploit['equity_boost'] + margin * 3.0
    if self.mistakes.overcall_bias == 0.0 and margin >= 0.10:
        p_call = max(p_call, 0.90)      # hard+ never folds clearly winning hands
    if random.random() < min(1.0, p_call):
        return self._make_call(player.chips, min_call)
```

Rationale: `call_freq` still expresses personality at *marginal* spots
(margin ≈ 0), but a clearly profitable call (margin 0.10+) is nearly always
taken at hard+ and strongly favored below. TAG keeps its raise-or-fold feel
without burning made hands.

**Preflop facing a raise** (`engine.py:201-206`). Current gate:
`if random.random() < self.profile.call_freq + exploit['equity_boost']`.
Replace with the same idea using score distance:

```python
score_margin = (raw_score - (threshold - 10)) / 100.0   # how far inside the range
p_call = self.profile.call_freq + exploit['equity_boost'] + score_margin * 1.5
if self.mistakes.overcall_bias == 0.0 and raw_score >= 80:
    p_call = max(p_call, 0.90)
```

`is_premium` hands (raw_score ≥ 90) must never fold here regardless of level
(they already pass the outer `if`; ensure the inner roll cannot fold them —
give them `p_call = 1.0`).

**Verify:** unit test — postflop state with equity 0.60, odds 0.25,
`TightAggressiveStrategy(HARD)`: over 500 trials, call+raise rate ≥ 0.90
(never mostly-fold). Same state at `difficulty=0.4`: call rate noticeably
lower is acceptable, folding dominates only when equity is marginal. Preflop:
AA facing a raise never folds at any difficulty (1,000 trials, all levels).

---

## Task 4 — Overcall, overvalue, and draw-chasing mistakes

All in `_decide_postflop`, applied to a **separate variable** so bet/raise
logic keeps honest numbers where noted:

1. **Overcall bias:** in the Task-3 postflop gate, compute
   `margin = (equity + self.mistakes.overcall_bias) - (odds + ...)`.
   The bias applies **only** to the call comparison — never to
   `bet_equity`, never to value-bet thresholds.
2. **Overvalue bias:** right after `equity` is finalized (`engine.py:295-297`),
   add: if the bot holds any pair or better (`draw.hand_rank >= 2`) **or**
   an ace among its hole cards, `equity = min(1.0, equity +
   self.mistakes.overvalue_bias)`. This one applies to *all* downstream uses
   (a beginner genuinely believes top pair is gold), including `bet_equity`.
3. **Draw chasing:** in the facing-a-bet branch, before the final
   `return PlayerAction.FOLD, 0` (`engine.py:397`), insert:

```python
if is_draw and min_call > 0:
    mode = self.mistakes.chase_draws
    if mode == 'always':
        return self._make_call(player.chips, min_call)
    if mode == 'any_outs' and draw.total_outs >= 4:
        return self._make_call(player.chips, min_call)
    if mode == 'sloppy' and equity + 0.10 > odds:
        return self._make_call(player.chips, min_call)
    # 'correct': fall through to fold
```

Cap the chase: if `min_call >= player.chips // 2`, skip the chase branch at
every mode except 'always' (even beginners hesitate for half their stack).

**Verify:** unit tests per mode — gutshot (4 outs) facing a pot-sized bet:
very_easy calls ~always, easy calls, normal folds unless odds are close,
hard folds. Overvalue: bare ace-high on a dry board at very_easy produces
bets/calls measurably more often than at hard (same seed loop, compare
frequencies).

---

## Task 5 — Position awareness as a difficulty feature

In `_decide_preflop`, where `range_label` is computed (`engine.py:172`):

```python
if self.mistakes.position_aware:
    range_label = position_to_range(self._position, is_opening=unopened)
else:
    range_label = 'medium'
```

(Beginners play the same hands from every seat — this deliberately reproduces
the pre-Phase-1 flattening, now as a *feature* of low levels.)

**Verify:** reuse the Phase-1 BTN-vs-UTG entry-rate test at two levels:
at `HARD`, BTN entry ≥ 1.5× UTG; at `EASY`, the two rates differ by < 15%
relative.

---

## Task 6 — Gate the opponent model by difficulty

`exploit_adjustment` and `opponent_fold_equity` currently apply at every
level with default priors. In both `_decide_preflop` and `_decide_postflop`,
after computing `opponent_ids`:

```python
n = self.mistakes.opp_model_min_hands
modeled_ids = [oid for oid in opponent_ids
               if n >= 0 and self.tracker.has_data(oid, n)]
exploit = self.tracker.exploit_adjustment(modeled_ids)
```

(`exploit_adjustment([])` already returns all-zero adjustments — rely on
that.) Same filtering for `opponent_fold_equity`, and compute
`opp_folds_often` / `opp_calls_often` over `modeled_ids` only.

Effect: very_easy/easy/normal bots never adapt; hard adapts after 10 observed
hands per opponent; expert after 5.

**Verify:** unit test — at `EASY`, after feeding 50 opponent actions, exploit
adjustments are all zero; at `EXPERT` with 6 observed hands they are not.

---

## Task 7 — Bluff mode and Monte-Carlo budget

1. `_should_bluff_v2` (`engine.py:449-470`): replace the
   `self.difficulty < 0.4` check with `self.mistakes.bluff_mode`:
   - `'random'`: current low-difficulty branch (`random() < 0.3`).
   - `'texture'`: current default path (board scary + opponent weak, or
     opp_folds_often) — unchanged.
   - `'texture_image'`: as `'texture'`, plus multiply the final chance by
     `(0.5 + self.image.bluff_success_rate)` — a bot with a tight image
     bluffs more, loose image less. Implement by returning True with that
     probability where `'texture'` would return True.
2. Monte-Carlo trials (`engine.py:288-292`): replace `int(50 * difficulty)`
   with a flat `200` trials, still only when `difficulty >= 0.75` and
   `len(community) >= 4`. (37 noisy trials was ±8pp of pure noise; 200 is
   ±3.5pp and still cheap.)

**Verify:** existing bluff tests updated; benchmark smoke in Task 10 stays
under ~60 s (it was 7.4 s at baseline; MC×5 on turn/river decisions for
hard+ bots is the only cost growth, and the ladder run uses mixed levels).

---

## Task 8 — Expose `expert` end to end

1. `api/schemas.py:14` — `Literal["easy", "normal", "hard", "expert"]`.
2. `api/sessions.py:17,20` — import `EXPERT`; add `"expert": EXPERT` to
   `_DIFFICULTY`.
3. `web/index.html:42-44` — add an `Expert` radio to the new-game difficulty
   group. Check the stats-viewer difficulty filter (`#sv-difficulty`,
   `index.html:101`) and the simulation form select (`index.html:167`) list
   an expert option; add it where missing.
4. `players/roster.py` — Bot_Frank's factory is
   `TightAggressiveStrategy(HARD if d >= NORMAL else d)`, which would
   *downgrade* Frank to HARD at an expert table. Change to
   `TightAggressiveStrategy(max(d, HARD))`. Leave Iris/Jack as-is.
5. Persistent stats: difficulty is stored as a label — confirm an "expert"
   session appears in `/stats` endpoints (grep `core/stats_persistent.py`
   for any hardcoded label list; extend if one exists).

**Verify:** `tests/test_api.py`-style test: creating a session with
`difficulty="expert"` succeeds and bots receive `difficulty == 0.9`
(inspect `session.game.players[i].strategy.difficulty`). Manual: new game in
the web UI shows and accepts Expert.

---

## Task 9 — Docs note

Append a dated "Phase 2 implemented" note under
`notes/bot_ai_assessment.md` Section 8 / Phase 2, listing any deviations
from this spec. Do not rewrite the assessment.

---

## Task 10 — Verification gate

1. `python -m pytest tests/ -q` — all green.
2. **Difficulty ladder** (the core acceptance test — add it as a slow test or
   a script under `tests/`, marked to run manually if too slow for CI):
   for each level in `[EASY, NORMAL, HARD, EXPERT]`, run ≥ 48 tables ×
   150 hands where one `BalancedStrategy(level)` plays against three
   `BalancedStrategy(NORMAL)` opponents (fresh strategies per table; use the
   sweep runner in `core/benchmark.py` if it fits, else a small loop like
   `run_all_vs_all`'s). Record each level's total net.
   **Assert monotone: net(EASY) < net(NORMAL) < net(HARD) < net(EXPERT)**,
   and net(EXPERT) − net(EASY) > 0 by a clear margin. If any adjacent pair
   inverts, increase tables before concluding failure (variance), then
   investigate.
3. **Archetype sanity** — rerun the baseline:
   `run_all_vs_all(num_tables=32, hands_per_table=150, starting_chips=1000,
   big_blind=20, difficulty=0.6)`.
   Expected (investigate if violated, don't hard-assert):
   TightAggressive net > LooseAggressive net and > Maniac net, and TAG in
   the top half. Maniac/LAG still losing overall is correct poker.
   Print the table and include it in the Task 9 note next to the baseline.
4. Manual: `python run_web.py`, one game at Easy and one at Expert, 3–4 hands
   each. Easy bots should feel loose/stationy (calling a lot, chasing);
   Expert bots should fold junk, punish weak bets, and complete hands without
   errors.

## Out of scope (do NOT do these)

- Tuning any value in `strategies/profile.py` (even if the benchmark tempts
  you — record findings in the Task 9 note instead).
- New archetypes, per-street style parameters (Phase 3), preflop equity from
  the score table / `equity_vs_range` (Phase 4), push/fold charts (Variant B).
- Difficulty selection per individual bot in the UI.
- Removing the old float constants or changing `create_bots`' signature.
