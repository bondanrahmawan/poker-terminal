from enum import Enum
from typing import List, Tuple
from core.card import Card

class PlayerAction(Enum):
    FOLD = "fold"
    CALL = "call"
    RAISE = "raise"
    CHECK = "check"
    ALL_IN = "all-in"

class Player:
    interactive = False  # engine pauses for this player instead of calling get_action()

    def __init__(self, player_id: str, name: str, starting_chips: int):
        self.player_id = player_id
        self.name = name
        self.chips = starting_chips
        self.hole_cards: List[Card] = []

        # State variables
        self.is_active = True
        self.is_all_in = False

    def reset_for_hand(self):
        self.hole_cards = []
        if self.chips > 0:
            self.is_active = True
            self.is_all_in = False
        else:
            self.is_active = False # Busted players

    def receive_cards(self, cards: List[Card]):
        self.hole_cards.extend(cards)

    def lose_chips(self, amount: int) -> int:
        """Deducts up to amount from player chips. Returns actual deducted amount."""
        if amount >= self.chips:
            actual = self.chips
            self.chips = 0
            self.is_all_in = True
            return actual
        else:
            self.chips -= amount
            return amount

    def win_chips(self, amount: int):
        """Adds chips to player stack."""
        self.chips += amount

    def fold(self):
        self.is_active = False
        self.hole_cards = []

    def can_act(self) -> bool:
        """Returns True if the player can take action (active and not all-in)."""
        return self.is_active and not self.is_all_in

    def get_action(self, game_state: dict) -> Tuple[PlayerAction, int]:
        """
        To be overridden by subclasses (bot, human via UI or network).
        Returns (PlayerAction, amount)
        """
        raise NotImplementedError("Subclasses must implement get_action")

    def __repr__(self):
        return f"{self.name} (Chips: {self.chips})"
