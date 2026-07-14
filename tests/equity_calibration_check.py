"""
Phase 4 Task 6 acceptance check — equity calibration (the correctness gate).

Not a pytest test (no test_ prefix): ~50k full runouts take a couple of
minutes. Run manually:

    python -m tests.equity_calibration_check

Simulates random spots (random hole cards + 0/3/4 community cards, 1-3
opponents). For each spot it records advanced_equity()'s estimate and the
result of ONE full all-in runout against random opponents (win=1, tie=0.5).
Bucketed by estimated-equity decile, the bucket-mean actual win rate should
match the bucket-mean estimate. Gate: mean absolute error across populated
buckets < 0.05 (5pp), and no single decile bucket off by > 0.10.

advanced_equity() is the heuristic estimator this phase touches (its preflop
branch now maps from the 0-100 score table). HARD+ bots use monte_carlo_equity
on turn/river instead; this gate holds the heuristic itself to account.
"""
import random
import time

from core.card import Card, Suit, Rank
from core.evaluator import HandEvaluator
from strategies.draw_detection import advanced_equity

_FULL_DECK = [Card(r, s) for s in Suit.get_all() for r in Rank.get_all()]


def _one_spot(rng) -> tuple:
    """Deal one random spot; return (estimated_equity, actual_runout_result)."""
    deck = _FULL_DECK[:]
    rng.shuffle(deck)
    idx = 0
    hole = deck[idx:idx + 2]
    idx += 2
    num_community = rng.choice([0, 3, 4])
    num_opponents = rng.choice([1, 2, 3])
    community = deck[idx:idx + num_community]
    idx += num_community

    est = advanced_equity(hole, community, num_opponents)

    opps = []
    for _ in range(num_opponents):
        opps.append(deck[idx:idx + 2])
        idx += 2
    board = community + deck[idx:idx + (5 - num_community)]

    hero, _ = HandEvaluator.evaluate(hole, board)
    best_opp = None
    for opp in opps:
        sc, _ = HandEvaluator.evaluate(opp, board)
        if best_opp is None or sc > best_opp:
            best_opp = sc
    if hero > best_opp:
        actual = 1.0
    elif hero == best_opp:
        actual = 0.5
    else:
        actual = 0.0
    return est, actual


def calibrate(num_trials=50000, seed=1234):
    """Return 10 decile buckets: each dict(n, est_sum, act_sum)."""
    rng = random.Random(seed)
    buckets = [dict(n=0, est=0.0, act=0.0) for _ in range(10)]
    for _ in range(num_trials):
        est, actual = _one_spot(rng)
        b = min(9, int(est * 10))
        buckets[b]['n'] += 1
        buckets[b]['est'] += est
        buckets[b]['act'] += actual
    return buckets


def report(buckets):
    """Print the calibration table; return (mae, worst_bucket_error)."""
    print("decile     n       est    actual   |err|")
    errors = []
    for i, b in enumerate(buckets):
        if b['n'] == 0:
            continue
        est = b['est'] / b['n']
        act = b['act'] / b['n']
        err = abs(est - act)
        errors.append(err)
        print(f"{i / 10:.1f}-{(i + 1) / 10:.1f}  {b['n']:7d}  {est:.3f}   {act:.3f}   {err:.3f}")
    mae = sum(errors) / len(errors)
    worst = max(errors)
    return mae, worst


def main():
    t0 = time.time()
    buckets = calibrate(50000)
    mae, worst = report(buckets)
    print(f"MAE={mae:.4f}  worst-bucket={worst:.4f}  elapsed {time.time() - t0:.1f}s")
    assert mae < 0.05, f"calibration MAE {mae:.4f} exceeds 0.05"
    assert worst < 0.10, f"a decile bucket off by {worst:.4f} > 0.10"
    print("OK: equity calibrated within tolerance")


if __name__ == "__main__":
    main()
