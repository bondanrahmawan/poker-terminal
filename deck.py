import random
from card import Card, Suit, Rank

class Deck:
    def __init__(self):
        self.cards = []
        self._build()

    def _build(self):
        self.cards = [Card(rank, suit) for suit in Suit.get_all() for rank in Rank.get_all()]

    def shuffle(self):
        random.shuffle(self.cards)

    def draw(self, count=1):
        drawn = []
        for _ in range(count):
            if not self.cards:
                raise ValueError("Deck is empty")
            drawn.append(self.cards.pop())
        # Return a single item if drawing 1, otherwise list
        if count == 1:
            return drawn[0]
        return drawn

    def reset(self):
        self._build()
        self.shuffle()

    def __len__(self):
        return len(self.cards)
