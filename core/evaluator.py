from itertools import combinations
from collections import Counter
from typing import List, Tuple
from core.card import Card

class HandRank:
    HIGH_CARD = 1
    ONE_PAIR = 2
    TWO_PAIR = 3
    THREE_OF_A_KIND = 4
    STRAIGHT = 5
    FLUSH = 6
    FULL_HOUSE = 7
    FOUR_OF_A_KIND = 8
    STRAIGHT_FLUSH = 9

    @staticmethod
    def to_string(rank: int) -> str:
        mapping = {
            1: "High Card", 2: "One Pair", 3: "Two Pair",
            4: "Three of a Kind", 5: "Straight", 6: "Flush",
            7: "Full House", 8: "Four of a Kind", 9: "Straight Flush"
        }
        return mapping.get(rank, "Unknown")


class HandEvaluator:
    @staticmethod
    def evaluate_5_cards(cards: List[Card]) -> Tuple:
        """
        Evaluates exactly 5 cards and returns a score tuple.
        The tuple's first element is the hand rank category.
        The remaining elements are used to break ties.
        """
        assert len(cards) == 5

        ranks = sorted([c.rank for c in cards], reverse=True)
        suits = [c.suit for c in cards]

        is_flush = len(set(suits)) == 1

        # Check for straight
        is_straight = False
        # Normal straight
        if ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5:
            is_straight = True
        # Ace-low straight (A, 5, 4, 3, 2)
        elif ranks == [14, 5, 4, 3, 2]:
            is_straight = True
            ranks = [5, 4, 3, 2, 1]  # Adjust A to 1 for straight comparison

        rank_counts = Counter(ranks)
        counts = sorted(rank_counts.values(), reverse=True)

        # Straight Flush
        if is_flush and is_straight:
            return (HandRank.STRAIGHT_FLUSH, ranks[0])

        # Four of a Kind
        if counts == [4, 1]:
            quad_rank = [r for r, c in rank_counts.items() if c == 4][0]
            kicker = [r for r, c in rank_counts.items() if c == 1][0]
            return (HandRank.FOUR_OF_A_KIND, quad_rank, kicker)

        # Full House
        if counts == [3, 2]:
            triplet = [r for r, c in rank_counts.items() if c == 3][0]
            pair = [r for r, c in rank_counts.items() if c == 2][0]
            return (HandRank.FULL_HOUSE, triplet, pair)

        # Flush
        if is_flush:
            return (HandRank.FLUSH, *ranks)

        # Straight
        if is_straight:
            return (HandRank.STRAIGHT, ranks[0])

        # Three of a Kind
        if counts == [3, 1, 1]:
            triplet = [r for r, c in rank_counts.items() if c == 3][0]
            kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)
            return (HandRank.THREE_OF_A_KIND, triplet, *kickers)

        # Two Pair
        if counts == [2, 2, 1]:
            pairs = sorted([r for r, c in rank_counts.items() if c == 2], reverse=True)
            kicker = [r for r, c in rank_counts.items() if c == 1][0]
            return (HandRank.TWO_PAIR, pairs[0], pairs[1], kicker)

        # One Pair
        if counts == [2, 1, 1, 1]:
            pair = [r for r, c in rank_counts.items() if c == 2][0]
            kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)
            return (HandRank.ONE_PAIR, pair, *kickers)

        # High Card
        return (HandRank.HIGH_CARD, *ranks)

    @staticmethod
    def evaluate(hole_cards: List[Card], community_cards: List[Card]) -> Tuple:
        """
        Evaluates the best 5-card hand from the available 7 cards.
        Returns a tuple: (score_tuple, best_5_cards_list)
        """
        all_cards = hole_cards + community_cards
        if len(all_cards) < 5:
            raise ValueError(f"Need at least 5 cards to evaluate, got {len(all_cards)}")

        best_score = None
        best_hand = None

        # Pick the best 5 card combinations out of the available cards
        # Typically 7 cards, so 21 combinations
        for combo in combinations(all_cards, 5):
            combo_list = list(combo)
            score = HandEvaluator.evaluate_5_cards(combo_list)
            if best_score is None or score > best_score:
                best_score = score
                best_hand = combo_list

        return best_score, best_hand
