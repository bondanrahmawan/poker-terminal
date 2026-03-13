import time
from typing import List, Dict, Tuple
from state import GameState
from deck import Deck
from betting import BetManager, PotManager
from player import Player, PlayerAction
from evaluator import HandEvaluator

class Game:
    def __init__(self, big_blind: int):
        self.players: List[Player] = []
        self.deck = Deck()
        self.state = GameState.WAITING
        self.bet_manager = BetManager(big_blind)
        self.pot_manager = PotManager()
        self.community_cards = []
        self.big_blind = big_blind
        self.dealer_idx = 0
        self.logs = []
        
    def log(self, msg: str):
        self.logs.append(msg)
        
    def add_player(self, player: Player):
        self.players.append(player)
        
    def remove_player(self, player_id: str):
        self.players = [p for p in self.players if p.player_id != player_id]

    def start_game(self):
        if len(self.players) < 2:
            self.log("Not enough players to start.")
            return
        self.state = GameState.DEAL
        self.run_cycle()
        
    def run_cycle(self):
        # State machine main loop (simplified for synchronous play)
        while self.state != GameState.WAITING:
            if self.state == GameState.DEAL:
                self._handle_deal()
            elif self.state == GameState.PREFLOP:
                self._handle_betting_round()
                if self._check_round_end():
                    self.state = GameState.FLOP
            elif self.state == GameState.FLOP:
                self._deal_community(3)
                self._handle_betting_round()
                if self._check_round_end():
                    self.state = GameState.TURN
            elif self.state == GameState.TURN:
                self._deal_community(1)
                self._handle_betting_round()
                if self._check_round_end():
                    self.state = GameState.RIVER
            elif self.state == GameState.RIVER:
                self._deal_community(1)
                self._handle_betting_round()
                if self._check_round_end():
                    self.state = GameState.SHOWDOWN
            elif self.state == GameState.SHOWDOWN:
                self._handle_showdown()
                self.state = GameState.END
            elif self.state == GameState.END:
                self._handle_end()
                self.state = GameState.WAITING

    def _handle_deal(self):
        self.log("\n--- NEW HAND ---")
        self.deck.reset()
        self.community_cards = []
        self.pot_manager = PotManager()
        self.bet_manager.reset_round()
        
        # Reset players and collect active ones
        active_players = []
        for p in self.players:
            p.reset_for_hand()
            if p.is_active:
                active_players.append(p)
                
        if len(active_players) < 2:
            self.log("Not enough players with chips.")
            self.state = GameState.WAITING
            return

        # Deal 2 cards to each active player
        for p in active_players:
            cards = self.deck.draw(2)
            if not isinstance(cards, list):
                cards = [cards]
            p.receive_cards(cards)

        self.state = GameState.PREFLOP

    def _deal_community(self, count: int):
        self.pot_manager.calculate_pots([p.player_id for p in self.players if p.is_active])
        self.bet_manager.reset_round()
        
        cards = self.deck.draw(count)
        if not isinstance(cards, list):
            cards = [cards]
        self.community_cards.extend(cards)
        self.log(f"Dealing community cards: {cards}")

    def _handle_betting_round(self):
        # Simplified betting loop. In a real terminal async game, we'd wait for input.
        # Since this is local, we just loop until betting is done.
        active_players = [p for p in self.players if p.can_act()]
        if len(active_players) <= 1:
            return # Everyone else folded or all in
            
        # Post small/big blinds if PREFLOP
        start_idx = (self.dealer_idx + 1) % len(self.players)
        
        if self.state == GameState.PREFLOP:
            # Simplistic blind posting
            sb_player = self.players[(self.dealer_idx + 1) % len(self.players)]
            bb_player = self.players[(self.dealer_idx + 2) % len(self.players)]
            
            sb_amt = sb_player.lose_chips(self.big_blind // 2)
            self.pot_manager.add_contribution(sb_player.player_id, sb_amt)
            self.bet_manager.process_bet(sb_player.player_id, sb_amt)
            self.log(f"{sb_player.name:<15} posts SB: {sb_amt}")
            
            bb_amt = bb_player.lose_chips(self.big_blind)
            self.pot_manager.add_contribution(bb_player.player_id, bb_amt)
            self.bet_manager.process_bet(bb_player.player_id, bb_amt)
            self.log(f"{bb_player.name:<15} posts BB: {bb_amt}")
            
            start_idx = (self.dealer_idx + 3) % len(self.players)

        players_to_act = active_players.copy()
        current_idx = start_idx
        
        while players_to_act:
            p = self.players[current_idx]
            if p in players_to_act and p.can_act():
                game_state_data = {
                    'min_call': self.bet_manager.get_amount_to_call(p.player_id),
                    'min_raise': self.bet_manager.min_raise,
                    'pot_size': self.pot_manager.total_pot(),
                    'community_cards': self.community_cards,
                    'players_info': [(other.name, other.chips, other.is_active) for other in self.players]
                }
                
                action, amt = p.get_action(game_state_data)
                self.log(f"{p.name:<15} actions:  {action:<6}  {amt}")
                
                if action == PlayerAction.FOLD:
                    p.fold()
                    players_to_act.remove(p)
                else:
                    actual_deducted = p.lose_chips(amt)
                    self.pot_manager.add_contribution(p.player_id, actual_deducted)
                    
                    if action in (PlayerAction.RAISE, PlayerAction.ALL_IN) and actual_deducted > self.bet_manager.get_amount_to_call(p.player_id):
                        self.bet_manager.process_bet(p.player_id, actual_deducted, is_raise=True)
                        # Everyone else has to act again
                        players_to_act = [other for other in self.players if other.can_act() and other != p]
                    else:
                        self.bet_manager.process_bet(p.player_id, actual_deducted, is_raise=False)
                        players_to_act.remove(p)
                        
            current_idx = (current_idx + 1) % len(self.players)
            
            # Check if only 1 player left active
            if len([p for p in self.players if p.is_active]) == 1:
                break

    def _check_round_end(self) -> bool:
        active_players = [p for p in self.players if p.is_active]
        if len(active_players) <= 1:
            self.state = GameState.SHOWDOWN
            return False
        return True

    def _handle_showdown(self):
        self.log("\n--- SHOWDOWN ---")
        self.log(f"Community Cards: {self.community_cards}")
        self.pot_manager.calculate_pots([p.player_id for p in self.players if p.is_active])
        
        for pot in self.pot_manager.pots:
            if not pot.eligible_players:
                continue
                
            eligible = [p for p in self.players if p.player_id in pot.eligible_players and p.is_active]
            
            if len(eligible) == 1:
                winner = eligible[0]
                winner.win_chips(pot.amount)
                self.log(f"{winner.name} wins {pot.amount} uncalled")
                continue
                
            best_score = None
            winners = []
            
            for p in eligible:
                score, best_hand = HandEvaluator.evaluate(p.hole_cards, self.community_cards)
                self.log(f"{p.name:<15} shows {str(p.hole_cards):<12} -> Best 5: {best_hand} (score: {score[0]})")
                if best_score is None or score > best_score:
                    best_score = score
                    winners = [p]
                elif score == best_score:
                    winners.append(p)
                    
            split_amount = pot.amount // len(winners)
            for w in winners:
                w.win_chips(split_amount)
                self.log(f"{w.name} wins {split_amount} from pot")

    def _handle_end(self):
        self.dealer_idx = (self.dealer_idx + 1) % len(self.players)
        self.log("Hand complete.")
