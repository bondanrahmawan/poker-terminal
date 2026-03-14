"""
Comprehensive tests for HandEvaluator.
Run with: pytest test_eval.py -v
"""
import pytest
from evaluator import HandEvaluator, HandRank
from card import Card, Suit


class TestHandEvaluator:
    """Tests for 5-card hand evaluation."""

    def test_high_card(self):
        """Test high card detection."""
        cards = [
            Card(14, Suit.SPADES),   # Ace
            Card(10, Suit.HEARTS),   # 10
            Card(7, Suit.DIAMONDS),  # 7
            Card(5, Suit.CLUBS),     # 5
            Card(3, Suit.SPADES),    # 3
        ]
        score, hand = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.HIGH_CARD
        assert score[1] == 14  # Ace kicker

    def test_one_pair(self):
        """Test one pair detection."""
        cards = [
            Card(10, Suit.SPADES),
            Card(10, Suit.HEARTS),
            Card(8, Suit.DIAMONDS),
            Card(5, Suit.CLUBS),
            Card(3, Suit.SPADES),
        ]
        score, hand = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.ONE_PAIR
        assert score[1] == 10  # Pair of 10s

    def test_two_pair(self):
        """Test two pair detection."""
        cards = [
            Card(12, Suit.SPADES),   # Queen
            Card(12, Suit.HEARTS),   # Queen
            Card(8, Suit.DIAMONDS),  # 8
            Card(8, Suit.CLUBS),     # 8
            Card(3, Suit.SPADES),    # 3
        ]
        score, hand = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.TWO_PAIR
        assert score[1] == 12  # Higher pair
        assert score[2] == 8   # Lower pair

    def test_three_of_a_kind(self):
        """Test three of a kind detection."""
        cards = [
            Card(9, Suit.SPADES),
            Card(9, Suit.HEARTS),
            Card(9, Suit.DIAMONDS),
            Card(5, Suit.CLUBS),
            Card(3, Suit.SPADES),
        ]
        score, hand = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.THREE_OF_A_KIND
        assert score[1] == 9

    def test_straight(self):
        """Test straight detection."""
        cards = [
            Card(10, Suit.SPADES),
            Card(9, Suit.HEARTS),
            Card(8, Suit.DIAMONDS),
            Card(7, Suit.CLUBS),
            Card(6, Suit.SPADES),
        ]
        score, hand = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.STRAIGHT
        assert score[1] == 10  # Top card of straight

    def test_straight_ace_low(self):
        """Test ace-low straight (A-2-3-4-5)."""
        cards = [
            Card(14, Suit.SPADES),  # Ace
            Card(2, Suit.HEARTS),
            Card(3, Suit.DIAMONDS),
            Card(4, Suit.CLUBS),
            Card(5, Suit.SPADES),
        ]
        score, hand = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.STRAIGHT
        assert score[1] == 5  # Treated as 5-high straight

    def test_flush(self):
        """Test flush detection."""
        cards = [
            Card(14, Suit.SPADES),
            Card(11, Suit.SPADES),
            Card(8, Suit.SPADES),
            Card(5, Suit.SPADES),
            Card(3, Suit.SPADES),
        ]
        score, hand = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.FLUSH
        assert score[1] == 14  # Ace high flush

    def test_full_house(self):
        """Test full house detection."""
        cards = [
            Card(10, Suit.SPADES),
            Card(10, Suit.HEARTS),
            Card(10, Suit.DIAMONDS),
            Card(4, Suit.CLUBS),
            Card(4, Suit.SPADES),
        ]
        score, hand = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.FULL_HOUSE
        assert score[1] == 10  # Triplet
        assert score[2] == 4   # Pair

    def test_four_of_a_kind(self):
        """Test four of a kind detection."""
        cards = [
            Card(7, Suit.SPADES),
            Card(7, Suit.HEARTS),
            Card(7, Suit.DIAMONDS),
            Card(7, Suit.CLUBS),
            Card(2, Suit.SPADES),
        ]
        score, hand = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.FOUR_OF_A_KIND
        assert score[1] == 7   # Quad rank
        assert score[2] == 2   # Kicker

    def test_straight_flush(self):
        """Test straight flush detection."""
        cards = [
            Card(10, Suit.SPADES),
            Card(9, Suit.SPADES),
            Card(8, Suit.SPADES),
            Card(7, Suit.SPADES),
            Card(6, Suit.SPADES),
        ]
        score, hand = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.STRAIGHT_FLUSH
        assert score[1] == 10

    def test_royal_flush(self):
        """Test royal flush detection (highest straight flush)."""
        cards = [
            Card(14, Suit.SPADES),  # Ace
            Card(13, Suit.SPADES),  # King
            Card(12, Suit.SPADES),  # Queen
            Card(11, Suit.SPADES),  # Jack
            Card(10, Suit.SPADES),  # 10
        ]
        score, hand = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.STRAIGHT_FLUSH
        assert score[1] == 14  # Ace high


class TestSevenCardEvaluation:
    """Tests for 7-card (hole + community) evaluation."""

    def test_best_hand_from_seven_cards(self):
        """Test that evaluator picks best 5 from 7 cards."""
        hole_cards = [Card(14, Suit.SPADES), Card(13, Suit.SPADES)]  # A♠ K♠
        community = [
            Card(12, Suit.SPADES),  # Q♠
            Card(11, Suit.SPADES),  # J♠
            Card(10, Suit.SPADES),  # 10♠ (makes royal flush)
            Card(2, Suit.HEARTS),
            Card(3, Suit.CLUBS),
        ]
        score, hand = HandEvaluator.evaluate(hole_cards, community)
        assert score[0] == HandRank.STRAIGHT_FLUSH
        assert score[1] == 14

    def test_uses_community_cards(self):
        """Test that community cards are used in evaluation."""
        hole_cards = [Card(2, Suit.SPADES), Card(7, Suit.HEARTS)]  # Bad hand
        community = [
            Card(14, Suit.DIAMONDS),  # Ace
            Card(13, Suit.CLUBS),     # King
            Card(12, Suit.HEARTS),    # Queen
            Card(11, Suit.SPADES),    # Jack
            Card(10, Suit.DIAMONDS),  # 10 (makes straight on board)
        ]
        score, hand = HandEvaluator.evaluate(hole_cards, community)
        assert score[0] == HandRank.STRAIGHT

    def test_pocket_pair_makes_set(self):
        """Test that pocket pair can make three of a kind with community."""
        hole_cards = [Card(10, Suit.SPADES), Card(10, Suit.HEARTS)]  # Pair of 10s
        community = [
            Card(10, Suit.DIAMONDS),  # Third 10
            Card(5, Suit.CLUBS),
            Card(3, Suit.SPADES),
            Card(2, Suit.HEARTS),
            Card(14, Suit.DIAMONDS),  # Ace kicker
        ]
        score, hand = HandEvaluator.evaluate(hole_cards, community)
        assert score[0] == HandRank.THREE_OF_A_KIND
        assert score[1] == 10


class TestHandComparison:
    """Tests for hand ranking comparisons (tiebreakers)."""

    def test_higher_pair_wins(self):
        """Test that higher pair beats lower pair."""
        # Player 1: Pair of Aces
        score1, _ = HandEvaluator.evaluate(
            [Card(14, Suit.SPADES), Card(14, Suit.HEARTS)],
            [Card(2, Suit.DIAMONDS), Card(3, Suit.CLUBS), Card(4, Suit.SPADES), Card(5, Suit.HEARTS), Card(6, Suit.DIAMONDS)]
        )
        # Player 2: Pair of Kings
        score2, _ = HandEvaluator.evaluate(
            [Card(13, Suit.SPADES), Card(13, Suit.HEARTS)],
            [Card(2, Suit.DIAMONDS), Card(3, Suit.CLUBS), Card(4, Suit.SPADES), Card(5, Suit.HEARTS), Card(6, Suit.DIAMONDS)]
        )
        assert score1 > score2

    def test_kicker_decides_tie(self):
        """Test that kicker breaks ties in pair hands."""
        # Player 1: A-K (Ace pair, K kicker)
        score1, _ = HandEvaluator.evaluate(
            [Card(14, Suit.SPADES), Card(14, Suit.HEARTS), Card(13, Suit.DIAMONDS)],
            [Card(2, Suit.CLUBS), Card(3, Suit.SPADES), Card(4, Suit.HEARTS), Card(5, Suit.DIAMONDS)]
        )
        # Player 2: A-Q (Ace pair, Q kicker)
        score2, _ = HandEvaluator.evaluate(
            [Card(14, Suit.CLUBS), Card(14, Suit.DIAMONDS), Card(12, Suit.HEARTS)],
            [Card(2, Suit.SPADES), Card(3, Suit.HEARTS), Card(4, Suit.CLUBS), Card(5, Suit.SPADES)]
        )
        assert score1 > score2

    def test_straight_flush_beats_four_of_a_kind(self):
        """Test hand ranking hierarchy."""
        # Four of a kind
        score1, _ = HandEvaluator.evaluate(
            [Card(10, Suit.SPADES), Card(10, Suit.HEARTS)],
            [Card(10, Suit.DIAMONDS), Card(10, Suit.CLUBS), Card(2, Suit.SPADES), Card(3, Suit.HEARTS), Card(4, Suit.DIAMONDS)]
        )
        # Straight flush
        score2, _ = HandEvaluator.evaluate(
            [Card(9, Suit.SPADES), Card(8, Suit.SPADES)],
            [Card(7, Suit.SPADES), Card(6, Suit.SPADES), Card(5, Suit.SPADES), Card(2, Suit.HEARTS), Card(3, Suit.CLUBS)]
        )
        assert score2 > score1


class TestEdgeCases:
    """Edge case tests."""

    def test_all_suits_equal_for_non_flush(self):
        """Test that suits don't affect non-flush hands."""
        cards1 = [Card(10, Suit.SPADES), Card(10, Suit.HEARTS), Card(5, Suit.DIAMONDS), Card(4, Suit.CLUBS), Card(3, Suit.SPADES)]
        cards2 = [Card(10, Suit.CLUBS), Card(10, Suit.DIAMONDS), Card(5, Suit.SPADES), Card(4, Suit.HEARTS), Card(3, Suit.CLUBS)]
        score1, _ = HandEvaluator.evaluate_5_cards(cards1)
        score2, _ = HandEvaluator.evaluate_5_cards(cards2)
        assert score1 == score2

    def test_straight_wrap_not_valid(self):
        """Test that Q-K-A-2-3 is not a valid straight."""
        cards = [
            Card(12, Suit.SPADES),  # Queen
            Card(13, Suit.HEARTS),  # King
            Card(14, Suit.DIAMONDS),# Ace
            Card(2, Suit.CLUBS),    # 2
            Card(3, Suit.SPADES),   # 3
        ]
        score, _ = HandEvaluator.evaluate_5_cards(cards)
        assert score[0] == HandRank.HIGH_CARD  # Not a straight


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
