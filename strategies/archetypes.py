"""
Archetype strategies — distinct poker personality types.

Each class embodies a named playstyle and can be used as-is
without any configuration parameters.
"""
import random
from typing import Tuple
from player import PlayerAction
from strategies import BotStrategy, PlayerView, register
from strategies.utils import estimate_equity, pot_odds, position_adjustment, calc_raise_amount


@register('tight_passive')
class TightPassiveStrategy(BotStrategy):
    """
    Nit / rock — only enters pots with strong hands, rarely raises,
    prefers calling over betting, folds quickly to aggression.
    Hardest player to extract chips from; also rarely wins big pots.
    """

    def decide(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        min_call        = game_state.get('min_call', 0)
        min_raise       = game_state.get('min_raise', 0)
        pot_size        = game_state.get('pot_size', 0)
        community_cards = game_state.get('community_cards', [])
        position        = game_state.get('position', 0)
        num_active      = game_state.get('num_active', 2)

        equity  = estimate_equity(player.hole_cards, community_cards)
        pos_adj = position_adjustment(position, num_active)
        adj_eq  = equity - pos_adj  # no aggressiveness bonus

        if min_call == 0:
            if adj_eq >= 0.70 and random.random() < 0.4:
                bet = calc_raise_amount(pot_size, min_call, min_raise, player.chips, 0.5)
                if bet == player.chips:
                    return PlayerAction.ALL_IN, bet
                return PlayerAction.RAISE, bet
            return PlayerAction.CHECK, 0
        else:
            odds = pot_odds(min_call, pot_size)
            if adj_eq >= 0.75 and random.random() < 0.3:
                raise_amt = calc_raise_amount(pot_size, min_call, min_raise, player.chips, 0.5)
                if raise_amt == player.chips:
                    return PlayerAction.ALL_IN, raise_amt
                return PlayerAction.RAISE, raise_amt
            elif adj_eq >= 0.50 or adj_eq > odds:
                call_amount = min(player.chips, min_call)
                if call_amount == player.chips:
                    return PlayerAction.ALL_IN, call_amount
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.FOLD, 0


@register('loose_aggressive')
class LooseAggressiveStrategy(BotStrategy):
    """
    LAG — enters many pots, applies constant pressure with bets and raises,
    exploits position aggressively. High variance; can bully passive tables.
    """

    def decide(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        min_call        = game_state.get('min_call', 0)
        min_raise       = game_state.get('min_raise', 0)
        pot_size        = game_state.get('pot_size', 0)
        community_cards = game_state.get('community_cards', [])
        position        = game_state.get('position', 0)
        num_active      = game_state.get('num_active', 2)

        equity   = estimate_equity(player.hole_cards, community_cards)
        pos_adj  = position_adjustment(position, num_active)
        adj_eq   = equity + 0.12 - pos_adj  # wider range than default
        rand_val = random.random()

        if min_call == 0:
            if adj_eq >= 0.35 and rand_val < 0.75:
                bet = calc_raise_amount(pot_size, min_call, min_raise, player.chips, 0.75)
                if bet == player.chips:
                    return PlayerAction.ALL_IN, bet
                return PlayerAction.RAISE, bet
            return PlayerAction.CHECK, 0
        else:
            odds = pot_odds(min_call, pot_size)
            if adj_eq >= 0.45 and rand_val < 0.65:
                raise_amt = calc_raise_amount(pot_size, min_call, min_raise, player.chips, 1.0)
                if raise_amt == player.chips:
                    return PlayerAction.ALL_IN, raise_amt
                return PlayerAction.RAISE, raise_amt
            elif adj_eq > odds - 0.05:  # calls slightly wider than pure pot odds
                call_amount = min(player.chips, min_call)
                if call_amount == player.chips:
                    return PlayerAction.ALL_IN, call_amount
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.FOLD, 0


@register('calling_station')
class CallingStationStrategy(BotStrategy):
    """
    Calling station — calls down with almost any holding,
    rarely raises, almost never folds if they have a pair or better.
    Easy to exploit by value-betting relentlessly.
    """

    def decide(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        min_call        = game_state.get('min_call', 0)
        min_raise       = game_state.get('min_raise', 0)
        pot_size        = game_state.get('pot_size', 0)
        community_cards = game_state.get('community_cards', [])

        equity = estimate_equity(player.hole_cards, community_cards)

        if min_call == 0:
            # Almost never bets — only with very strong hands occasionally
            if equity >= 0.80 and random.random() < 0.3:
                bet = calc_raise_amount(pot_size, min_call, min_raise, player.chips, 0.4)
                if bet == player.chips:
                    return PlayerAction.ALL_IN, bet
                return PlayerAction.RAISE, bet
            return PlayerAction.CHECK, 0
        else:
            odds = pot_odds(min_call, pot_size)
            # Calls with any reasonable holding — only folds clear garbage
            if equity >= 0.28 or equity > odds * 0.7:
                call_amount = min(player.chips, min_call)
                if call_amount == player.chips:
                    return PlayerAction.ALL_IN, call_amount
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.FOLD, 0
