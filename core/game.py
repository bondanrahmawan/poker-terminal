"""Game - Main poker game engine."""

from typing import List, Dict, Optional, Tuple

from core.state import GameState
from core.deck import Deck, Card
from core.betting import BetManager, PotManager
from core.player import Player, PlayerAction
from core.stats_tracker import StatsTracker
from core.showdown import ShowdownHandler, ShowdownResult
from core.blind_scheduler import BlindScheduler
from core.events import GameEvent
from core.action_request import ActionRequest
from core.errors import IllegalActionError

_NUM_BLIND_LEVELS = 10

_NEXT_STREET = {
    GameState.PREFLOP: GameState.FLOP,
    GameState.FLOP: GameState.TURN,
    GameState.TURN: GameState.RIVER,
}


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
                 blind_reset_interval: int = 0, seed: int = None) -> None:
        """
        Args:
            big_blind: Big blind amount
            hands_per_level: Number of hands before blind escalation
            ante: Whether antes are enabled
            live_output: Whether to print output in real-time
            game_mode: 'tournament' or 'cash'
            short_deck: Use 36-card deck (6+)
            blind_reset_interval: Reset blinds every N hands (0=never, used in simulation mode)
            seed: Optional deck RNG seed for reproducible deals (None=global random)
        """
        self.players: List[Player] = []
        self.deck = Deck(min_rank=6 if short_deck else 2, seed=seed)
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
        self.events: List[GameEvent] = []
        self._event_seq = 0
        self.live_output = live_output
        self.pending_msg: str = ""
        self.game_mode = game_mode
        self.short_deck = short_deck
        self.blind_reset_interval = blind_reset_interval  # For simulation mode

        # Per-hand tracking
        self.player_roles: Dict[str, str] = {}
        self.fold_streets: Dict[str, str] = {}
        self.current_street: str = 'preflop'
        self.street_investments: Dict[str, dict] = {}
        
        # Last hand results (for bot notifications)
        self._last_hand_result: Optional[ShowdownResult] = None

        # Resumable-engine state (Phase 2)
        self._round_ctx: Optional[dict] = None       # per-betting-round loop state
        self._round_started: bool = False            # guards re-deal/re-begin on resume
        self._pending_request: Optional[ActionRequest] = None

    @property
    def stats(self) -> Dict[str, dict]:
        """Access the stats tracker's stats dictionary."""
        return self.stats_tracker.stats

    def log(self, msg: str):
        self.logs.append(msg)
        if self.live_output:
            print(msg)

    def emit(self, type_: str, **data) -> None:
        """Append a structured event alongside the string logs."""
        self.events.append(GameEvent(self._event_seq, type_, data))
        self._event_seq += 1

    def add_player(self, player: Player) -> None:
        """Add a player to the game and initialize their stats."""
        self.players.append(player)
        self.stats_tracker.register_player(player)

    def remove_player(self, player_id: str) -> None:
        """Remove a player from the game."""
        self.players = [p for p in self.players if p.player_id != player_id]

    def start_game(self) -> None:
        """Start a hand synchronously. Raises if the table has interactive players
        (drive those with start_hand()/submit_action() instead)."""
        req = self.start_hand()
        if req is not None:
            raise RuntimeError(
                "start_game() is synchronous-only; this table has interactive "
                "players — drive it with start_hand()/submit_action()")

    # ── Resumable public API (Phase 2) ───────────────────────────────────────

    def start_hand(self) -> Optional[ActionRequest]:
        """Begin a new hand and run it forward until either the hand completes
        (returns None) or an interactive player must act (returns ActionRequest)."""
        if len(self.players) < 2:
            self.log("Not enough players to start.")
            return None
        if self._pending_request is not None:
            raise IllegalActionError("A hand is already in progress awaiting an action")
        self.state = GameState.DEAL
        return self.advance()

    def advance(self) -> Optional[ActionRequest]:
        """Resume processing. Returns the next ActionRequest, or None when the
        hand is complete (state is back to WAITING)."""
        if self._pending_request is not None:
            return self._pending_request  # still waiting; idempotent
        req = self.run_cycle()
        self._pending_request = req
        return req

    def submit_action(self, player_id: str, action: PlayerAction,
                      amount: int = 0) -> Optional[ActionRequest]:
        """Apply an interactive player's action, then advance. Raises
        IllegalActionError on any violation. Returns like advance()."""
        req = self._pending_request
        if req is None:
            raise IllegalActionError("No action is pending")
        if player_id != req.player_id:
            raise IllegalActionError(
                f"Not {player_id}'s turn (waiting on {req.player_id})")
        p = next(pl for pl in self.players if pl.player_id == player_id)
        norm_action, norm_amount = self._validate_action(req, p, action, amount)
        self._pending_request = None
        self._apply_action(p, norm_action, norm_amount)
        return self.advance()

    @property
    def pending_request(self) -> Optional[ActionRequest]:
        """The outstanding request if the game is paused, else None."""
        return self._pending_request

    def run_cycle(self) -> Optional[ActionRequest]:
        """Run the game cycle until WAITING, or pause and return an ActionRequest
        when an interactive player must act."""
        while self.state != GameState.WAITING:
            if self.state == GameState.DEAL:
                self._handle_deal()
            elif self.state in (GameState.PREFLOP, GameState.FLOP,
                                GameState.TURN, GameState.RIVER):
                if self._round_ctx is None and not self._round_started:
                    if self.state != GameState.PREFLOP:
                        self._deal_community(3 if self.state == GameState.FLOP else 1)
                    self._begin_betting_round()
                    self._round_started = True
                req = self._continue_betting_round()
                if req is not None:
                    return req  # paused for an interactive player
                self._round_started = False
                if self.state == GameState.RIVER:
                    self.state = GameState.SHOWDOWN
                else:
                    self.state = (GameState.SHOWDOWN if self._is_hand_over()
                                  else _NEXT_STREET[self.state])
            elif self.state == GameState.SHOWDOWN:
                self._handle_showdown()
                self.state = GameState.END
            elif self.state == GameState.END:
                self._handle_end()
                self.state = GameState.WAITING
        return None

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
        if street:
            self.emit('street_started', street=street.lower(),
                      cards_dealt=[c.to_dict() for c in cards],
                      community=[c.to_dict() for c in self.community_cards])

    # ── Deal ─────────────────────────────────────────────────────────────────

    def _handle_deal(self) -> None:
        """Handle the deal phase: reset state, post blinds, deal cards."""
        self.hand_count += 1
        self.fold_streets = {}
        self.current_street = 'preflop'
        self.street_investments = {}
        self._round_ctx = None
        self._round_started = False

        # Keep the event list bounded in simulation mode (benchmarks run
        # hundreds of thousands of hands in a single Game instance).
        if not self.live_output:
            self.events = []

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

        self.emit('hand_started',
                  hand_number=self.hand_count,
                  small_blind=self.blind_scheduler.small_blind,
                  big_blind=self.big_blind,
                  ante=self.blind_scheduler.ante,
                  level=self.blind_scheduler.current_level + 1,
                  game_mode=self.game_mode,
                  dealer_player_id=self.players[self.dealer_idx].player_id)
        self.emit('seating', order=[
            {'player_id': p.player_id, 'name': p.name,
             'role': self.player_roles.get(p.player_id, ''),
             'chips': p.chips,
             'is_human': getattr(p, 'strategy', None) is None}
            for p in seat_order
        ])

        # Increment hands_played for all active players
        for p in active_players:
            self.stats_tracker.increment_hands_played(p.player_id)

        self.street_investments = {
            p.player_id: {'preflop': 0, 'flop': 0, 'turn': 0, 'river': 0}
            for p in active_players
        }

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
            cards = self.deck.draw(2)
            p.receive_cards(cards)
            self.emit('hole_cards_dealt', player_id=p.player_id, name=p.name,
                      cards=[c.to_dict() for c in cards])

        self.state = GameState.PREFLOP

    # ── Betting round ────────────────────────────────────────────────────────

    def _begin_betting_round(self) -> None:
        """Everything before the action loop: the can_act() short-circuit, computing
        the first-to-act seat, and (preflop only) posting antes + blinds. Stores the
        loop context in self._round_ctx, or None if the round is a no-op."""
        if len([p for p in self.players if p.can_act()]) <= 1:
            self._round_ctx = None
            return

        n = len(self.players)
        active_count = len([p for p in self.players if p.is_active])
        heads_up = active_count == 2

        # Default: BB or player after BB acts first
        start_idx = (self.dealer_idx + 1) % n

        if self.state == GameState.PREFLOP:
            self.log("\n--- PREFLOP ---")
            self.emit('street_started', street='preflop', cards_dealt=[], community=[])

            if self.blind_scheduler.ante > 0:
                for p in [x for x in self.players if x.is_active]:
                    ante_amt = p.lose_chips(self.blind_scheduler.ante)
                    self.pot_manager.add_contribution(p.player_id, ante_amt)
                    if p.player_id in self.street_investments:
                        self.street_investments[p.player_id]['preflop'] += ante_amt
                    self._log_action(p.name, "ante", ante_amt)
                    self.emit('blind_posted', player_id=p.player_id, name=p.name,
                              kind='ante', amount=ante_amt, pot=self.pot_manager.total_pot())

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
            if sb_player.player_id in self.street_investments:
                self.street_investments[sb_player.player_id]['preflop'] += sb_amt
            self.bet_manager.process_bet(sb_player.player_id, sb_amt)
            self._log_action(sb_player.name, "posts SB", sb_amt)
            self.emit('blind_posted', player_id=sb_player.player_id, name=sb_player.name,
                      kind='small', amount=sb_amt, pot=self.pot_manager.total_pot())

            bb_amt = bb_player.lose_chips(self.big_blind)
            self.pot_manager.add_contribution(bb_player.player_id, bb_amt)
            if bb_player.player_id in self.street_investments:
                self.street_investments[bb_player.player_id]['preflop'] += bb_amt
            self.bet_manager.process_bet(bb_player.player_id, bb_amt)
            self._log_action(bb_player.name, "posts BB", bb_amt)
            self.emit('blind_posted', player_id=bb_player.player_id, name=bb_player.name,
                      kind='big', amount=bb_amt, pot=self.pot_manager.total_pot())
        else:
            # Postflop betting rounds
            if heads_up:
                # Heads-up postflop: BB (non-dealer) acts first
                start_idx = (self.dealer_idx + 1) % n
            else:
                # Full ring postflop: SB (first active after dealer) acts first
                start_idx = (self.dealer_idx + 1) % n

        # players_to_act is built AFTER blind posting so an all-in blind poster
        # (can_act() == False) is correctly excluded.
        players_to_act: List[Player] = [p for p in self.players if p.can_act()]
        self._round_ctx = {
            'players_to_act': players_to_act,
            'current_idx': start_idx,
            'iterations': 0,
            'max_iterations': len(players_to_act) * 2 + 10,  # infinite-loop guard
            'active_count': active_count,
            'abort_round': False,
        }

    def _continue_betting_round(self) -> Optional[ActionRequest]:
        """The action loop over self._round_ctx. Returns an ActionRequest and leaves
        the context intact when it reaches an interactive player; returns None when
        the round completes."""
        ctx = self._round_ctx
        if ctx is None:
            return None  # no-op round (<=1 player could act) or already complete

        n = len(self.players)
        while ctx['players_to_act'] and ctx['iterations'] < ctx['max_iterations']:
            if ctx['abort_round']:
                break
            p = self.players[ctx['current_idx']]

            # Skip players no longer owing a decision or unable to act
            if p not in ctx['players_to_act'] or not p.can_act():
                if p in ctx['players_to_act'] and not p.can_act():
                    ctx['players_to_act'].remove(p)
                ctx['current_idx'] = (ctx['current_idx'] + 1) % n
                continue

            if getattr(p, 'interactive', False):
                # Pause: leave ctx untouched so the loop resumes at this same player.
                return self._build_action_request(p)

            action, amt = p.get_action(self._build_game_state(p, ctx))
            self._apply_action(p, action, amt)

        iterations = ctx['iterations']
        max_iterations = ctx['max_iterations']
        self._round_ctx = None
        if iterations >= max_iterations:
            self.log("WARNING: Betting round terminated due to excessive iterations")
        return None

    def _apply_action(self, p: Player, action: PlayerAction, amt: int) -> None:
        """Apply a single action to the current round, mutating self._round_ctx.
        Handles fold bookkeeping, chip deduction, pot contributions, the
        raise-reopens-betting reset, logging, and event emission. Advances
        current_idx and flags abort_round when only one active player remains."""
        ctx = self._round_ctx
        n = len(self.players)

        if action == PlayerAction.FOLD:
            p.fold()
            ctx['players_to_act'].remove(p)
            self._log_action(p.name, "fold", 0)
            self.fold_streets[p.player_id] = self.current_street
            self.emit('action_taken', player_id=p.player_id, name=p.name,
                      action='fold', amount=0, pot=self.pot_manager.total_pot(),
                      all_in=False)
        else:
            actual_deducted = p.lose_chips(amt)
            if p.player_id in self.street_investments:
                self.street_investments[p.player_id][self.current_street] += actual_deducted
            self.pot_manager.add_contribution(p.player_id, actual_deducted)

            if action in (PlayerAction.RAISE, PlayerAction.ALL_IN) and \
                    actual_deducted > self.bet_manager.get_amount_to_call(p.player_id):
                self.bet_manager.process_bet(p.player_id, actual_deducted, is_raise=True)
                # A raise reopens betting for all active players except the raiser
                ctx['players_to_act'] = [o for o in self.players if o.can_act() and o != p]
            else:
                self.bet_manager.process_bet(p.player_id, actual_deducted, is_raise=False)
                ctx['players_to_act'].remove(p)

            self._log_action(p.name, action.value, actual_deducted)
            self.emit('action_taken', player_id=p.player_id, name=p.name,
                      action=action.value, amount=actual_deducted,
                      pot=self.pot_manager.total_pot(),
                      all_in=(action == PlayerAction.ALL_IN))

            if action == PlayerAction.ALL_IN:
                self.log(f">> {p.name} is ALL-IN")

        ctx['iterations'] += 1
        ctx['current_idx'] = (ctx['current_idx'] + 1) % n

        # Check if only one player remains active
        if len([q for q in self.players if q.is_active]) == 1:
            ctx['abort_round'] = True

    def _build_game_state(self, p: Player, ctx: dict) -> dict:
        """The per-action game_state dict consumed by non-interactive get_action()."""
        n = len(self.players)
        return {
            'min_call':       self.bet_manager.get_amount_to_call(p.player_id),
            'min_raise':      self.bet_manager.min_raise,
            'pot_size':       self.pot_manager.total_pot(),
            'community_cards': self.community_cards,
            'players_info':   [(o.name, o.chips, o.is_active) for o in self.players],
            'position':       (self.players.index(p) - self.dealer_idx) % n,
            'player_role':    self.player_roles.get(p.player_id, ''),
            'num_active':     ctx['active_count'],
            'hand_log':       self.logs,
            'events':         self.events,
        }

    def _build_action_request(self, p: Player) -> ActionRequest:
        """Build the ActionRequest for an interactive player who must act."""
        min_call = max(0, self.bet_manager.get_amount_to_call(p.player_id))
        full_min_raise = min_call + self.bet_manager.min_raise
        raise_legal = p.chips > min_call and p.chips >= full_min_raise

        legal = ['fold']
        legal.append('check' if min_call == 0 else 'call')
        if raise_legal:
            legal.append('raise')
        legal.append('all-in')

        return ActionRequest(
            player_id=p.player_id,
            street=self.current_street,
            legal_actions=legal,
            min_call=min_call,
            min_raise_total=min(p.chips, full_min_raise),
            max_raise_total=p.chips,
            pot_size=self.pot_manager.total_pot(),
            seq=self._event_seq - 1,
        )

    def _validate_action(self, req: ActionRequest, p: Player,
                         action: PlayerAction, amount: int):
        """Validate and normalize an interactive action. Returns (action, amount) or
        raises IllegalActionError. Normalizes rather than rejecting where the TUI
        already would (CALL->ALL_IN, ALL_IN forces stack, etc.)."""
        if action.value not in req.legal_actions:
            raise IllegalActionError(
                f"{action.value} is not legal (allowed: {req.legal_actions})")

        if action in (PlayerAction.FOLD, PlayerAction.CHECK):
            return action, 0

        if action == PlayerAction.CALL:
            amt = min(p.chips, req.min_call)
            if amt >= p.chips:
                return PlayerAction.ALL_IN, p.chips
            return PlayerAction.CALL, amt

        if action == PlayerAction.RAISE:
            if not (req.min_raise_total <= amount <= p.chips):
                raise IllegalActionError(
                    f"Raise {amount} out of range "
                    f"[{req.min_raise_total}, {p.chips}]")
            if amount == p.chips:
                return PlayerAction.ALL_IN, amount
            return PlayerAction.RAISE, amount

        if action == PlayerAction.ALL_IN:
            return PlayerAction.ALL_IN, p.chips

        raise IllegalActionError(f"Unknown action {action}")

    def _is_hand_over(self) -> bool:
        return len([p for p in self.players if p.is_active]) <= 1

    # ── Showdown ─────────────────────────────────────────────────────────────

    def _handle_showdown(self) -> None:
        """Handle the showdown: evaluate hands and distribute pots."""
        self.log("\n--- SHOWDOWN ---")
        self.log(f"Community: {self.community_cards}")

        active_players: List[Player] = [p for p in self.players if p.is_active]
        # Only announce a showdown when it's actually contested — a hand that
        # ends by everyone folding to one player reveals no cards.
        if len(active_players) > 1:
            self.emit('showdown_started',
                      community=[c.to_dict() for c in self.community_cards])

        # Show folded players
        folded = [(p, self.fold_streets.get(p.player_id, 'preflop'))
                  for p in self.players
                  if not p.is_active and p.chips > 0 or
                     (not p.is_active and p.player_id in self.fold_streets)]
        for p, street in folded:
            self.log(f"{p.name:<{self._NAME_W}} folded on {street}")

        self.pot_manager.calculate_pots(
            [p.player_id for p in self.players if p.is_active],
            [p.player_id for p in self.players if p.is_all_in],
        )

        # Evaluate active players
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
                    self.emit('hole_cards_shown', player_id=p.player_id, name=p.name,
                              cards=[c.to_dict() for c in p.hole_cards],
                              hand_name=hand_name, best_five=str(best_hand_cards))

        # Show pot structure
        if len(self.pot_manager.pots) > 1:
            self.log("")
            id_to_name = {p.player_id: p.name for p in self.players}
            for i, pot in enumerate(self.pot_manager.pots):
                label = "Main Pot" if i == 0 else f"Side Pot {i}"
                eligible_names = ', '.join(
                    id_to_name.get(pid, pid) for pid in sorted(pot.eligible_players))
                self.log(f"  {label}: {pot.amount}  (eligible: {eligible_names})")
            self.emit('pot_structure', pots=[
                {"label": "Main Pot" if i == 0 else f"Side Pot {i}",
                 "amount": pot.amount,
                 "eligible_names": [id_to_name.get(pid, pid)
                                    for pid in sorted(pot.eligible_players)]}
                for i, pot in enumerate(self.pot_manager.pots)
            ])

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
            self.emit('pot_awarded', player_id=player_id, name=winner.name,
                      amount=amount, pot_index=-1, pot_label='total')

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

        # Clear stale all-in flags at hand end — including for busted players,
        # whose flag reset_for_hand (next deal) skips. (The pot is emptied for
        # display purposes in the view once the hand is over; pot_manager itself
        # is reset at the next deal so post-hand invariants stay inspectable.)
        for p in self.players:
            p.is_all_in = False

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
                self.emit('blinds_raised',
                          small_blind=self.blind_scheduler.small_blind,
                          big_blind=self.big_blind,
                          ante=self.blind_scheduler.ante,
                          level=self.blind_scheduler.current_level + 1)
            
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

        self.emit('hand_ended',
                  hand_number=self.hand_count,
                  chip_counts={p.player_id: p.chips for p in self.players},
                  busted=[p.player_id for p in self.players if p.chips == 0])

        self.log("Hand complete.")

    # ── Serialization / views (Phase 3) ──────────────────────────────────────

    def view_for(self, viewer_id: Optional[str]) -> dict:
        """JSON-safe snapshot from viewer_id's perspective (None = spectator)."""
        from core import views
        return views.build_view(self, viewer_id)

    def events_for(self, viewer_id: Optional[str], since_seq: int = -1) -> list:
        """Serialized events after since_seq, with private hole cards filtered."""
        from core import views
        return views.events_for(self, viewer_id, since_seq)

    def print_stats(self) -> None:
        """Print enhanced session statistics with visual formatting."""
        self.stats_tracker.print_stats(self.players)

