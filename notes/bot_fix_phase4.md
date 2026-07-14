# Bot AI Fix — Phase 4: Equity quality (and a real Expert edge)

Implementation spec, self-contained. Follows Phase 1 (f9f6a1e), Phase 2
(8d799f1), Variant B (6ec5712). Companion analysis: `notes/bot_ai_assessment.md`
Section 8 / Phase 4 — not required reading.

## Context

Two of the bot's equity inputs are crude, and one difficulty finding is
unresolved. This phase fixes all three together.

1. **Preflop equity is binary.** `advanced_equity`
   (`strategies/draw_detection.py:240-244`) and `estimate_equity`
   (`strategies/utils.py:22-25`) both return **0.55** for "strong" hands and
   **0.32** for everything else. AA and 66 are identical; so are AKs and QJo.
   The codebase already owns a 0–100 hand-strength table
   (`strategies/hand_score.py:score_starting_hand`, AA=100 … 72o=5) used for
   play/fold decisions but **not** for equity. Preflop sizing and calling run
   on a two-value guess.

2. **`equity_vs_range` is dead.** `draw_detection.py:284` computes equity
   against a *theoretical opponent looseness* and is **never called by any
   code**. Post-Phase-1 the opponent tracker produces real VPIP per opponent,
   so we can finally feed it observed looseness instead of assuming random
   opponents.

3. **Hard ≈ Expert (verification finding, 2026-07-13).** Six Hard-vs-Expert
   comparisons on current code: two favored Hard, three favored Expert, and
   the most sensitive test (128 shared-card tables, same opponents) was a
   dead tie (493.5k vs 487.9k). The two levels share **zero** mistake biases
   and differ only in soft dials — so they are the same strength, and the
   ladder script's strict `HARD < EXPERT` assertion tests a difference that
   doesn't exist. This phase gives Expert a **real** edge — range-aware
   equity, gated to expert/perfect only — so the top rung becomes a genuine
   skill gap rather than a hoped-for accident.

**Scope discipline:** preflop equity from the score table + wiring
`equity_vs_range`, both behind the existing architecture. No new archetypes,
no postflop *logic* changes, no profile-float tuning, no MCTS/CFR.

### Baselines (post-Variant-B, 2026-07-13)

- Ladder rungs, separate tables: EASY < NORMAL < HARD are cleanly separated
  with huge gaps; HARD vs EXPERT is within noise (see finding 3).
- All-vs-all @ 0.6, 32 tables × 150 hands: TAG +553k, TP +386k, Trapper
  +312k, Nit +222k, Balanced −6k, LAG −246k, LP −517k, Maniac −703k.

## Ground rules

- Surgical; match style; tasks in order; after each task run its tests then
  `python -m pytest tests/ -q`.
- SimpleStrategy is test-only but shares `estimate_equity`/`advanced_equity`;
  improving preflop equity will shift some SimpleStrategy test expectations —
  update those tests to the new values (they assert the old 0.55/0.32
  constants), justified by this spec.
- Ladder script (`tests/difficulty_ladder_check.py`) is amended in Task 1 and
  re-tightened in Task 7.

---

## Task 1 — Amend the ladder gate to reflect measured reality (do first)

The strict `HARD < EXPERT` assertion currently fails on variance because the
two levels are presently co-equal (finding 3). Before Phase 4 makes them
differ, fix the instrument so there is a working gate to develop against.

In `tests/difficulty_ladder_check.py`:

1. Keep the separate-table ladder, but change the assertion to
   `EASY < NORMAL < HARD` (strict) and `EXPERT >= HARD - TOL` where
   `TOL = 0.15 * abs(HARD_net)` — i.e. Expert must not be *materially* worse
   than Hard. Document in the module docstring that Hard/Expert are
   statistically co-equal pre-Phase-4 and that Task 7 tightens this once
   range-aware equity lands.
2. Add a `head_to_head(level_a, level_b, num_tables=128)` helper that seats
   one bot of each level plus two `NORMAL` fillers at the **same** table
   (alternating seat order by table index to cancel positional bias) and
   returns `(net_a, net_b)`. This is the sensitive instrument the diagnosis
   used; Task 7 will assert Expert beats Hard head-to-head by a real margin.

**Verify:** `python -m tests.difficulty_ladder_check` passes on the current
(pre-Phase-4) code. (It won't assert an Expert edge yet — that's Task 7.)

---

## Task 2 — Preflop equity from the score table

New function in `strategies/draw_detection.py` (it may import
`score_starting_hand` — `hand_score.py` only depends on `core.card`, no cycle):

```python
from strategies.hand_score import score_starting_hand

def preflop_equity(hole_cards, num_opponents: int = 1) -> float:
    """Heads-up equity mapped from the 0-100 starting-hand score, then
    scaled for multiway pots (independent-opponent approximation)."""
    score = score_starting_hand(hole_cards[0], hole_cards[1])
    hu = 0.35 + 0.50 * (score / 100.0)      # AA(100)->0.85, 72o(5)->0.375
    return max(0.0, min(1.0, hu ** max(1, num_opponents)))
```

Replace the binary preflop branch in **both**:
- `advanced_equity` (`draw_detection.py:240-244`) → `return preflop_equity(hole_cards, num_opponents)`
- `estimate_equity` (`utils.py:22-25`) → same (import from draw_detection).

**Known caveat to watch:** the score table ranks *playability*, so it
somewhat overvalues big offsuit broadways (AKo scores 90 but is ~65% vs a
random hand). The linear map is a starting point; the calibration test
(Task 6) is the gate that forces tuning the constants (a mild concave curve
or a pair/offsuit correction is acceptable if MAE demands it). Do not ship
without Task 6 passing.

**Verify:** unit tests — `preflop_equity` is monotone in score (AA > KK >
AKs > QJo > 72o); heads-up AA in [0.82, 0.88]; 72o in [0.33, 0.42]; 3-opponent
AA < heads-up AA and > 0.55.

---

## Task 3 — `range_aware_equity` difficulty flag

Extend `MistakeProfile` (`strategies/difficulty.py`) with one field:

```python
range_aware_equity: bool   # discount equity by observed opponent looseness
```

Values: `True` for `expert` and `perfect`, `False` for all lower levels.
(Frozen dataclass — update all six entries and any constructor-shape tests.)

This is the mechanism that gives Expert its real edge: only expert/perfect
adjust their equity for *who* is betting.

**Verify:** boundary test — `mistakes_for(EXPERT).range_aware_equity is True`,
`mistakes_for(HARD).range_aware_equity is False`.

---

## Task 4 — Wire `equity_vs_range` into postflop, gated

In `_decide_postflop` (`strategies/engine.py`), where `raw_equity` is
computed (currently the `monte_carlo_equity` / `advanced_equity` branch
around engine.py:287-294):

After `raw_equity` is obtained, if `self.mistakes.range_aware_equity` **and**
there is at least one modeled opponent with tracker data, replace the flat
equity with a range-discounted version:

```python
if self.mistakes.range_aware_equity and modeled_ids:
    # Weight by the tightest bettor we can see: a tight opponent's bet
    # discounts our equity more than a station's.
    ranges = [self.tracker.get_stats(oid).vpip for oid in modeled_ids]
    opp_range = max(0.10, min(0.90, min(ranges)))   # tightest = smallest vpip
    raw_equity = equity_vs_range(
        player.hole_cards, community, opponent_range=opp_range,
        num_opponents=num_active - 1,
    )
```

`modeled_ids` already exists in `_decide_postflop` (Phase 2, difficulty-gated
opponent list). `equity_vs_range` is already imported? — if not, add it to
the `strategies/__init__.py` re-export block and the engine import. Note that
`equity_vs_range` internally calls `advanced_equity`, which now uses the
Task-2 preflop mapping — consistent.

Leave all downstream logic (`equity`, `bet_equity`, thresholds) unchanged;
only the *source* number improves.

**Verify:** unit test — same hand/board, a bot facing a modeled tight
opponent (vpip 0.15) has strictly lower `raw_equity` than facing a modeled
loose opponent (vpip 0.75); a HARD bot (flag False) ignores both and returns
the flat equity.

---

## Task 5 (optional stretch) — Range-weighted Monte Carlo

Only if Task 6's calibration wants it. `monte_carlo_equity`
(`draw_detection.py`) deals opponents uniformly random hands. Add an optional
`opp_range: float = 1.0` param: when < 1.0, reject-sample opponent hands whose
`score_starting_hand` is below `score_cutoff_for_fraction(opp_range)` (reuse
the Variant B helper from `strategies/push_fold.py`), so a tight range deals
stronger opponent hands. Wire it into the Task-4 expert path for turn/river
only. **Skip this task if Task 6 already passes** — it adds cost and
complexity for marginal gain.

**Verify:** if implemented — tighter `opp_range` lowers estimated equity for a
medium hand; calibration MAE improves or holds.

---

## Task 6 — Equity calibration test (the correctness gate)

New `tests/equity_calibration_check.py` (script, not `test_`-prefixed — it's
slow; mirror `difficulty_ladder_check.py`'s "run as module" pattern):

- Simulate ≥ 50,000 random spots (random hole cards + 0/3/4 community cards,
  1–3 opponents). For each, record the estimated equity (the function under
  test) and the actual result of a full all-in runout against random
  opponents (or range-restricted for the range-aware variant).
- Bucket by estimated-equity decile; assert **mean absolute error between
  bucket-mean estimate and bucket actual win rate < 0.05 (5pp)** across all
  buckets, and no single bucket off by > 0.10.
- Print the calibration table (estimate vs actual per decile) for eyeballing.

If preflop or postflop buckets exceed tolerance, tune Task 2's mapping /
Task 4's discount (that is the intended loop). Document final constants in
the Task 8 note.

**Verify:** `python -m tests.equity_calibration_check` prints the table and
passes the MAE gate.

---

## Task 7 — Re-tighten the ladder; prove the Expert edge

Now that expert has range-aware equity, restore a real top-rung gate.

In `tests/difficulty_ladder_check.py` `main()`: after the separate-table
ladder, run `head_to_head(EXPERT, HARD, num_tables=128)` and assert
`net(EXPERT) > net(HARD)` by a margin exceeding the noise band (require
`net_expert - net_hard > 0.05 * abs(net_hard)` — a real, not incidental,
edge). Keep the separate-table `EASY < NORMAL < HARD` assertions.

**Verify:** `python -m tests.difficulty_ladder_check` — Easy<Normal<Hard
strict, and Expert beats Hard head-to-head by > 5%. If the margin is
positive but under 5%, Phase 4's discount may be too weak; revisit Task 4's
`opp_range` aggressiveness (or enable Task 5) before concluding.

---

## Task 8 — Docs note + final gate

1. Append a dated "Phase 4 implemented" note under
   `notes/bot_ai_assessment.md` Phase 4, recording: the final preflop-equity
   mapping constants, calibration MAE achieved, whether Task 5 was needed,
   and the measured Expert-over-Hard head-to-head margin.
2. Final gate:
   - `python -m pytest tests/ -q` — all green.
   - `python -m tests.equity_calibration_check` — MAE gate passes.
   - `python -m tests.difficulty_ladder_check` — Easy<Normal<Hard and
     Expert > Hard head-to-head by the required margin.
   - All-vs-all @ 0.6, 32 tables × 150 hands — ordering still poker-sane
     (TAG/TP top; Maniac/LAG/LP bottom); record next to the baseline.
   - Manual: `python run_web.py`, one Expert game — bots should fold weak
     aces preflop (no more binary overvaluation) and give up cheaply when a
     tight opponent shows aggression. Complete hands without errors.

## Out of scope (do NOT do these)

- Tuning `strategies/profile.py` values.
- Per-street style params (Phase 3), range-tracking per-hand (Variant A),
  push/fold chart changes (Variant B).
- Any postflop decision-flow change beyond swapping the equity source.
- Removing SimpleStrategy or the old binary helpers' call sites elsewhere.
- New UI, new archetypes, per-bot difficulty.
