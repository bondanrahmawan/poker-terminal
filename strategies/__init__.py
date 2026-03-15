from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple, Dict, Type
from core.card import Card
from core.player import PlayerAction


@dataclass(frozen=True)
class PlayerView:
    """Read-only snapshot of a player's state passed to strategy at decision time."""
    chips: int
    hole_cards: List[Card]


class BotStrategy(ABC):
    """
    Interface every bot AI must implement.

    Receives:
      game_state — dict with keys:
        min_call, min_raise, pot_size, community_cards,
        players_info, position, num_active, hand_log
      player — PlayerView snapshot (chips, hole_cards)

    Returns:
      (PlayerAction, amount)
    """

    @abstractmethod
    def decide(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        ...


# Strategy registry: name -> class, populated by @register()
REGISTRY: Dict[str, Type[BotStrategy]] = {}


def register(name: str):
    """Decorator that registers a strategy class under a string key."""
    def decorator(cls: Type[BotStrategy]) -> Type[BotStrategy]:
        REGISTRY[name] = cls
        return cls
    return decorator
