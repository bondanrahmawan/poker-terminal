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
    def to_string(rank: int, short_deck: bool = False) -> str:
        if short_deck:
            # In short deck, rank 7 = Flush (above Full House), rank 6 = Full House
            mapping = {
                1: "High Card", 2: "One Pair", 3: "Two Pair",
                4: "Three of a Kind", 5: "Straight",
                6: "Full House", 7: "Flush",
                8: "Four of a Kind", 9: "Straight Flush"
            }
        else:
            mapping = {
                1: "High Card", 2: "One Pair", 3: "Two Pair",
                4: "Three of a Kind", 5: "Straight", 6: "Flush",
                7: "Full House", 8: "Four of a Kind", 9: "Straight Flush"
            }
        return mapping.get(rank, "Unknown")


class HandEvaluator:
    @staticmethod
    def evaluate_5_cards(cards: List[Card], short_deck: bool = False) -> Tuple:
        assert len(cards) == 5
        ranks = sorted([c.rank for c in cards], reverse=True)
        suits = [c.suit for c in cards]
        is_flush = len(set(suits)) == 1

        is_straight = False
        if ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5:
            is_straight = True
        elif short_deck and ranks == [14, 9, 8, 7, 6]:
            # Short-deck wheel: A-6-7-8-9 (ace plays low)
            is_straight = True
            ranks = [9, 8, 7, 6, 1]
        elif not short_deck and ranks == [14, 5, 4, 3, 2]:
            # Regular wheel: A-2-3-4-5
            is_straight = True
            ranks = [5, 4, 3, 2, 1]

        rank_counts = Counter(ranks)
        counts = sorted(rank_counts.values(), reverse=True)

        if is_flush and is_straight:
            score = (HandRank.STRAIGHT_FLUSH, ranks[0])
        elif counts == [4, 1]:
            quad = [r for r, c in rank_counts.items() if c == 4][0]
            kicker = [r for r, c in rank_counts.items() if c == 1][0]
            score = (HandRank.FOUR_OF_A_KIND, quad, kicker)
        elif counts == [3, 2]:
            triplet = [r for r, c in rank_counts.items() if c == 3][0]
            pair = [r for r, c in rank_counts.items() if c == 2][0]
            score = (HandRank.FULL_HOUSE, triplet, pair)
        elif is_flush:
            score = (HandRank.FLUSH, *ranks)
        elif is_straight:
            score = (HandRank.STRAIGHT, ranks[0])
        elif counts == [3, 1, 1]:
            triplet = [r for r, c in rank_counts.items() if c == 3][0]
            kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)
            score = (HandRank.THREE_OF_A_KIND, triplet, *kickers)
        elif counts == [2, 2, 1]:
            pairs = sorted([r for r, c in rank_counts.items() if c == 2], reverse=True)
            kicker = [r for r, c in rank_counts.items() if c == 1][0]
            score = (HandRank.TWO_PAIR, pairs[0], pairs[1], kicker)
        elif counts == [2, 1, 1, 1]:
            pair = [r for r, c in rank_counts.items() if c == 2][0]
            kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)
            score = (HandRank.ONE_PAIR, pair, *kickers)
        else:
            score = (HandRank.HIGH_CARD, *ranks)

        # Short deck: swap Flush and Full House so Flush > Full House
        if short_deck and score[0] in (HandRank.FLUSH, HandRank.FULL_HOUSE):
            swap = {HandRank.FLUSH: 7, HandRank.FULL_HOUSE: 6}
            score = (swap[score[0]],) + score[1:]

        return score

    @staticmethod
    def evaluate(hole_cards: List[Card], community_cards: List[Card],
                 short_deck: bool = False) -> Tuple:
        all_cards = hole_cards + community_cards
        if len(all_cards) < 5:
            raise ValueError(f"Need at least 5 cards, got {len(all_cards)}")
        best_score = None
        best_hand = None
        for combo in combinations(all_cards, 5):
            combo_list = list(combo)
            score = HandEvaluator.evaluate_5_cards(combo_list, short_deck=short_deck)
            if best_score is None or score > best_score:
                best_score = score
                best_hand = combo_list
        return best_score, best_hand
