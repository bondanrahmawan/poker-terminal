"""
Draw detection and advanced postflop equity estimation.

Provides:
  - DrawInfo dataclass describing current draws
  - detect_draws() — finds flush draws, straight draws, made hands
  - advanced_equity() — equity estimate incorporating draws, outs, and opponent count
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Optional
from collections import Counter
from core.card import Card
from core.evaluator import HandEvaluator, HandRank
from strategies.hand_score import score_starting_hand


# ── Draw information ─────────────────────────────────────────────────────────

@dataclass
class DrawInfo:
    """Describes the draws available to a hand on a given board."""
    # Made hand
    hand_rank: int = 0               # HandRank value
    hand_name: str = ''

    # Flush draws
    flush_draw_suit: Optional[str] = None   # suit with 4+ cards
    flush_draw_cards: int = 0               # how many of suit in hand+board
    is_flush_draw: bool = False

    # Straight draws
    open_ended_straight_draw: bool = False  # 8 outs
    gutshot_straight_draw: bool = False     # 4 outs
    double_gutshot: bool = False            # 8 outs (two gaps)
    straight_draw_outs: int = 0

    # Paired board / trips potential
    has_pair: bool = False
    has_two_pair: bool = False
    has_trips: bool = False
    has_backdoor_flush: bool = False        # 3 of suit (needs 2 streets)
    has_backdoor_straight: bool = False     # connected with 1 gap

    @property
    def total_outs(self) -> int:
        """Rough count of outs to improve."""
        outs = 0
        if self.is_flush_draw:
            outs += 9  # 13 - 4 known
        if self.open_ended_straight_draw or self.double_gutshot:
            outs += 8
        elif self.gutshot_straight_draw:
            outs += 4
        # Backdoor draws (need 2 cards) — count as ~1.5 outs each
        if self.has_backdoor_flush:
            outs += 1.5
        if self.has_backdoor_straight:
            outs += 1.5
        return int(outs)

    @property
    def is_strong_draw(self) -> bool:
        """Combo draw or strong single draw."""
        return self.total_outs >= 12 or (
            self.is_flush_draw and (self.open_ended_straight_draw or self.gutshot_straight_draw)
        )

    @property
    def is_weak_draw(self) -> bool:
        """Only a gutshot or backdoor."""
        return self.total_outs <= 4 and not self.is_flush_draw


# ── Detection ────────────────────────────────────────────────────────────────

def detect_draws(hole_cards: List[Card], community: List[Card],
                 short_deck: bool = False) -> DrawInfo:
    """Analyze hole cards + community for draws and made hands."""
    info = DrawInfo()
    all_cards = hole_cards + community

    if len(community) < 3:
        return info

    # ── Made hand ──
    try:
        score, _ = HandEvaluator.evaluate(hole_cards, community, short_deck=short_deck)
        info.hand_rank = score[0]
        info.hand_name = HandRank.to_string(score[0], short_deck=short_deck)
        info.has_pair = score[0] == HandRank.ONE_PAIR
        info.has_two_pair = score[0] == HandRank.TWO_PAIR
        info.has_trips = score[0] == HandRank.THREE_OF_A_KIND
    except ValueError:
        pass  # Not enough cards yet

    # ── Flush draw detection ──
    suit_counts = Counter(c.suit for c in all_cards)
    hole_suits = Counter(c.suit for c in hole_cards)
    for suit, count in suit_counts.items():
        if count == 4:
            info.is_flush_draw = True
            info.flush_draw_suit = suit
            info.flush_draw_cards = 4
        elif count == 5:
            info.is_flush_draw = True
            info.flush_draw_suit = suit
            info.flush_draw_cards = 5
        elif count == 3 and hole_suits.get(suit, 0) == 2:
            info.has_backdoor_flush = True

    # ── Straight draw detection ──
    ranks = sorted(set(c.rank for c in all_cards))
    hole_ranks = sorted(c.rank for c in hole_cards)

    # Check for open-ended straight draw (8 outs)
    info.open_ended_straight_draw = _has_open_ended(ranks, hole_ranks)
    info.gutshot_straight_draw = _has_gutshot(ranks, hole_ranks)
    info.double_gutshot = _has_double_gutshot(ranks, hole_ranks)

    if info.open_ended_straight_draw or info.double_gutshot:
        info.straight_draw_outs = 8
    elif info.gutshot_straight_draw:
        info.straight_draw_outs = 4

    # Backdoor straight: 3 connected ranks within gap of 2
    if not info.open_ended_straight_draw and not info.gutshot_straight_draw:
        info.has_backdoor_straight = _has_backdoor_straight(ranks, hole_ranks)

    return info


def _has_open_ended(board_ranks: List[int], hole_ranks: List[int]) -> bool:
    """Check if player has 4 consecutive ranks with both ends open."""
    all_ranks = sorted(set(board_ranks + hole_ranks))
    # Need 4 consecutive ranks where we hold one end
    for i in range(len(all_ranks) - 3):
        window = all_ranks[i:i+4]
        if window[3] - window[0] == 3:
            # Check if at least one hole card is part of this sequence
            if any(r in hole_ranks for r in window):
                # Verify both ends are missing (open-ended)
                low_end = window[0] - 1
                high_end = window[3] + 1
                if low_end not in all_ranks and high_end not in all_ranks:
                    if low_end >= 2 or high_end <= 14:
                        return True
    return False


def _gutshot_scan_ranks(board_ranks: List[int], hole_ranks: List[int]) -> Tuple[List[int], set]:
    """Build the rank set (with ace also scanned low for wheel gutshots) and
    the set of hole ranks to test window membership against."""
    all_ranks = set(board_ranks) | set(hole_ranks)
    hole_scan = set(hole_ranks)
    if 14 in all_ranks:
        all_ranks.add(1)
    if 14 in hole_scan:
        hole_scan.add(1)
    return sorted(all_ranks), hole_scan


def _gutshot_missing_ranks(scan_ranks: List[int], hole_scan: set) -> set:
    """Missing ranks of every 4-distinct-rank, span-4 (one internal gap)
    window that includes at least one hole card."""
    missing = set()
    for i in range(len(scan_ranks) - 3):
        window = scan_ranks[i:i+4]
        if window[3] - window[0] == 4 and any(r in hole_scan for r in window):
            gap = set(range(window[0], window[3] + 1)) - set(window)
            if len(gap) == 1:
                missing.add(next(iter(gap)))
    return missing


def _has_gutshot(board_ranks: List[int], hole_ranks: List[int]) -> bool:
    """4 distinct ranks spanning exactly 4 (one internal rank missing),
    using at least one hole card, and not already an open-ended draw."""
    if _has_open_ended(board_ranks, hole_ranks):
        return False
    scan_ranks, hole_scan = _gutshot_scan_ranks(board_ranks, hole_ranks)
    return len(_gutshot_missing_ranks(scan_ranks, hole_scan)) >= 1


def _has_double_gutshot(board_ranks: List[int], hole_ranks: List[int]) -> bool:
    """Two distinct gutshot windows with two different missing ranks (8 outs)."""
    scan_ranks, hole_scan = _gutshot_scan_ranks(board_ranks, hole_ranks)
    return len(_gutshot_missing_ranks(scan_ranks, hole_scan)) >= 2


def _has_backdoor_straight(board_ranks: List[int], hole_ranks: List[int]) -> bool:
    """3 ranks within a span of 4, using at least 1 hole card."""
    all_ranks = sorted(set(board_ranks + hole_ranks))
    for i in range(len(all_ranks) - 2):
        window = all_ranks[i:i+3]
        if window[2] - window[0] <= 4:
            if any(r in hole_ranks for r in window):
                return True
    return False


# ── Advanced equity estimation ───────────────────────────────────────────────

# Base equity by hand rank (same as utils.py but extended)
_BASE_EQUITY = {
    HandRank.HIGH_CARD: 0.25,
    HandRank.ONE_PAIR: 0.42,
    HandRank.TWO_PAIR: 0.57,
    HandRank.THREE_OF_A_KIND: 0.67,
    HandRank.STRAIGHT: 0.76,
    HandRank.FLUSH: 0.84,
    HandRank.FULL_HOUSE: 0.91,
    HandRank.FOUR_OF_A_KIND: 0.96,
    HandRank.STRAIGHT_FLUSH: 0.99,
}

# Equity by outs (rule of 4 and 2 approximation)
_OUTS_EQUITY_FLOP = {
    0: 0.00, 1: 0.04, 2: 0.08, 3: 0.12, 4: 0.16, 5: 0.20,
    6: 0.24, 7: 0.28, 8: 0.32, 9: 0.35, 10: 0.38, 11: 0.41,
    12: 0.45, 13: 0.48, 14: 0.51, 15: 0.54, 16: 0.57, 17: 0.60,
    18: 0.62, 19: 0.65, 20: 0.68,
}

_OUTS_EQUITY_TURN = {
    0: 0.00, 1: 0.02, 2: 0.04, 3: 0.06, 4: 0.09, 5: 0.11,
    6: 0.13, 7: 0.15, 8: 0.17, 9: 0.20, 10: 0.22, 11: 0.24,
    12: 0.26, 13: 0.28, 14: 0.30, 15: 0.33, 16: 0.35, 17: 0.37,
    18: 0.39, 19: 0.41, 20: 0.43,
}


def preflop_equity(hole_cards: List[Card], num_opponents: int = 1) -> float:
    """Heads-up equity mapped from the 0-100 starting-hand score, then
    scaled for multiway pots. The multiway exponent is softened from the pure
    independent-opponent value n to 1 + 0.6*(n-1): shared-board correlation
    makes true multiway equity higher than hu**n, which otherwise badly
    underestimates weak hands (calibrated in Task 6: 5pp -> sub-4pp MAE)."""
    score = score_starting_hand(hole_cards[0], hole_cards[1])
    hu = 0.35 + 0.50 * (score / 100.0)      # AA(100)->0.85, 72o(5)->0.375
    n = max(1, num_opponents)
    return max(0.0, min(1.0, hu ** (1 + 0.6 * (n - 1))))


def advanced_equity(hole_cards: List[Card], community: List[Card],
                    num_opponents: int = 1, short_deck: bool = False) -> float:
    """
    Estimate equity incorporating draws, outs, and opponent count.

    On the flop uses rule-of-4; on the turn uses rule-of-2.
    Multiplayer pots reduce equity (more chances someone has you beat).
    """
    if not community:
        return preflop_equity(hole_cards, num_opponents)

    draw = detect_draws(hole_cards, community, short_deck)

    # ── Made hand equity ──
    try:
        score, _ = HandEvaluator.evaluate(hole_cards, community, short_deck=short_deck)
        base = _BASE_EQUITY.get(score[0], 0.25)
    except ValueError:
        base = 0.25

    # ── Draw equity (additive on top of made hand) ──
    is_turn = len(community) >= 4
    outs_table = _OUTS_EQUITY_TURN if is_turn else _OUTS_EQUITY_FLOP
    draw_equity = outs_table.get(draw.total_outs, 0.0)

    # If we have a made hand AND a draw, use the higher of the two (not sum)
    # but add a combo bonus for strong draws
    if draw.is_strong_draw:
        equity = max(base, draw_equity) + 0.05  # combo bonus
    elif base >= 0.50:
        # Already have a made hand — draws add marginal value
        equity = base + draw_equity * 0.3
    else:
        # Drawing hand — equity is mostly from outs
        equity = max(base, draw_equity)

    # ── Multiplayer adjustment ──
    if num_opponents > 1:
        # Each additional opponent reduces equity by ~3-5%
        equity *= (1.0 - 0.04 * (num_opponents - 1))

    # ── Pair on board reduction (harder to win with one pair) ──
    board_ranks = [c.rank for c in community]
    if len(set(board_ranks)) < len(board_ranks) and base <= 0.42:
        equity -= 0.05  # paired board hurts weak pairs

    return max(0.0, min(1.0, equity))


def equity_vs_range(hole_cards: List[Card], community: List[Card],
                    opponent_range: float = 0.3, num_opponents: int = 1,
                    short_deck: bool = False, base_equity: float = None) -> float:
    """
    Adjust equity for a known opponent looseness — two-sided and centered so an
    average opponent leaves equity unchanged.

    opponent_range: fraction of hands the opponent plays (0.1 = very tight,
    0.9 = very loose). A loose range means the opponent holds weaker hands on
    average, so our equity rises; a tight range means stronger hands, so it
    falls. At 0.5 the adjustment is zero.

    base_equity: if given, the adjustment is applied on top of it (so a more
    accurate Monte-Carlo estimate is preserved); otherwise advanced_equity is
    used as the base.
    """
    base = (base_equity if base_equity is not None
            else advanced_equity(hole_cards, community, num_opponents, short_deck))

    # +/- around an average (0.5) opponent; capped so multiway pots can't swing
    # the estimate wildly.
    adjustment = 0.15 * (opponent_range - 0.5) * min(num_opponents, 2)
    adjustment = max(-0.15, min(0.15, adjustment))

    return max(0.0, min(1.0, base + adjustment))


def monte_carlo_equity(hole_cards: List[Card], community: List[Card],
                       num_opponents: int = 1, trials: int = 100,
                       short_deck: bool = False) -> float:
    """Estimate equity via Monte Carlo simulation — deal random runouts and opponent hands."""
    import random as _rng
    from core.card import Suit, Rank

    known = set((c.rank, c.suit) for c in hole_cards + community)
    min_rank = 6 if short_deck else 2
    remaining = [Card(r, s) for s in Suit.get_all() for r in Rank.get_all()
                 if r >= min_rank and (r, s) not in known]

    cards_needed = 5 - len(community)
    total_opp_cards = 2 * num_opponents
    if len(remaining) < cards_needed + total_opp_cards:
        return advanced_equity(hole_cards, community, num_opponents, short_deck)

    wins = 0
    ties = 0
    for _ in range(trials):
        _rng.shuffle(remaining)
        idx = 0

        sim_community = community + remaining[idx:idx + cards_needed]
        idx += cards_needed

        my_score, _ = HandEvaluator.evaluate(hole_cards, sim_community, short_deck=short_deck)

        best_opp = None
        for _ in range(num_opponents):
            opp_cards = remaining[idx:idx + 2]
            idx += 2
            opp_score, _ = HandEvaluator.evaluate(opp_cards, sim_community, short_deck=short_deck)
            if best_opp is None or opp_score > best_opp:
                best_opp = opp_score

        if my_score > best_opp:
            wins += 1
        elif my_score == best_opp:
            ties += 1

    return (wins + ties * 0.5) / trials
