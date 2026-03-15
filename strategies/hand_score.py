"""
Starting hand score table — returns 0-100 for any two hole cards.
Higher = stronger preflop holding.

Reference points from design doc:
  AA=100, KK=98, AKs=95, AQ~90, KQ~80, J7~20, 72=5
"""
from core.card import Card

# ── Pocket pairs ─────────────────────────────────────────────────────────────
_PAIR_SCORES = {
    14: 100,  # AA
    13:  98,  # KK
    12:  95,  # QQ
    11:  91,  # JJ
    10:  87,  # TT
     9:  80,  # 99
     8:  73,  # 88
     7:  66,  # 77
     6:  58,  # 66
     5:  52,  # 55
     4:  47,  # 44
     3:  43,  # 33
     2:  40,  # 22
}

# ── Non-pair hands: (high_rank, low_rank, suited) → score ────────────────────
_HAND_TABLE = {
    # Suited aces
    (14, 13, True): 95,  # AKs
    (14, 12, True): 88,  # AQs
    (14, 11, True): 85,  # AJs
    (14, 10, True): 82,  # ATs
    (14,  9, True): 72,  # A9s
    (14,  8, True): 68,  # A8s
    (14,  7, True): 65,  # A7s
    (14,  6, True): 62,  # A6s
    (14,  5, True): 61,  # A5s  (wheel draw)
    (14,  4, True): 58,  # A4s
    (14,  3, True): 56,  # A3s
    (14,  2, True): 54,  # A2s
    # Offsuit aces
    (14, 13, False): 90,  # AKo
    (14, 12, False): 83,  # AQo
    (14, 11, False): 79,  # AJo
    (14, 10, False): 75,  # ATo
    (14,  9, False): 63,  # A9o
    (14,  8, False): 59,  # A8o
    (14,  7, False): 55,  # A7o
    (14,  6, False): 52,  # A6o
    (14,  5, False): 51,  # A5o
    (14,  4, False): 48,  # A4o
    (14,  3, False): 46,  # A3o
    (14,  2, False): 43,  # A2o
    # Suited kings
    (13, 12, True): 84,  # KQs
    (13, 11, True): 80,  # KJs
    (13, 10, True): 76,  # KTs
    (13,  9, True): 68,  # K9s
    (13,  8, True): 55,  # K8s
    (13,  7, True): 52,  # K7s
    (13,  6, True): 50,  # K6s
    (13,  5, True): 48,  # K5s
    (13,  4, True): 46,  # K4s
    (13,  3, True): 44,  # K3s
    (13,  2, True): 42,  # K2s
    # Offsuit kings
    (13, 12, False): 80,  # KQo
    (13, 11, False): 74,  # KJo
    (13, 10, False): 69,  # KTo
    (13,  9, False): 59,  # K9o
    (13,  8, False): 45,  # K8o
    (13,  7, False): 42,  # K7o
    (13,  6, False): 39,  # K6o
    (13,  5, False): 37,  # K5o
    (13,  4, False): 35,  # K4o
    (13,  3, False): 33,  # K3o
    (13,  2, False): 31,  # K2o
    # Suited queens
    (12, 11, True): 79,  # QJs
    (12, 10, True): 74,  # QTs
    (12,  9, True): 63,  # Q9s
    (12,  8, True): 55,  # Q8s
    (12,  7, True): 48,  # Q7s
    (12,  6, True): 44,  # Q6s
    (12,  5, True): 40,  # Q5s
    (12,  4, True): 37,  # Q4s
    (12,  3, True): 35,  # Q3s
    (12,  2, True): 33,  # Q2s
    # Offsuit queens
    (12, 11, False): 72,  # QJo
    (12, 10, False): 67,  # QTo
    (12,  9, False): 55,  # Q9o
    (12,  8, False): 45,  # Q8o
    (12,  7, False): 38,  # Q7o
    (12,  6, False): 34,  # Q6o
    (12,  5, False): 31,  # Q5o
    (12,  4, False): 28,  # Q4o
    (12,  3, False): 26,  # Q3o
    (12,  2, False): 24,  # Q2o
    # Suited jacks
    (11, 10, True): 75,  # JTs
    (11,  9, True): 63,  # J9s
    (11,  8, True): 59,  # J8s
    (11,  7, True): 20,  # J7s  (design doc reference)
    (11,  6, True): 38,  # J6s
    (11,  5, True): 35,  # J5s
    (11,  4, True): 32,  # J4s
    (11,  3, True): 30,  # J3s
    (11,  2, True): 28,  # J2s
    # Offsuit jacks
    (11, 10, False): 67,  # JTo
    (11,  9, False): 55,  # J9o
    (11,  8, False): 48,  # J8o
    (11,  7, False): 20,  # J7o  (design doc reference)
    (11,  6, False): 28,  # J6o
    (11,  5, False): 25,  # J5o
    (11,  4, False): 22,  # J4o
    (11,  3, False): 20,  # J3o
    (11,  2, False): 18,  # J2o
    # Suited tens
    (10,  9, True): 68,  # T9s
    (10,  8, True): 60,  # T8s
    (10,  7, True): 52,  # T7s
    (10,  6, True): 44,  # T6s
    (10,  5, True): 38,  # T5s
    (10,  4, True): 32,  # T4s
    (10,  3, True): 28,  # T3s
    (10,  2, True): 25,  # T2s
    # Offsuit tens
    (10,  9, False): 57,  # T9o
    (10,  8, False): 48,  # T8o
    (10,  7, False): 40,  # T7o
    (10,  6, False): 33,  # T6o
    (10,  5, False): 27,  # T5o
    (10,  4, False): 23,  # T4o
    (10,  3, False): 20,  # T3o
    (10,  2, False): 18,  # T2o
    # Suited nines
    ( 9,  8, True): 60,  # 98s
    ( 9,  7, True): 52,  # 97s
    ( 9,  6, True): 45,  # 96s
    ( 9,  5, True): 38,  # 95s
    ( 9,  4, True): 30,  # 94s
    ( 9,  3, True): 26,  # 93s
    ( 9,  2, True): 23,  # 92s
    # Offsuit nines
    ( 9,  8, False): 48,  # 98o
    ( 9,  7, False): 40,  # 97o
    ( 9,  6, False): 33,  # 96o
    ( 9,  5, False): 27,  # 95o
    ( 9,  4, False): 21,  # 94o
    ( 9,  3, False): 18,  # 93o
    ( 9,  2, False): 15,  # 92o
    # Suited eights and below
    ( 8,  7, True): 53,  # 87s
    ( 8,  6, True): 44,  # 86s
    ( 8,  5, True): 38,  # 85s
    ( 8,  4, True): 28,  # 84s
    ( 8,  3, True): 22,  # 83s
    ( 8,  2, True): 18,  # 82s
    ( 7,  6, True): 46,  # 76s
    ( 7,  5, True): 38,  # 75s
    ( 7,  4, True): 28,  # 74s
    ( 7,  3, True): 21,  # 73s
    ( 7,  2, True):  5,  # 72s  (design doc reference)
    ( 6,  5, True): 40,  # 65s
    ( 6,  4, True): 28,  # 64s
    ( 6,  3, True): 20,  # 63s
    ( 6,  2, True): 15,  # 62s
    ( 5,  4, True): 32,  # 54s
    ( 5,  3, True): 20,  # 53s
    ( 5,  2, True): 13,  # 52s
    ( 4,  3, True): 18,  # 43s
    ( 4,  2, True): 12,  # 42s
    ( 3,  2, True): 10,  # 32s
    # Offsuit low hands (worst of the worst)
    ( 8,  7, False): 38,
    ( 7,  6, False): 32,
    ( 8,  6, False): 30,
    ( 6,  5, False): 28,
    ( 7,  5, False): 25,
    ( 8,  5, False): 26,
    ( 9,  2, False): 15,
    ( 8,  2, False): 12,
    ( 7,  2, False):  5,  # 72o  (design doc reference — worst hand)
    ( 6,  2, False): 13,
    ( 5,  2, False): 12,
    ( 4,  2, False): 10,
    ( 3,  2, False):  8,
    ( 4,  3, False): 14,
    ( 5,  3, False): 14,
    ( 6,  3, False): 13,
    ( 7,  3, False): 14,
    ( 8,  3, False): 16,
    ( 6,  4, False): 20,
    ( 7,  4, False): 18,
    ( 8,  4, False): 20,
    ( 5,  4, False): 22,
}


def score_starting_hand(card1: Card, card2: Card) -> int:
    """
    Returns a starting hand strength score (0-100).
    Used for preflop play/fold decisions.
    Higher score = stronger hand.
    """
    r1, r2 = card1.rank, card2.rank
    suited = card1.suit == card2.suit

    if r1 == r2:
        return _PAIR_SCORES.get(r1, 35)

    high, low = max(r1, r2), min(r1, r2)
    score = _HAND_TABLE.get((high, low, suited))
    if score is not None:
        return score

    # Fallback formula for any unlisted hand
    base = (high - 2) * 2 + (low - 2)
    if suited:
        base += 6
    if high - low == 1:
        base += 4
    elif high - low == 2:
        base += 2
    return max(1, min(base, 55))
