"""
Position-aware preflop ranges for smarter bot play.

Provides:
  - Opening ranges by position (UTG, MP, CO, BTN, SB)
  - 3-betting ranges vs raises
  - Fold/call/raise decisions based on position and action history
"""
from __future__ import annotations
from typing import Dict, Set, Tuple
from core.card import Card


# ── Position labels ──────────────────────────────────────────────────────────

UTG = 'UTG'       # Under the gun (first to act, tightest)
UTG1 = 'UTG1'
MP = 'MP'         # Middle position
HJ = 'HJ'         # Hijack
CO = 'CO'         # Cutoff
BTN = 'BTN'       # Button (widest range)
SB = 'SB'         # Small blind
BB = 'BB'         # Big blind

# Position order (early → late)
POSITION_ORDER = [UTG, UTG1, MP, HJ, CO, BTN, SB, BB]


# ── Opening ranges (% of hands) ──────────────────────────────────────────────
# Based on standard 6-max / full-ring opening ranges.
# Each range is a list of hand types: pairs, suited, offsuit.

_OPENING_RANGES = {
    # Tight — 15% of hands (UTG full-ring)
    'tight': {
        'pairs': list(range(7, 15)),       # 77+
        'suited': [                         # A2s+, K9s+, Q9s+, J9s+, T8s+, 97s+, 86s+, 75s+, 64s+, 53s+
            (14, 2), (14, 3), (14, 4), (14, 5), (14, 6), (14, 7), (14, 8), (14, 9),
            (14, 10), (14, 11), (14, 12), (14, 13),
            (13, 9), (13, 10), (13, 11), (13, 12),
            (12, 9), (12, 10), (12, 11),
            (11, 9), (11, 10),
            (10, 8), (10, 9),
            (9, 7), (9, 8),
            (8, 6), (8, 7),
            (7, 5), (7, 6),
            (6, 4), (6, 5),
            (5, 3), (5, 4),
        ],
        'offsuit': [                        # ATo+, KQo
            (14, 10), (14, 11), (14, 12), (14, 13),
            (13, 12),
        ],
    },
    # Medium — 22% of hands (MP/HJ)
    'medium': {
        'pairs': list(range(5, 15)),       # 55+
        'suited': [
            (14, 2), (14, 3), (14, 4), (14, 5), (14, 6), (14, 7), (14, 8), (14, 9),
            (14, 10), (14, 11), (14, 12), (14, 13),
            (13, 7), (13, 8), (13, 9), (13, 10), (13, 11), (13, 12),
            (12, 8), (12, 9), (12, 10), (12, 11),
            (11, 8), (11, 9), (11, 10),
            (10, 7), (10, 8), (10, 9),
            (9, 6), (9, 7), (9, 8),
            (8, 5), (8, 6), (8, 7),
            (7, 4), (7, 5), (7, 6),
            (6, 3), (6, 4), (6, 5),
            (5, 2), (5, 3), (5, 4),
            (4, 2), (4, 3),
            (3, 2),
        ],
        'offsuit': [
            (14, 8), (14, 9), (14, 10), (14, 11), (14, 12), (14, 13),
            (13, 10), (13, 11), (13, 12),
            (12, 10), (12, 11),
            (11, 10),
        ],
    },
    # Wide — 35% of hands (CO)
    'wide': {
        'pairs': list(range(2, 15)),       # 22+
        'suited': [
            (14, 2), (14, 3), (14, 4), (14, 5), (14, 6), (14, 7), (14, 8), (14, 9),
            (14, 10), (14, 11), (14, 12), (14, 13),
            (13, 5), (13, 6), (13, 7), (13, 8), (13, 9), (13, 10), (13, 11), (13, 12),
            (12, 6), (12, 7), (12, 8), (12, 9), (12, 10), (12, 11),
            (11, 6), (11, 7), (11, 8), (11, 9), (11, 10),
            (10, 5), (10, 6), (10, 7), (10, 8), (10, 9),
            (9, 5), (9, 6), (9, 7), (9, 8),
            (8, 4), (8, 5), (8, 6), (8, 7),
            (7, 3), (7, 4), (7, 5), (7, 6),
            (6, 2), (6, 3), (6, 4), (6, 5),
            (5, 2), (5, 3), (5, 4),
            (4, 2), (4, 3),
            (3, 2),
        ],
        'offsuit': [
            (14, 5), (14, 6), (14, 7), (14, 8), (14, 9), (14, 10), (14, 11), (14, 12), (14, 13),
            (13, 8), (13, 9), (13, 10), (13, 11), (13, 12),
            (12, 8), (12, 9), (12, 10), (12, 11),
            (11, 9), (11, 10),
            (10, 9),
        ],
    },
    # Very wide — 50% of hands (BTN)
    'very_wide': {
        'pairs': list(range(2, 15)),
        'suited': 'almost_all',  # all suited except worst 10%
        'offsuit': [
            (14, 2), (14, 3), (14, 4), (14, 5), (14, 6), (14, 7), (14, 8), (14, 9),
            (14, 10), (14, 11), (14, 12), (14, 13),
            (13, 9), (13, 10), (13, 11), (13, 12),
            (12, 9), (12, 10), (12, 11),
            (11, 9), (11, 10),
            (10, 9),
        ],
    },
    # SB completion — 40% of hands
    'sb_wide': {
        'pairs': list(range(2, 15)),
        'suited': 'almost_all',
        'offsuit': [
            (14, 5), (14, 6), (14, 7), (14, 8), (14, 9), (14, 10), (14, 11), (14, 12), (14, 13),
            (13, 10), (13, 11), (13, 12),
            (12, 10), (12, 11),
            (11, 10),
        ],
    },
}


# ── 3-bet ranges (vs a raise) ────────────────────────────────────────────────

_THREE_BET_RANGES = {
    'tight': {
        'value': [
            (14, 14), (13, 13), (12, 12),  # JJ+
            (14, 13, True), (14, 12, True),  # AKs, AQs
        ],
        'bluff': [
            (14, 5, True), (14, 4, True),  # A5s, A4s (blocker to Aces)
            (5, 4, True), (4, 3, True),     # 54s, 43s (connected suited)
        ],
    },
    'medium': {
        'value': [
            (14, 14), (13, 13), (12, 12), (11, 11),  # JJ+
            (14, 13, True), (14, 12, True), (14, 11, True),  # AKs, AQs, AJs
            (14, 13, False),  # AKo
        ],
        'bluff': [
            (14, 5, True), (14, 4, True), (14, 3, True),
            (5, 4, True), (4, 3, True), (6, 5, True),
            (13, 12, True),  # KQs as semi-bluff
        ],
    },
    'wide': {
        'value': [
            (14, 14), (13, 13), (12, 12), (11, 11), (10, 10),
            (14, 13, True), (14, 12, True), (14, 11, True), (14, 10, True),
            (14, 13, False), (14, 12, False),
        ],
        'bluff': [
            (14, x, True) for x in range(2, 7)
        ] + [
            (x, y, True) for x in range(5, 9) for y in range(x-3, x) if y >= 2
        ],
    },
}


def position_to_range(position: str, is_opening: bool = True) -> str:
    """Map a position to a range label."""
    if not is_opening:
        return 'medium'  # default for facing raises
    mapping = {
        UTG: 'tight',
        UTG1: 'tight',
        MP: 'medium',
        HJ: 'medium',
        CO: 'wide',
        BTN: 'very_wide',
        SB: 'sb_wide',
        BB: 'medium',  # BB doesn't open (already posted), but defends wide
    }
    return mapping.get(position, 'medium')


def hand_in_range(card1: Card, card2: Card, range_label: str) -> bool:
    """Check if a starting hand is in the given opening range."""
    if range_label not in _OPENING_RANGES:
        return False

    rng = _OPENING_RANGES[range_label]
    r1, r2 = card1.rank, card2.rank
    high, low = max(r1, r2), min(r1, r2)
    suited = card1.suit == card2.suit

    # Pocket pairs
    if r1 == r2:
        return r1 in rng['pairs']

    # Suited hands
    if suited:
        if rng['suited'] == 'almost_all':
            # Accept all suited except 72, 82, 73, 83, 92
            bad_hands = {(7, 2), (8, 2), (7, 3), (8, 3), (9, 2)}
            return (high, low) not in bad_hands
        return (high, low) in rng['suited']

    # Offsuit hands
    return (high, low) in rng['offsuit']


def should_3bet(
    card1: Card, card2: Card,
    range_label: str,
    aggression: float,
    raise_size: float = 0.0,  # relative to pot
) -> tuple:
    """
    Decide whether to 3-bet preflop.
    Returns (should_3bet, is_value, is_bluff).
    """
    import random
    r1, r2 = card1.rank, card2.rank
    high, low = max(r1, r2), min(r1, r2)
    suited = card1.suit == card2.suit

    three_bet_rng = _THREE_BET_RANGES.get(range_label, _THREE_BET_RANGES['medium'])

    # Check value 3-bet
    is_pair = r1 == r2
    is_suited = suited
    for val_hand in three_bet_rng['value']:
        if len(val_hand) == 2:
            # Pair
            if is_pair and r1 == val_hand[0]:
                return (True, True, False)
        elif len(val_hand) == 3:
            if high == val_hand[0] and low == val_hand[1] and is_suited == val_hand[2]:
                return (True, True, False)

    # Check bluff 3-bet
    for bluff_hand in three_bet_rng['bluff']:
        if len(bluff_hand) == 3:
            if high == bluff_hand[0] and low == bluff_hand[1] and is_suited == bluff_hand[2]:
                if random.random() < aggression * 0.6:
                    return (True, False, True)

    # Random bluff with aggression
    if random.random() < aggression * 0.1:
        return (True, False, True)

    return (False, False, False)


def should_defend_bb(
    card1: Card, card2: Card,
    raise_size: float,  # relative to pot
    aggression: float,
) -> bool:
    """
    Decide whether to defend the big blind vs a raise.
    Gets better odds with smaller raises and more aggression.
    """
    from strategies.hand_score import score_starting_hand
    score = score_starting_hand(card1, card2)

    # Pot odds: smaller raise = better odds = defend wider
    pot_odds_factor = 1.0 - raise_size  # 0.3 raise → 0.7 factor

    # Threshold: defend if hand score * pot_odds > 30
    threshold = 30 * (1.0 - aggression * 0.3)
    return score * pot_odds_factor > threshold
