import random

class Suit:
    SPADES = 'Spades'
    HEARTS = 'Hearts'
    DIAMONDS = 'Diamonds'
    CLUBS = 'Clubs'

    @staticmethod
    def get_all():
        return [Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS]

class Rank:
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13
    ACE = 14

    @staticmethod
    def get_all():
        return list(range(2, 15))

    @staticmethod
    def to_string(rank):
        mapping = {
            11: 'J', 12: 'Q', 13: 'K', 14: 'A'
        }
        return mapping.get(rank, str(rank))


class Card:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit

    def __repr__(self):
        rank_str = Rank.to_string(self.rank)
        suit_char = {Suit.SPADES: '♠', Suit.HEARTS: '♥', Suit.DIAMONDS: '♦', Suit.CLUBS: '♣'}[self.suit]
        return f"{rank_str}{suit_char}"

    def __eq__(self, other):
        if not isinstance(other, Card):
            return False
        return self.rank == other.rank and self.suit == other.suit

    def __hash__(self):
        return hash((self.rank, self.suit))

    def __lt__(self, other):
        # Sort primarily by rank
        return self.rank < other.rank
