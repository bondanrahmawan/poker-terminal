from typing import List, Dict
from core.state import GameState
from core.deck import Deck
from core.betting import BetManager, PotManager
from core.player import Player, PlayerAction
from core.evaluator import HandEvaluator, HandRank

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
    def __init__(self, big_blind: int, hands_per_level: int = 5,
                 ante: bool = False, live_output: bool = False,
                 game_mode: str = 'tournament', short_deck: bool = False):
        """
        game_mode : 'tournament' (escalating blinds) or 'cash' (fixed blinds)
        short_deck: use 36-card deck (6+); Flush beats Full House
        """
        self.players: List[Player] = []
        self.deck = Deck(min_rank=6 if short_deck else 2)
        self.state = GameState.WAITING
        self.big_blind = big_blind
        self.blind_schedule = [big_blind * (i + 1) for i in range(_NUM_BLIND_LEVELS)]
        self.blind_level = 0
        self.hands_per_level = hands_per_level
        self.ante_enabled = ante
        self.ante = (big_blind // 10) if ante else 0
        self.bet_manager = BetManager(big_blind)
        self.pot_manager = PotManager()
        self.community_cards = []
        self.dealer_idx = 0
        self.hand_count = 0
        self.logs = []
        self.live_output = live_output
        self.stats: Dict[str, dict] = {}
        self.pending_msg: str = ""
        self.game_mode = game_mode
        self.short_deck = short_deck
        # Per-hand tracking
        self.player_roles: Dict[str, str] = {}   # player_id -> position label
        self.fold_streets: Dict[str, str] = {}   # player_id -> street name when folded
        self.current_street: str = 'preflop'
        # Bot tracking — populated during showdown, consumed in _handle_end
        self._last_hand_winners: List[str] = []
        self._last_hand_winnings: Dict[str, int] = {}

    def log(self, msg: str):
        self.logs.append(msg)
        if self.live_output:
            print(msg)

    def add_player(self, player: Player):
        self.players.append(player)
        self.stats[player.player_id] = {
            'hands_won': 0,
            'hands_played': 0,
            'chips_won': 0,
            'biggest_pot': 0,
            'best_hand_rank': 0,
            'best_hand_name': '-',
            'bust_hand': None,
            'rebuys': 0,
            'starting_chips': player.chips,
        }

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

    # ── Log format constants ─────────────────────────────────────────────────
    _NAME_W     = 15
    _ACT_W      = 10
    _AMT_W      = 6
    _DEAL_INDENT = 55

    def _log_action(self, name: str, label: str, amt: int):
        pot = self.pot_manager.total_pot()
        self.log(f"{name:<{self._NAME_W}} {label:<{self._ACT_W}} {amt:>{self._AMT_W}}    Pot: {pot}")

    def _deal_community(self, count: int):
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

    def _handle_deal(self):
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
        ante_info = f"  |  Ante: {self.ante}" if self.ante > 0 else ""
        self.log(f"\n--- NEW HAND ---")
        self.log(f"Hand #{self.hand_count}  |  Blinds: {self.big_blind // 2}/{self.big_blind}"
                 f"  |  Level {self.blind_level + 1}{ante_info}{mode_tag}")

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
            self.stats[p.player_id]['hands_played'] += 1

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

    def _handle_betting_round(self):
        if len([p for p in self.players if p.can_act()]) <= 1:
            return

        n = len(self.players)
        active_count = len([p for p in self.players if p.is_active])
        heads_up = active_count == 2

        # Default: BB or player after BB acts first
        start_idx = (self.dealer_idx + 1) % n

        if self.state == GameState.PREFLOP:
            self.log("\n--- PREFLOP ---")

            if self.ante > 0:
                for p in [x for x in self.players if x.is_active]:
                    ante_amt = p.lose_chips(self.ante)
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

        players_to_act = [p for p in self.players if p.can_act()]
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

    def _handle_showdown(self):
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
        scores: Dict[str, tuple] = {}
        active_players = [p for p in self.players if p.is_active]
        if len(active_players) > 1:
            for p in active_players:
                score, best_hand = HandEvaluator.evaluate(
                    p.hole_cards, self.community_cards, short_deck=self.short_deck)
                hand_name = HandRank.to_string(score[0], short_deck=self.short_deck)
                self.log(f"{p.name:<{self._NAME_W}} shows {str(p.hole_cards):<14}"
                         f"-> {best_hand}  ({hand_name})")
                scores[p.player_id] = score

        # Show pot structure
        if len(self.pot_manager.pots) > 1:
            self.log("")
            id_to_name = {p.player_id: p.name for p in self.players}
            for i, pot in enumerate(self.pot_manager.pots):
                label = "Main Pot" if i == 0 else f"Side Pot {i}"
                eligible_names = ', '.join(
                    id_to_name.get(pid, pid) for pid in sorted(pot.eligible_players))
                self.log(f"  {label}: {pot.amount}  (eligible: {eligible_names})")

        # Distribute pots
        total_winnings: Dict[str, int] = {}
        for pot in self.pot_manager.pots:
            if not pot.eligible_players:
                continue
            eligible = [p for p in self.players
                        if p.player_id in pot.eligible_players and p.is_active]
            if len(eligible) == 1:
                winner = eligible[0]
                winner.win_chips(pot.amount)
                total_winnings[winner.player_id] = \
                    total_winnings.get(winner.player_id, 0) + pot.amount
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
            remainder = pot.amount - split_amount * len(winners)
            for w in winners:
                w.win_chips(split_amount)
                total_winnings[w.player_id] = \
                    total_winnings.get(w.player_id, 0) + split_amount
            if remainder > 0:
                first_winner = min(
                    winners,
                    key=lambda p: (self.players.index(p) - self.dealer_idx - 1) % len(self.players)
                )
                first_winner.win_chips(remainder)
                total_winnings[first_winner.player_id] = \
                    total_winnings.get(first_winner.player_id, 0) + remainder

        self.log("")
        for player_id, amount in total_winnings.items():
            winner = next(p for p in self.players if p.player_id == player_id)
            self.log(f">> {winner.name} wins {amount}")

        # Store for bot record_hand_result() in _handle_end()
        self._last_hand_winners = list(total_winnings.keys())
        self._last_hand_winnings = dict(total_winnings)

        # Update stats
        for player_id, amount in total_winnings.items():
            s = self.stats[player_id]
            s['hands_won'] += 1
            s['chips_won'] += amount
            if amount > s['biggest_pot']:
                s['biggest_pot'] = amount

        for p in active_players:
            if p.player_id in scores:
                rank = scores[p.player_id][0]
                s = self.stats[p.player_id]
                if rank > s['best_hand_rank']:
                    s['best_hand_rank'] = rank
                    s['best_hand_name'] = HandRank.to_string(rank, short_deck=self.short_deck)

    # ── End ──────────────────────────────────────────────────────────────────

    def _handle_end(self):
        for p in self.players:
            if p.chips == 0 and self.stats[p.player_id]['bust_hand'] is None:
                self.stats[p.player_id]['bust_hand'] = self.hand_count

        # Notify bots of hand results for dynamic behavior (tilt, image, tracking)
        for p in self.players:
            if hasattr(p, 'record_hand_result'):
                won = p.player_id in self._last_hand_winners
                amount = self._last_hand_winnings.get(p.player_id, 0)
                # Rough estimate: was favorite if they had best hand at showdown
                was_fav = won  # simplified; could be improved with pre-hand equity
                p.record_hand_result(won, amount, was_fav)

        n = len(self.players)
        for _ in range(n):
            self.dealer_idx = (self.dealer_idx + 1) % n
            if self.players[self.dealer_idx].chips > 0:
                break

        # Only escalate blinds in tournament mode
        if self.game_mode == 'tournament':
            if self.hand_count % self.hands_per_level == 0:
                next_level = self.blind_level + 1
                if next_level < len(self.blind_schedule):
                    self.blind_level = next_level
                    self.big_blind = self.blind_schedule[self.blind_level]
                    self.bet_manager.big_blind = self.big_blind
                    self.bet_manager.min_raise = self.big_blind
                    if self.ante_enabled:
                        self.ante = max(1, self.big_blind // 10)
                    ante_info = f"  Ante: {self.ante}" if self.ante > 0 else ""
                    self.pending_msg = (
                        f"*** BLIND LEVEL UP — Blinds: {self.big_blind // 2}/{self.big_blind}"
                        f"{ante_info} ***"
                    )

        self.log("Hand complete.")

    # ── Stats ────────────────────────────────────────────────────────────────

    @staticmethod
    def _strategy_label(player: 'Player') -> str:
        """Return a short strategy description for display in stats."""
        strategy = getattr(player, 'strategy', None)
        if strategy is None:
            return 'human'
        profile = getattr(strategy, 'profile', None)
        diff = getattr(strategy, 'difficulty', None)
        if profile:
            diff_str = f"{diff:.1f}" if diff is not None else '?'
            return f"{profile.name}/{diff_str}"
        agg = getattr(strategy, 'aggressiveness', None)
        if agg is not None:
            return f"simple/{agg:.1f}"
        return strategy.__class__.__name__

    def print_stats(self):
        """Print enhanced session statistics with visual formatting."""
        import re
        # Color codes
        GREEN = '\033[92m'
        RED = '\033[91m'
        YELLOW = '\033[93m'
        CYAN = '\033[96m'
        MAGENTA = '\033[95m'
        BOLD = '\033[1m'
        DIM = '\033[2m'
        RESET = '\033[0m'

        # Helper to get visual width (strip ANSI codes)
        def visual_len(s):
            return len(re.sub(r'\033\[[0-9;]*m', '', s))

        # Helper to pad string to visual width
        def visual_ljust(s, width):
            vlen = visual_len(s)
            return s + ' ' * max(0, width - vlen)

        def visual_rjust(s, width):
            vlen = visual_len(s)
            return ' ' * max(0, width - vlen) + s
        
        # Header
        print()
        print(f"{BOLD}{CYAN}╔{'═' * 126}╗{RESET}")
        print(f"{BOLD}{CYAN}║{RESET}{BOLD}{'SESSION STATISTICS':^126}{RESET}{BOLD}{CYAN}║{RESET}")
        print(f"{BOLD}{CYAN}╠{'═' * 126}╣{RESET}")

        # Summary stats
        total_hands = sum(s['hands_played'] for s in self.stats.values())
        total_rebuys = sum(s.get('rebuys', 0) for s in self.stats.values())
        biggest_pot = max(s['biggest_pot'] for s in self.stats.values())
        best_hand = max(self.stats.values(), key=lambda x: x['best_hand_rank'])

        summary_line = (
            f"{DIM}Total Hands:{RESET} {BOLD}{total_hands:>7}{RESET}  "
            f"{DIM}|{RESET} {DIM}Total Rebuys:{RESET} {YELLOW}{total_rebuys:>6}{RESET}  "
            f"{DIM}|{RESET} {DIM}Biggest Pot:{RESET} {GREEN}{biggest_pot:>9}{RESET}  "
            f"{DIM}|{RESET} {DIM}Best Hand:{RESET} {MAGENTA}{best_hand['best_hand_name']:<15}{RESET}"
        )
        print(f"{BOLD}{CYAN}║{RESET} {visual_ljust(summary_line, 124)} {BOLD}{CYAN}║{RESET}")
        print(f"{BOLD}{CYAN}╠{'═' * 126}╣{RESET}")
        
        # Table header (carefully aligned column widths)
        # Column widths: 3+12+22+8+8+7+6+7+6+9+15+11=114 + 12 spaces = 126
        header = (
            f" {visual_rjust(f'{BOLD}#{RESET}', 3)} "
            f"{visual_ljust(f'{BOLD}Name{RESET}', 12)} "
            f"{visual_ljust(f'{BOLD}Strategy{RESET}', 22)} "
            f"{visual_rjust(f'{BOLD}Chips{RESET}', 8)} "
            f"{visual_rjust(f'{BOLD}Net{RESET}', 8)} "
            f"{visual_rjust(f'{BOLD}Played{RESET}', 7)} "
            f"{visual_rjust(f'{BOLD}Won{RESET}', 6)} "
            f"{visual_rjust(f'{BOLD}Win%{RESET}', 7)} "
            f"{visual_rjust(f'{BOLD}Rebuys{RESET}', 6)} "
            f"{visual_rjust(f'{BOLD}Big Pot{RESET}', 9)} "
            f"{visual_ljust(f'{BOLD}Best Hand{RESET}', 15)} "
            f"{visual_ljust(f'{BOLD}Status{RESET}', 11)}"
        )
        print(f"{BOLD}{CYAN}║{RESET}{header}{BOLD}{CYAN}║{RESET}")
        print(f"{BOLD}{CYAN}╠{'═' * 126}╣{RESET}")
        
        # Player rows - sorted by chips
        sorted_players = sorted(self.players, key=lambda p: p.chips, reverse=True)

        for rank, p in enumerate(sorted_players, 1):
            s = self.stats[p.player_id]
            net = p.chips - s['starting_chips']

            # Color coding for net (with proper width formatting)
            if net > 0:
                net_str = f"{GREEN}{net:>8}{RESET}"
            elif net < 0:
                net_str = f"{RED}{net:>8}{RESET}"
            else:
                net_str = f"{DIM}{0:>8}{RESET}"

            # Win percentage
            played = s['hands_played']
            won = s['hands_won']
            if played > 0:
                win_pct = won / played * 100
                if win_pct >= 50:
                    win_pct_str = f"{GREEN}{win_pct:>6.0f}%{RESET}"
                elif win_pct >= 25:
                    win_pct_str = f"{YELLOW}{win_pct:>6.0f}%{RESET}"
                else:
                    win_pct_str = f"{RED}{win_pct:>6.0f}%{RESET}"
            else:
                win_pct_str = f"{DIM}{'-':>7}{RESET}"

            # Status with icon
            if p.chips > 0:
                status = f"{GREEN}● Active{RESET}"
            elif s['bust_hand']:
                status = f"{RED}✕ Bust #{s['bust_hand']}{RESET}"
            else:
                status = f"{DIM}○ Out{RESET}"

            # Rebuys highlight (with proper width formatting)
            rebuys = s.get('rebuys', 0)
            if rebuys > 3:
                rebuys_str = f"{RED}{rebuys:>6}{RESET}"
            elif rebuys > 0:
                rebuys_str = f"{YELLOW}{rebuys:>6}{RESET}"
            else:
                rebuys_str = f"{DIM}{rebuys:>6}{RESET}"

            # Rank indicator (right-aligned numbers with color for top 3)
            if rank == 1:
                rank_str = f"{YELLOW}{rank:>3}{RESET}"
            elif rank == 2:
                rank_str = f"{DIM}{rank:>3}{RESET}"
            elif rank == 3:
                rank_str = f"{MAGENTA}{rank:>3}{RESET}"
            else:
                rank_str = f"{DIM}{rank:>3}{RESET}"

            strategy_str = self._strategy_label(p)

            # Build row with visual width alignment
            row = (
                f" {visual_rjust(rank_str, 3)} "
                f"{visual_ljust(p.name, 12)} "
                f"{visual_ljust(f'{DIM}{strategy_str}{RESET}', 22)} "
                f"{visual_rjust(f'{BOLD}{p.chips}{RESET}', 8)} "
                f"{visual_rjust(net_str, 8)} "
                f"{visual_rjust(f'{DIM}{played}{RESET}', 7)} "
                f"{visual_rjust(f'{DIM}{won}{RESET}', 6)} "
                f"{visual_rjust(win_pct_str, 7)} "
                f"{visual_rjust(rebuys_str, 6)} "
                f"{visual_rjust(f'{DIM}{s["biggest_pot"]}{RESET}', 9)} "
                f"{visual_ljust(f'{MAGENTA}{s["best_hand_name"]}{RESET}', 15)} "
                f"{visual_ljust(status, 11)}"
            )
            print(f"{BOLD}{CYAN}║{RESET}{row}{BOLD}{CYAN}║{RESET}")

        # Footer
        print(f"{BOLD}{CYAN}╚{'═' * 126}╝{RESET}")
        
        # Top performers section
        print()
        print(f"{BOLD}{DIM}  ─── TOP PERFORMERS ───{RESET}")
        
        # Best win rate (min 5 hands)
        eligible = [p for p in self.players if self.stats[p.player_id]['hands_played'] >= 5]
        if eligible:
            best_wr = max(eligible, key=lambda p: self.stats[p.player_id]['hands_won'] / max(1, self.stats[p.player_id]['hands_played']))
            best_wr_pct = self.stats[best_wr.player_id]['hands_won'] / self.stats[best_wr.player_id]['hands_played'] * 100
            print(f"  {DIM}Best Win Rate:{RESET}  {BOLD}{GREEN}{best_wr.name}{RESET} ({YELLOW}{best_wr_pct:.0f}%{RESET})")
        
        # Biggest pot winner
        biggest = max(self.players, key=lambda p: self.stats[p.player_id]['biggest_pot'])
        print(f"  {DIM}Biggest Pot:{RESET}  {BOLD}{GREEN}{biggest.name}{RESET} ({YELLOW}{self.stats[biggest.player_id]['biggest_pot']}{RESET})")
        
        # Best hand
        best = max(self.players, key=lambda p: self.stats[p.player_id]['best_hand_rank'])
        print(f"  {DIM}Best Hand:{RESET}  {BOLD}{MAGENTA}{best.name}{RESET} ({YELLOW}{self.stats[best.player_id]['best_hand_name']}{RESET})")
        
        # Most aggressive (most hands played)
        if eligible:
            most_active = max(eligible, key=lambda p: self.stats[p.player_id]['hands_played'])
            print(f"  {DIM}Most Active:{RESET}  {BOLD}{CYAN}{most_active.name}{RESET} ({YELLOW}{self.stats[most_active.player_id]['hands_played']} hands{RESET})")
        
        print()
