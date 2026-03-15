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

        start_idx = (self.dealer_idx + 1) % n

        if self.state == GameState.PREFLOP:
            self.log("\n--- PREFLOP ---")

            if self.ante > 0:
                for p in [x for x in self.players if x.is_active]:
                    ante_amt = p.lose_chips(self.ante)
                    self.pot_manager.add_contribution(p.player_id, ante_amt)
                    self._log_action(p.name, "ante", ante_amt)

            if heads_up:
                sb_player = self.players[self.dealer_idx]
                bb_player = self.players[(self.dealer_idx + 1) % n]
                start_idx = self.dealer_idx
            else:
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

        players_to_act = [p for p in self.players if p.can_act()]
        current_idx = start_idx

        while players_to_act:
            p = self.players[current_idx]
            if p in players_to_act and p.can_act():
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
                        players_to_act = [o for o in self.players if o.can_act() and o != p]
                    else:
                        self.bet_manager.process_bet(p.player_id, actual_deducted, is_raise=False)
                        players_to_act.remove(p)

                    self._log_action(p.name, action.value, actual_deducted)

                    if action == PlayerAction.ALL_IN:
                        self.log(f">> {p.name} is ALL-IN")

            current_idx = (current_idx + 1) % n
            if len([p for p in self.players if p.is_active]) == 1:
                break

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
        print("\n" + "=" * 118)
        print("  SESSION STATISTICS")
        print("=" * 118)
        header = (
            f"  {'Name':<15} {'Strategy':<22}  {'Played':>6}  {'Won':>5}  {'Win%':>5}  "
            f"{'Rebuys':>6}  {'Net':>7}  {'Biggest Pot':>11}  {'Best Hand':<14}  {'Final':>6}  Status"
        )
        print(header)
        print("  " + "-" * 114)
        for p in sorted(self.players, key=lambda p: p.chips, reverse=True):
            s = self.stats[p.player_id]
            net = p.chips - s['starting_chips']
            net_str = f"+{net}" if net > 0 else str(net)
            played = s['hands_played']
            won = s['hands_won']
            win_pct = f"{won / played * 100:.0f}%" if played > 0 else "-"
            rebuys = s.get('rebuys', 0)
            if p.chips > 0:
                status = "Active"
            elif s['bust_hand']:
                status = f"Bust hand #{s['bust_hand']}"
            else:
                status = "Out"
            strategy_str = self._strategy_label(p)
            print(
                f"  {p.name:<15} {strategy_str:<22}  {played:>6}  {won:>5}  {win_pct:>5}  "
                f"{rebuys:>6}  {net_str:>7}  {s['biggest_pot']:>11}  {s['best_hand_name']:<14}  "
                f"{p.chips:>6}  {status}"
            )
        print("=" * 118)
