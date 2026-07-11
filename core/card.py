import random

_ANSI_RED   = '\033[91m'
_ANSI_RESET = '\033[0m'

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


SUIT_CODE = {Suit.SPADES: 'S', Suit.HEARTS: 'H', Suit.DIAMONDS: 'D', Suit.CLUBS: 'C'}


class Card:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit

    def to_dict(self) -> dict:
        """JSON-safe representation for serialization (Phase 3)."""
        return {"rank": self.rank, "suit": SUIT_CODE[self.suit], "display": repr(self)}

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

    def colored_str(self) -> str:
        """Returns ANSI-colored repr: red for Hearts/Diamonds."""
        base = repr(self)
        if self.suit in (Suit.HEARTS, Suit.DIAMONDS):
            return f"{_ANSI_RED}{base}{_ANSI_RESET}"
        return base
