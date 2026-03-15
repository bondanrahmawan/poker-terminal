"""
Shared helpers for bot strategies.
Import these in any strategy — do not duplicate them.
"""
from typing import List
from core.card import Card
from core.evaluator import HandEvaluator

# Estimated equity per hand rank (index = HandRank value 0..9)
# 0 = unset, 1 = High Card, ..., 9 = Straight Flush / Royal Flush
_EQUITY_BY_RANK = [0.0, 0.25, 0.42, 0.57, 0.67, 0.76, 0.84, 0.91, 0.96, 0.99]


def estimate_equity(hole_cards: List[Card], community_cards: List[Card]) -> float:
    """
    Returns a rough win-probability estimate (0.0–1.0).
    Pre-flop uses a rank-based heuristic; post-flop uses HandEvaluator.
    """
    if len(community_cards) == 0:
        ranks = [c.rank for c in hole_cards]
        is_strong = max(ranks) > 10 or abs(ranks[0] - ranks[1]) <= 1
        return 0.55 if is_strong else 0.32
    score, _ = HandEvaluator.evaluate(hole_cards, community_cards)
    rank = score[0] if score else 0
    return _EQUITY_BY_RANK[min(rank, 9)]


def pot_odds(min_call: int, pot_size: int) -> float:
    """
    Returns the fraction of the total pot the caller must invest.
    e.g. pot=300, call=100 -> 100/400 = 0.25 (need >25% equity to break even).
    """
    total = pot_size + min_call
    return min_call / total if total > 0 else 0.0


def position_adjustment(position: int, num_active: int) -> float:
    """
    Returns an equity-threshold adjustment based on seat position.
    Negative = play looser (lower threshold), Positive = play tighter.

    position 0  = dealer / button  → best post-flop position → loosen (-0.08)
    position 1  = SB               → worst post-flop position → tighten (+0.06)
    position 2  = BB               → marginally tight         → (+0.06)
    near button = cut-off area     → slightly loose           → (-0.04)
    """
    if num_active <= 2:
        return 0.0
    if position == 0:
        return -0.08
    elif position <= 2:
        return +0.06
    elif position / num_active >= 0.75:
        return -0.04
    return 0.0


def calc_raise_amount(pot_size: int, min_call: int, min_raise: int,
                      chips: int, fraction: float) -> int:
    """
    Returns a pot-proportional raise amount capped at player's stack.
    fraction: 0.5 = half-pot raise, 1.0 = full-pot raise.
    Always at least min_raise + min_call.
    """
    raw = int(pot_size * fraction) + min_call
    raw = max(raw, min_raise + min_call)
    return min(chips, raw)
