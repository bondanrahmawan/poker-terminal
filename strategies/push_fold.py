"""
Push/fold (jam-or-fold) charts for short-stack preflop play.

Standard-chart approximations expressed as "top X% of hands", using the
existing `score_starting_hand` table as the hand ordering (see
notes/bot_variant_b_pushfold.md for the honesty note on why this isn't
exact Nash/CFR). No imports from engine.py — avoids import cycles.
"""
from core.card import Card, Suit
from strategies.hand_score import score_starting_hand


# ── Score-cutoff table (built once at import) ────────────────────────────────

def _build_weighted_scores():
    """(score, combo_weight) for all 169 starting-hand classes."""
    entries = []
    for r in range(2, 15):
        entries.append((score_starting_hand(Card(r, Suit.SPADES), Card(r, Suit.HEARTS)), 6))
    for high in range(2, 15):
        for low in range(2, high):
            entries.append((score_starting_hand(Card(high, Suit.SPADES), Card(low, Suit.SPADES)), 4))
            entries.append((score_starting_hand(Card(high, Suit.SPADES), Card(low, Suit.HEARTS)), 12))
    return entries


def _build_cumulative_table():
    """[(score, cumulative_fraction)] sorted by score descending."""
    entries = _build_weighted_scores()
    total_weight = sum(w for _, w in entries)
    weight_by_score = {}
    for score, weight in entries:
        weight_by_score[score] = weight_by_score.get(score, 0) + weight
    cum = 0
    table = []
    for score in sorted(weight_by_score, reverse=True):
        cum += weight_by_score[score]
        table.append((score, cum / total_weight))
    return table


_CUM_TABLE = _build_cumulative_table()


def score_cutoff_for_fraction(fraction: float) -> int:
    """Score s such that hands scoring >= s make up ~`fraction` of all
    starting hands, weighted by combos (pair=6, suited=4, offsuit=12)."""
    fraction = max(0.01, min(1.0, fraction))
    for score, cum_frac in _CUM_TABLE:
        if cum_frac >= fraction:
            return score
    return _CUM_TABLE[-1][0]


# ── Jam chart — unopened pot, % of hands to shove ────────────────────────────

_JAM_FRACTIONS = {          # stack band (bb) -> {position: fraction}
    5:  {'UTG': 0.25, 'MP': 0.30, 'CO': 0.40, 'BTN': 0.55, 'SB': 0.75},
    8:  {'UTG': 0.18, 'MP': 0.22, 'CO': 0.30, 'BTN': 0.42, 'SB': 0.60},
    12: {'UTG': 0.12, 'MP': 0.15, 'CO': 0.22, 'BTN': 0.32, 'SB': 0.45},
    15: {'UTG': 0.08, 'MP': 0.10, 'CO': 0.15, 'BTN': 0.22, 'SB': 0.32},
}

# ── Call chart — facing a jam, % of hands to call ────────────────────────────

_CALL_FRACTIONS = {         # jam size band (bb) -> (heads_up, players_behind)
    5:  (0.35, 0.22),
    8:  (0.25, 0.15),
    12: (0.18, 0.11),
    15: (0.13, 0.08),
}

_STACK_BANDS = sorted(_JAM_FRACTIONS.keys())


def _band_for(stack_bb: float) -> int:
    for band in _STACK_BANDS:
        if stack_bb <= band:
            return band
    return _STACK_BANDS[-1]


# ── Public API ────────────────────────────────────────────────────────────────

def jam_fraction(stack_bb: float, position: str, aggression: float) -> float:
    """Chart fraction, tinted by style: fraction * (0.9 + 0.2 * aggression)."""
    band = _band_for(stack_bb)
    row = _JAM_FRACTIONS[band]
    base = row.get(position, row['MP'])
    tint = 0.9 + 0.2 * aggression
    return min(1.0, base * tint)


def call_fraction(jam_bb: float, players_behind: int, num_all_ins: int) -> float:
    if num_all_ins >= 2:
        return 0.05
    band = _band_for(jam_bb)
    heads_up, behind = _CALL_FRACTIONS[band]
    return behind if players_behind > 0 else heads_up


def should_jam(score: int, stack_bb: float, position: str, aggression: float) -> bool:
    return score >= score_cutoff_for_fraction(jam_fraction(stack_bb, position, aggression))


def should_call_jam(score: int, jam_bb: float, players_behind: int,
                     num_all_ins: int, widen: float = 0.0) -> bool:
    fraction = min(1.0, max(0.0, call_fraction(jam_bb, players_behind, num_all_ins) + widen))
    return score >= score_cutoff_for_fraction(fraction)
