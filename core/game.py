"""Game - Main poker game engine."""

from typing import List, Dict, Optional, Tuple

from core.state import GameState
from core.deck import Deck, Card
from core.betting import BetManager, PotManager
from core.player import Player, PlayerAction
from core.stats_tracker import StatsTracker
from core.showdown import ShowdownHandler, ShowdownResult
from core.blind_scheduler import BlindScheduler

_NUM_BLIND_LEVELS = 10


def _position_label(i: int, n: int, heads_up: bool) -> str:
    """Return a poker position name given seat index i in active seat order (0=SB)."""
    if heads_up:
        return 'BTN/SB' if i == 0 else 'BB'
    if i == 0:
        return 'SB'
    if i == 1:
        return 'BB'
    if i == n - 1:
        return 'BTN'
    if i == n - 2 and n >= 4:
        return 'CO'
    if i == n - 3 and n >= 6:
        return 'HJ'
    if i == 2 and n >= 5:
        return 'UTG'
    return 'MP'


class Game:
    """Main poker game engine managing game flow, dealing, and betting."""

    def __init__(self, big_blind: int, hands_per_level: int = 5,
                 ante: bool = False, live_output: bool = False,
                 game_mode: str = 'tournament', short_deck: bool = False,
                 blind_reset_interval: int = 0) -> None:
        """
        Args:
            big_blind: Big blind amount
            hands_per_level: Number of hands before blind escalation
            ante: Whether antes are enabled
            live_output: Whether to print output in real-time
            game_mode: 'tournament' or 'cash'
            short_deck: Use 36-card deck (6+)
            blind_reset_interval: Reset blinds every N hands (0=never, used in simulation mode)
        """
        self.players: List[Player] = []
        self.deck = Deck(min_rank=6 if short_deck else 2)
        self.state = GameState.WAITING
        self.big_blind = big_blind
        self.blind_scheduler = BlindScheduler(big_blind, ante_enabled=ante)
        self.hands_per_level = hands_per_level
        self.bet_manager = BetManager(big_blind)
        self.pot_manager = PotManager()
        self.showdown_handler = ShowdownHandler(short_deck=short_deck)
        self.stats_tracker = StatsTracker()
        self.community_cards: List[Card] = []
        self.dealer_idx = 0
        self.hand_count = 0
        self.logs: List[str] = []
        self.live_output = live_output
        self.pending_msg: str = ""
        self.game_mode = game_mode
        self.short_deck = short_deck
        self.blind_reset_interval = blind_reset_interval  # For simulation mode

        # Per-hand tracking
        self.player_roles: Dict[str, str] = {}
        self.fold_streets: Dict[str, str] = {}
        self.current_street: str = 'preflop'
        
        # Last hand results (for bot notifications)
        self._last_hand_result: Optional[ShowdownResult] = None

    @property
    def stats(self) -> Dict[str, dict]:
        """Access the stats tracker's stats dictionary."""
        return self.stats_tracker.stats

    def log(self, msg: str):
        self.logs.append(msg)
        if self.live_output:
            print(msg)

    def add_player(self, player: Player) -> None:
        """Add a player to the game and initialize their stats."""
        self.players.append(player)
        self.stats_tracker.register_player(player)

    def remove_player(self, player_id: str) -> None:
        """Remove a player from the game."""
        self.players = [p for p in self.players if p.player_id != player_id]

    def start_game(self) -> None:
        """Start the game if there are enough players."""
        if len(self.players) < 2:
            self.log("Not enough players to start.")
            return
        self.state = GameState.DEAL
        self.run_cycle()

    def run_cycle(self) -> None:
        """Run the game cycle until we return to WAITING state."""
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

    # ── Log format constants ─────────────────────────────────────────────────
    _NAME_W     = 15
    _ACT_W      = 10
    _AMT_W      = 6
    _DEAL_INDENT = 55

    def _log_action(self, name: str, label: str, amt: int) -> None:
        """Log a player action with pot information."""
        pot = self.pot_manager.total_pot()
        self.log(f"{name:<{self._NAME_W}} {label:<{self._ACT_W}} {amt:>{self._AMT_W}}    Pot: {pot}")

    def _deal_community(self, count: int) -> None:
        """Deal community cards for flop/turn/river."""
        self.bet_manager.reset_round()
        street_names = {0: 'FLOP', 3: 'TURN', 4: 'RIVER'}
        street = street_names.get(len(self.community_cards), '')
        if street:
            self.log(f"\n--- {street} ---")
            self.current_street = street.lower()
        cards = self.deck.draw(count)
        self.community_cards.extend(cards)
        self.log(f"{'':>{self._DEAL_INDENT}}{cards}")

    # ── Deal ─────────────────────────────────────────────────────────────────

    def _handle_deal(self) -> None:
        """Handle the deal phase: reset state, post blinds, deal cards."""
        self.hand_count += 1
        self.fold_streets = {}
        self.current_street = 'preflop'

        if self.pending_msg:
            self.log(self.pending_msg)
            self.pending_msg = ""

        mode_tag = ""
        if self.game_mode == 'cash':
            mode_tag = "  |  Cash Game"
        elif self.short_deck:
            mode_tag = "  |  Short Deck"
        ante_info = f"  |  Ante: {self.blind_scheduler.ante}" if self.blind_scheduler.ante > 0 else ""
        self.log(f"\n--- NEW HAND ---")
        self.log(f"Hand #{self.hand_count}  |  Blinds: {self.blind_scheduler.small_blind}/{self.big_blind}"
                 f"  |  Level {self.blind_scheduler.current_level + 1}{ante_info}{mode_tag}")

        self.deck.reset()
        self.community_cards = []
        self.pot_manager = PotManager()
        self.bet_manager.reset_round()

        active_players: List[Player] = []
        for p in self.players:
            p.reset_for_hand()
            if p.is_active:
                active_players.append(p)

        if len(active_players) < 2:
            self.log("Not enough players with chips.")
            self.state = GameState.WAITING
            return

        n = len(self.players)
        heads_up = len(active_players) == 2
        dealer_p = self.players[self.dealer_idx]

        if heads_up:
            sb_p = dealer_p
            bb_p = self.players[(self.dealer_idx + 1) % n]
        else:
            sb_p = self.players[(self.dealer_idx + 1) % n]
            bb_p = self.players[(self.dealer_idx + 2) % n]

        sb_seat = self.players.index(sb_p)
        seat_order = [
            self.players[(sb_seat + i) % n]
            for i in range(n)
            if self.players[(sb_seat + i) % n] in active_players
        ]

        # Compute position labels
        n_active = len(seat_order)
        self.player_roles = {
            p.player_id: _position_label(i, n_active, heads_up)
            for i, p in enumerate(seat_order)
        }

        # Increment hands_played for all active players
        for p in active_players:
            self.stats_tracker.increment_hands_played(p.player_id)

        self.log("Turn order:")
        for p in seat_order:
            role = self.player_roles.get(p.player_id, '')
            # Show strategy style for bots
            strategy = getattr(p, 'strategy', None)
            if strategy:
                profile = getattr(strategy, 'profile', None)
                diff = getattr(strategy, 'difficulty', None)
                if profile:
                    style_tag = f"  [{profile.name}, {diff:.1f}]"
                else:
                    agg = getattr(strategy, 'aggressiveness', None)
                    style_tag = f"  [simple, {agg:.1f}]" if agg is not None else ""
            else:
                style_tag = "  [human]"
            self.log(f"  {p.name:<{self._NAME_W}} [{role:<6}]  chips: {p.chips}{style_tag}")

        for p in active_players:
            p.receive_cards(self.deck.draw(2))

        self.state = GameState.PREFLOP

    # ── Betting round ────────────────────────────────────────────────────────

    def _handle_betting_round(self) -> None:
        """Handle a round of betting."""
        if len([p for p in self.players if p.can_act()]) <= 1:
            return

        n = len(self.players)
        active_count = len([p for p in self.players if p.is_active])
        heads_up = active_count == 2

        # Default: BB or player after BB acts first
        start_idx = (self.dealer_idx + 1) % n

        if self.state == GameState.PREFLOP:
            self.log("\n--- PREFLOP ---")

            if self.blind_scheduler.ante > 0:
                for p in [x for x in self.players if x.is_active]:
                    ante_amt = p.lose_chips(self.blind_scheduler.ante)
                    self.pot_manager.add_contribution(p.player_id, ante_amt)
                    self._log_action(p.name, "ante", ante_amt)

            if heads_up:
                # Heads-up: SB (dealer) acts first preflop, BB acts first postflop
                sb_player = self.players[self.dealer_idx]
                bb_player = self.players[(self.dealer_idx + 1) % n]
                start_idx = self.dealer_idx  # SB acts first preflop
            else:
                # Full ring: SB posts, BB posts, UTG+ (after BB) acts first
                sb_player = self.players[(self.dealer_idx + 1) % n]
                bb_player = self.players[(self.dealer_idx + 2) % n]
                start_idx = (self.dealer_idx + 3) % n

            sb_amt = sb_player.lose_chips(self.big_blind // 2)
            self.pot_manager.add_contribution(sb_player.player_id, sb_amt)
            self.bet_manager.process_bet(sb_player.player_id, sb_amt)
            self._log_action(sb_player.name, "posts SB", sb_amt)

            bb_amt = bb_player.lose_chips(self.big_blind)
            self.pot_manager.add_contribution(bb_player.player_id, bb_amt)
            self.bet_manager.process_bet(bb_player.player_id, bb_amt)
            self._log_action(bb_player.name, "posts BB", bb_amt)
        else:
            # Postflop betting rounds
            if heads_up:
                # Heads-up postflop: BB (non-dealer) acts first
                start_idx = (self.dealer_idx + 1) % n
            else:
                # Full ring postflop: SB (first active after dealer) acts first
                start_idx = (self.dealer_idx + 1) % n

        players_to_act: List[Player] = [p for p in self.players if p.can_act()]
        current_idx = start_idx
        iterations_without_progress = 0
        max_iterations = len(players_to_act) * 2 + 10  # Prevent infinite loops

        while players_to_act and iterations_without_progress < max_iterations:
            p = self.players[current_idx]

            # Skip players who are no longer in the list or can't act
            if p not in players_to_act or not p.can_act():
                # Remove from players_to_act if they can't act anymore (e.g., went all-in)
                if p in players_to_act and not p.can_act():
                    players_to_act.remove(p)
                current_idx = (current_idx + 1) % n
                continue

            iterations_without_progress += 1

            role = self.player_roles.get(p.player_id, '')
            game_state_data = {
                'min_call':       self.bet_manager.get_amount_to_call(p.player_id),
                'min_raise':      self.bet_manager.min_raise,
                'pot_size':       self.pot_manager.total_pot(),
                'community_cards': self.community_cards,
                'players_info':   [(o.name, o.chips, o.is_active) for o in self.players],
                'position':       (self.players.index(p) - self.dealer_idx) % n,
                'player_role':    role,
                'num_active':     active_count,
                'hand_log':       list(self.logs),
            }

            action, amt = p.get_action(game_state_data)

            if action == PlayerAction.FOLD:
                p.fold()
                players_to_act.remove(p)
                self._log_action(p.name, "fold", 0)
                self.fold_streets[p.player_id] = self.current_street
            else:
                actual_deducted = p.lose_chips(amt)
                self.pot_manager.add_contribution(p.player_id, actual_deducted)

                if action in (PlayerAction.RAISE, PlayerAction.ALL_IN) and \
                        actual_deducted > self.bet_manager.get_amount_to_call(p.player_id):
                    self.bet_manager.process_bet(p.player_id, actual_deducted, is_raise=True)
                    # A raise reopens betting for all active players except the raiser
                    players_to_act = [o for o in self.players if o.can_act() and o != p]
                else:
                    self.bet_manager.process_bet(p.player_id, actual_deducted, is_raise=False)
                    players_to_act.remove(p)

                self._log_action(p.name, action.value, actual_deducted)

                if action == PlayerAction.ALL_IN:
                    self.log(f">> {p.name} is ALL-IN")

            current_idx = (current_idx + 1) % n

            # Check if only one player remains active
            if len([p for p in self.players if p.is_active]) == 1:
                break

        # Safety check: if we hit max iterations, force end the betting round
        if iterations_without_progress >= max_iterations:
            self.log("WARNING: Betting round terminated due to excessive iterations")

    def _is_hand_over(self) -> bool:
        return len([p for p in self.players if p.is_active]) <= 1

    # ── Showdown ─────────────────────────────────────────────────────────────

    def _handle_showdown(self) -> None:
        """Handle the showdown: evaluate hands and distribute pots."""
        self.log("\n--- SHOWDOWN ---")
        self.log(f"Community: {self.community_cards}")

        # Show folded players
        folded = [(p, self.fold_streets.get(p.player_id, 'preflop'))
                  for p in self.players
                  if not p.is_active and p.chips > 0 or
                     (not p.is_active and p.player_id in self.fold_streets)]
        for p, street in folded:
            self.log(f"{p.name:<{self._NAME_W}} folded on {street}")

        self.pot_manager.calculate_pots([p.player_id for p in self.players if p.is_active])

        # Evaluate active players
        active_players: List[Player] = [p for p in self.players if p.is_active]
        hand_scores: Dict[str, Tuple[tuple, str, str]] = {}
        
        if len(active_players) > 1:
            hand_scores = self.showdown_handler.evaluate_hands(
                active_players, self.community_cards
            )
            for p in active_players:
                if p.player_id in hand_scores:
                    score, hand_name, best_hand_cards = hand_scores[p.player_id]
                    self.log(f"{p.name:<{self._NAME_W}} shows {str(p.hole_cards):<14}"
                             f"-> {best_hand_cards}  ({hand_name})")

        # Show pot structure
        if len(self.pot_manager.pots) > 1:
            self.log("")
            id_to_name = {p.player_id: p.name for p in self.players}
            for i, pot in enumerate(self.pot_manager.pots):
                label = "Main Pot" if i == 0 else f"Side Pot {i}"
                eligible_names = ', '.join(
                    id_to_name.get(pid, pid) for pid in sorted(pot.eligible_players))
                self.log(f"  {label}: {pot.amount}  (eligible: {eligible_names})")

        # Distribute pots using ShowdownHandler
        self._last_hand_result = self.showdown_handler.distribute_pots(
            self.pot_manager.pots,
            self.players,
            {pid: score for pid, (score, _, _) in hand_scores.items()},
            self.dealer_idx,
            len(self.players)
        )

        self.log("")
        for player_id, amount in self._last_hand_result.winnings.items():
            winner = next(p for p in self.players if p.player_id == player_id)
            self.log(f">> {winner.name} wins {amount}")

        # Update stats using StatsTracker
        for player_id, amount in self._last_hand_result.winnings.items():
            self.stats_tracker.record_win(player_id, amount)

        for p in active_players:
            if p.player_id in hand_scores:
                score, hand_name, _ = hand_scores[p.player_id]
                self.stats_tracker.update_best_hand(
                    p.player_id, score[0], hand_name
                )

    # ── End ──────────────────────────────────────────────────────────────────

    def _handle_end(self) -> None:
        """Handle end-of-hand processing: bust tracking, bot notifications, blind escalation."""
        # Record bust hands
        for p in self.players:
            if p.chips == 0:
                self.stats_tracker.record_bust(p.player_id, self.hand_count)

        # Notify bots of hand results for dynamic behavior (tilt, image, tracking)
        if self._last_hand_result is not None:
            for p in self.players:
                if hasattr(p, 'record_hand_result'):
                    won = p.player_id in self._last_hand_result.winners
                    amount = self._last_hand_result.winnings.get(p.player_id, 0)
                    # TODO: Track actual pre-showdown equity for accurate "was_favorite"
                    was_fav = won  # Simplified placeholder
                    p.record_hand_result(won, amount, was_fav)

        # Rotate dealer to next active player
        n = len(self.players)
        for _ in range(n):
            self.dealer_idx = (self.dealer_idx + 1) % n
            if self.players[self.dealer_idx].chips > 0:
                break

        # Only escalate blinds in tournament mode
        if self.game_mode == 'tournament':
            msg = self.blind_scheduler.escalate_blinds(self.hand_count, self.hands_per_level)
            if msg:
                # Update bet manager with new blind levels
                self.big_blind = self.blind_scheduler.big_blind
                self.bet_manager.big_blind = self.big_blind
                self.bet_manager.min_raise = self.big_blind
                self.pending_msg = msg
            
            # Reset blinds periodically in simulation mode to prevent snowballing
            if self.blind_reset_interval > 0 and self.hand_count % self.blind_reset_interval == 0:
                # Full session reset: blinds, chips, bust states (like new table)
                self.blind_scheduler.reset()
                self.big_blind = self.blind_scheduler.big_blind
                self.bet_manager.big_blind = self.big_blind
                self.bet_manager.min_raise = self.big_blind
                
                # Reset player state for new session (chips, active status, bust tracking)
                self.stats_tracker.reset_session_state(self.players)
                
                # Log session boundary (even in simulation mode, stored in logs)
                session_num = self.hand_count // self.blind_reset_interval
                self.log(f"*** SESSION {session_num + 1} START — Fresh table, blinds reset ***")

        self.log("Hand complete.")

    def print_stats(self) -> None:
        """Print enhanced session statistics with visual formatting."""
        self.stats_tracker.print_stats(self.players)

