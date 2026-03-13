import random
from player import Player, PlayerAction
from evaluator import HandEvaluator

class BotPlayer(Player):
    def __init__(self, player_id: str, name: str, starting_chips: int, aggressiveness: float = 0.5):
        super().__init__(player_id, name, starting_chips)
        # Value between 0.0 (very passive) and 1.0 (very aggressive)
        self.aggressiveness = aggressiveness

    def get_action(self, game_state: dict) -> tuple[str, int]:
        """
        Simple bot logic.
        game_state expects:
        - min_call: amount needed to call
        - min_raise: minimum amount to raise to
        - pot_size: total size of the pot
        - community_cards: list of visible cards on the board
        """
        
        min_call = game_state.get('min_call', 0)
        min_raise = game_state.get('min_raise', 0)
        community_cards = game_state.get('community_cards', [])
        
        score, _ = HandEvaluator.evaluate(self.hole_cards, community_cards)
        hand_strength = score[0] if score else 0
        
        # Super simple logic:
        # Pre-flop, check if hand has high cards
        if len(community_cards) == 0:
            ranks = [c.rank for c in self.hole_cards]
            if max(ranks) > 10 or abs(ranks[0] - ranks[1]) <= 1:
                hand_strength = 2 # Treat like generic good starting hand
        
        rand_val = random.random()
        
        # Must act logic
        if min_call == 0:
            # Check or bet
            if hand_strength >= 2 and rand_val < self.aggressiveness:
                # Bet
                bet_amount = min(self.chips, min_raise)
                if bet_amount == self.chips:
                    return PlayerAction.ALL_IN, bet_amount
                return PlayerAction.RAISE, bet_amount
            else:
                return PlayerAction.CHECK, 0
        else:
            # Call, Raise, or Fold
            if hand_strength >= 3 and rand_val < (self.aggressiveness * 1.5):
                # Raise
                raise_amount = min(self.chips, min_raise + min_call)
                if raise_amount == self.chips:
                    return PlayerAction.ALL_IN, raise_amount
                return PlayerAction.RAISE, raise_amount
            elif (hand_strength >= 2) or (rand_val < 0.3):
                # Call
                call_amount = min(self.chips, min_call)
                if call_amount == self.chips:
                    return PlayerAction.ALL_IN, call_amount
                return PlayerAction.CALL, call_amount
            else:
                return PlayerAction.FOLD, 0
