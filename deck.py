import random
from typing import List
from card import Card, Suit, Rank

class Deck:
    def __init__(self):
        self.cards = []
        self._build()

    def _build(self):
        self.cards = [Card(rank, suit) for suit in Suit.get_all() for rank in Rank.get_all()]

    def shuffle(self):
        random.shuffle(self.cards)

    def draw(self, count: int = 1) -> List[Card]:
        if count > len(self.cards):
            raise ValueError("Deck is empty")
        drawn = [self.cards.pop() for _ in range(count)]
        return drawn

    def reset(self):
        self._build()
        self.shuffle()

    def __len__(self):
        return len(self.cards)
