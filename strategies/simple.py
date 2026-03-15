"""
SimpleStrategy — the default bot AI.

Uses equity estimation, pot-odds calling, position awareness, and
pot-proportional raise sizing scaled by aggressiveness.
"""
import random
from typing import Tuple
from player import PlayerAction
from strategies import BotStrategy, PlayerView, register
from strategies.utils import estimate_equity, pot_odds, position_adjustment, calc_raise_amount


@register('simple')
class SimpleStrategy(BotStrategy):
    """
    Balanced strategy parameterised by a single aggressiveness float (0.0–1.0).
    - Calls when equity > pot odds (shifted by aggressiveness)
    - Raises with pot-proportional sizing (half-pot to full-pot)
    - Adjusts thresholds for table position
    """

    def __init__(self, aggressiveness: float = 0.5):
        self.aggressiveness = aggressiveness

    def decide(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        min_call        = game_state.get('min_call', 0)
        min_raise       = game_state.get('min_raise', 0)
        pot_size        = game_state.get('pot_size', 0)
        community_cards = game_state.get('community_cards', [])
        position        = game_state.get('position', 0)
        num_active      = game_state.get('num_active', 2)

        equity   = estimate_equity(player.hole_cards, community_cards)
        pos_adj  = position_adjustment(position, num_active)
        adj_eq   = equity + (self.aggressiveness - 0.5) * 0.15 - pos_adj
        rand_val = random.random()

        def _raise_amt() -> int:
            fraction = 0.5 + self.aggressiveness * 0.5  # 0.5 – 1.0
            return calc_raise_amount(pot_size, min_call, min_raise, player.chips, fraction)

        if min_call == 0:
            if adj_eq >= 0.45 and rand_val < self.aggressiveness:
                bet = _raise_amt()
                if bet == player.chips:
                    return PlayerAction.ALL_IN, bet
                return PlayerAction.RAISE, bet
            return PlayerAction.CHECK, 0
        else:
            odds = pot_odds(min_call, pot_size)
            if adj_eq >= 0.60 and rand_val < self.aggressiveness:
                raise_amt = _raise_amt()
                if raise_amt == player.chips:
                    return PlayerAction.ALL_IN, raise_amt
                return PlayerAction.RAISE, raise_amt
            elif adj_eq > odds:
                call_amount = min(player.chips, min_call)
                if call_amount == player.chips:
                    return PlayerAction.ALL_IN, call_amount
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.FOLD, 0
