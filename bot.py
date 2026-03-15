from typing import Tuple
from player import Player, PlayerAction
from strategies import BotStrategy, PlayerView
from strategies.simple import SimpleStrategy


class BotPlayer(Player):
    """
    A bot-controlled player. All decision logic lives in the strategy.
    Swap strategies to change AI behaviour without touching this class.

    Usage:
        BotPlayer("id", "Name", chips, SimpleStrategy(aggressiveness=0.8))
        BotPlayer("id", "Name", chips, TightPassiveStrategy())
        BotPlayer("id", "Name", chips)              # defaults to SimpleStrategy()
    """

    def __init__(self, player_id: str, name: str, starting_chips: int,
                 strategy: BotStrategy = None):
        super().__init__(player_id, name, starting_chips)
        self.strategy: BotStrategy = strategy or SimpleStrategy()

    def get_action(self, game_state: dict) -> Tuple[PlayerAction, int]:
        view = PlayerView(chips=self.chips, hole_cards=self.hole_cards)
        return self.strategy.decide(game_state, view)
