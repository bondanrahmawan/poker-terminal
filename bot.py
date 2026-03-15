import random
from typing import Tuple
from player import Player, PlayerAction
from evaluator import HandEvaluator

# Estimated equity by hand rank (index = HandRank value 0..9)
# 0 = unset, 1 = High Card, ..., 9 = Royal/Straight Flush
_EQUITY_BY_RANK = [0.0, 0.25, 0.42, 0.57, 0.67, 0.76, 0.84, 0.91, 0.96, 0.99]

class BotPlayer(Player):
    def __init__(self, player_id: str, name: str, starting_chips: int, aggressiveness: float = 0.5):
        super().__init__(player_id, name, starting_chips)
        self.aggressiveness = aggressiveness

    def _estimate_equity(self, community_cards: list) -> float:
        if len(community_cards) == 0:
            ranks = [c.rank for c in self.hole_cards]
            is_strong = max(ranks) > 10 or abs(ranks[0] - ranks[1]) <= 1
            return 0.55 if is_strong else 0.32
        score, _ = HandEvaluator.evaluate(self.hole_cards, community_cards)
        rank = score[0] if score else 0
        return _EQUITY_BY_RANK[min(rank, 9)]

    def _position_adjustment(self, position: int, num_active: int) -> float:
        """
        Returns an equity adjustment based on table position.
        position 0 = dealer/button (best — acts last post-flop), play looser.
        position 1 = SB (acts first post-flop), play tighter.
        position 2 = BB, slightly tight.
        Higher positions closer to button = looser.
        """
        if num_active <= 2:
            return 0.0
        # Normalise: 0.0 = button, 1.0 = just left of button (SB area)
        relative = position / num_active
        if position == 0:          # Button
            return -0.08
        elif position <= 2:        # Blinds
            return +0.06
        elif relative >= 0.75:     # Cut-off / near button
            return -0.04
        return 0.0

    def get_action(self, game_state: dict) -> Tuple[PlayerAction, int]:
        min_call   = game_state.get('min_call', 0)
        min_raise  = game_state.get('min_raise', 0)
        pot_size   = game_state.get('pot_size', 0)
        community_cards = game_state.get('community_cards', [])
        position   = game_state.get('position', 0)
        num_active = game_state.get('num_active', 2)

        equity     = self._estimate_equity(community_cards)
        pos_adj    = self._position_adjustment(position, num_active)
        # Aggressiveness shifts threshold; position shifts strategy
        adj_equity = equity + (self.aggressiveness - 0.5) * 0.15 - pos_adj
        rand_val   = random.random()

        def _raise_amount() -> int:
            """Pot-proportional raise scaled by aggressiveness (half-pot to full-pot)."""
            fraction = 0.5 + self.aggressiveness * 0.5   # 0.5 – 1.0
            raw = int(pot_size * fraction) + min_call
            raw = max(raw, min_raise + min_call)          # never below min raise
            return min(self.chips, raw)

        if min_call == 0:
            if adj_equity >= 0.45 and rand_val < self.aggressiveness:
                bet_amount = _raise_amount()
                if bet_amount == self.chips:
                    return PlayerAction.ALL_IN, bet_amount
                return PlayerAction.RAISE, bet_amount
            return PlayerAction.CHECK, 0
        else:
            pot_odds = min_call / (pot_size + min_call) if (pot_size + min_call) > 0 else 0

            if adj_equity >= 0.60 and rand_val < self.aggressiveness:
                raise_amt = _raise_amount()
                if raise_amt == self.chips:
                    return PlayerAction.ALL_IN, raise_amt
                return PlayerAction.RAISE, raise_amt
            elif adj_equity > pot_odds:
                call_amount = min(self.chips, min_call)
                if call_amount == self.chips:
                    return PlayerAction.ALL_IN, call_amount
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.FOLD, 0
