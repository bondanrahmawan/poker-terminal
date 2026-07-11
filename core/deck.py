import random
from typing import List
from core.card import Card, Suit, Rank


class Deck:
    def __init__(self, min_rank: int = 2, seed: int = None):
        self.min_rank = min_rank
        # seed=None keeps the historical behavior (global random, not seedable).
        self._rng = random.Random(seed) if seed is not None else random
        self.cards = []
        self._build()

    def _build(self):
        self.cards = [
            Card(rank, suit)
            for suit in Suit.get_all()
            for rank in Rank.get_all()
            if rank >= self.min_rank
        ]

    def shuffle(self):
        self._rng.shuffle(self.cards)

    def draw(self, count: int = 1) -> List[Card]:
        if count > len(self.cards):
            raise ValueError("Deck is empty")
        return [self.cards.pop() for _ in range(count)]

    def reset(self):
        self._build()
        self.shuffle()

    def __len__(self):
        return len(self.cards)
