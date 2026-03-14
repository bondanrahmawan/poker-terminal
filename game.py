from typing import List, Dict
from state import GameState
from deck import Deck
from betting import BetManager, PotManager
from player import Player, PlayerAction
from evaluator import HandEvaluator, HandRank

class Game:
    def __init__(self, big_blind: int, live_output: bool = False):
        self.players: List[Player] = []
        self.deck = Deck()
        self.state = GameState.WAITING
        self.bet_manager = BetManager(big_blind)
        self.pot_manager = PotManager()
        self.community_cards = []
        self.big_blind = big_blind
        self.dealer_idx = 0
        self.logs = []
        self.live_output = live_output

    def log(self, msg: str):
        self.logs.append(msg)
        if self.live_output:
            print(msg)

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
        while self.state != GameState.WAITING:
            if self.state == GameState.DEAL:
                self._handle_deal()
            elif self.state == GameState.PREFLOP:
                self._handle_betting_round()
                self.state = GameState.SHOWDOWN if self._is_hand_over() else GameState.FLOP
            elif self.state == GameState.FLOP:
                self._deal_community(3)
                self._handle_betting_round()
                self.state = GameState.SHOWDOWN if self._is_hand_over() else GameState.TURN
            elif self.state == GameState.TURN:
                self._deal_community(1)
                self._handle_betting_round()
                self.state = GameState.SHOWDOWN if self._is_hand_over() else GameState.RIVER
            elif self.state == GameState.RIVER:
                self._deal_community(1)
                self._handle_betting_round()
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

        active_players = []
        for p in self.players:
            p.reset_for_hand()
            if p.is_active:
                active_players.append(p)

        if len(active_players) < 2:
            self.log("Not enough players with chips.")
            self.state = GameState.WAITING
            return

        # Show turn order for the new hand
        n = len(self.players)
        dealer_player = self.players[self.dealer_idx]
        sb_player = self.players[(self.dealer_idx + 1) % n]
        bb_player = self.players[(self.dealer_idx + 2) % n]

        self.log("Turn order:")
        for i, p in enumerate(active_players):
            if p == dealer_player:
                role = "[Dealer]"
            elif p == sb_player:
                role = "[SB]"
            elif p == bb_player:
                role = "[BB]"
            else:
                role = ""
            self.log(f"  {i + 1}. {p.name:<{self._NAME_W}} {role:<10} chips: {p.chips}")

        for p in active_players:
            cards = self.deck.draw(2)
            p.receive_cards(cards)

        self.state = GameState.PREFLOP

    # Log format constants:
    #   action rows:  {name:<15} {label:<10} {amt:>6}    Pot: {pot}
    #   dealing rows: {' ':>34}>> {cards}   (pushed past the action columns)
    _NAME_W  = 15
    _ACT_W   = 10
    _AMT_W   = 6
    _DEAL_INDENT = 55

    def _log_action(self, name: str, label: str, amt: int):
        pot = self.pot_manager.total_pot()
        self.log(f"{name:<{self._NAME_W}} {label:<{self._ACT_W}} {amt:>{self._AMT_W}}    Pot: {pot}")

    def _deal_community(self, count: int):
        self.bet_manager.reset_round()
        cards = self.deck.draw(count)
        self.community_cards.extend(cards)
        self.log(f"{'>> ':<{self._DEAL_INDENT}}{cards}")

    def _handle_betting_round(self):
        if len([p for p in self.players if p.can_act()]) <= 1:
            return

        start_idx = (self.dealer_idx + 1) % len(self.players)

        if self.state == GameState.PREFLOP:
            sb_player = self.players[(self.dealer_idx + 1) % len(self.players)]
            bb_player = self.players[(self.dealer_idx + 2) % len(self.players)]

            sb_amt = sb_player.lose_chips(self.big_blind // 2)
            self.pot_manager.add_contribution(sb_player.player_id, sb_amt)
            self.bet_manager.process_bet(sb_player.player_id, sb_amt)
            self._log_action(sb_player.name, "posts SB", sb_amt)

            bb_amt = bb_player.lose_chips(self.big_blind)
            self.pot_manager.add_contribution(bb_player.player_id, bb_amt)
            self.bet_manager.process_bet(bb_player.player_id, bb_amt)
            self._log_action(bb_player.name, "posts BB", bb_amt)

            start_idx = (self.dealer_idx + 3) % len(self.players)

        # Build players_to_act AFTER blinds so any all-in blind posters are excluded
        players_to_act = [p for p in self.players if p.can_act()]
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

                if action == PlayerAction.FOLD:
                    p.fold()
                    players_to_act.remove(p)
                    self._log_action(p.name, "fold", 0)
                else:
                    actual_deducted = p.lose_chips(amt)
                    self.pot_manager.add_contribution(p.player_id, actual_deducted)

                    if action in (PlayerAction.RAISE, PlayerAction.ALL_IN) and actual_deducted > self.bet_manager.get_amount_to_call(p.player_id):
                        self.bet_manager.process_bet(p.player_id, actual_deducted, is_raise=True)
                        players_to_act = [other for other in self.players if other.can_act() and other != p]
                    else:
                        self.bet_manager.process_bet(p.player_id, actual_deducted, is_raise=False)
                        players_to_act.remove(p)

                    self._log_action(p.name, action.value, actual_deducted)

            current_idx = (current_idx + 1) % len(self.players)

            if len([p for p in self.players if p.is_active]) == 1:
                break

    def _is_hand_over(self) -> bool:
        return len([p for p in self.players if p.is_active]) <= 1

    def _handle_showdown(self):
        self.log("\n--- SHOWDOWN ---")
        self.log(f"Community: {self.community_cards}")
        self.pot_manager.calculate_pots([p.player_id for p in self.players if p.is_active])

        # Evaluate and display each active player's hand exactly once
        scores: Dict[str, tuple] = {}
        active_players = [p for p in self.players if p.is_active]
        if len(active_players) > 1:
            for p in active_players:
                score, best_hand = HandEvaluator.evaluate(p.hole_cards, self.community_cards)
                hand_name = HandRank.to_string(score[0])
                self.log(f"{p.name:<{self._NAME_W}} shows {str(p.hole_cards):<14}-> {best_hand}  ({hand_name})")
                scores[p.player_id] = score

        total_winnings: Dict[str, int] = {}

        for pot in self.pot_manager.pots:
            if not pot.eligible_players:
                continue

            eligible = [p for p in self.players if p.player_id in pot.eligible_players and p.is_active]

            if len(eligible) == 1:
                winner = eligible[0]
                winner.win_chips(pot.amount)
                total_winnings[winner.player_id] = total_winnings.get(winner.player_id, 0) + pot.amount
                continue

            best_score = None
            winners = []

            for p in eligible:
                score = scores[p.player_id]
                if best_score is None or score > best_score:
                    best_score = score
                    winners = [p]
                elif score == best_score:
                    winners.append(p)

            split_amount = pot.amount // len(winners)
            for w in winners:
                w.win_chips(split_amount)
                total_winnings[w.player_id] = total_winnings.get(w.player_id, 0) + split_amount

        # Single consolidated result line per winner
        for player_id, amount in total_winnings.items():
            winner = next(p for p in self.players if p.player_id == player_id)
            self.log(f">> {winner.name} wins {amount}")

    def _handle_end(self):
        # Advance dealer to the next player who still has chips
        n = len(self.players)
        for _ in range(n):
            self.dealer_idx = (self.dealer_idx + 1) % n
            if self.players[self.dealer_idx].chips > 0:
                break
        self.log("Hand complete.")
