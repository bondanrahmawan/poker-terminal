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
        players_info, position, num_active, hand_log,
        self_id, self_name, events, player_role, big_blind, current_bet
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


# ── Re-export new modules for convenience ────────────────────────────────────
from strategies.opponent_model import OpponentTracker, OpponentStats
from strategies.draw_detection import detect_draws, advanced_equity, monte_carlo_equity, DrawInfo
from strategies.betsizing import (
    BetSize, calc_bet_size, choose_bet_size, choose_raise_size, stack_depth_label,
)
from strategies.dynamic_behavior import (
    TiltState, TableImage, should_slow_play, should_semi_bluff,
    desperation_factor, adjust_for_desperation,
)
from strategies.preflop_ranges import (
    hand_in_range, should_3bet, position_to_range, should_defend_bb,
)
from strategies.push_fold import (
    should_jam, should_call_jam, score_cutoff_for_fraction,
)
