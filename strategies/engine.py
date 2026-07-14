"""
DesignedBotStrategy v2 — enhanced bot with full architecture.

New capabilities vs v1:
  - Opponent modeling & exploitation (VPIP, PFR, fold-to-bet tracking)
  - Draw detection (flush draws, straight draws, combo draws)
  - Advanced equity estimation (rule of 4/2, multiplayer adjustment)
  - Varied bet sizing (small, half, pot, overbet, block, min-raise)
  - Dynamic behavior (tilt, stack awareness, table image)
  - Deception (slow-playing monsters, semi-bluffing draws)
  - Position-aware preflop ranges & 3-betting

Flow: cards -> strength -> range -> odds -> style -> opponents -> decision
"""
import random
from typing import List, Tuple, Dict, Optional

from core.player import PlayerAction
from core.card import Card
from strategies import BotStrategy, PlayerView, register
from strategies import (
    OpponentTracker, TableImage, TiltState,
    detect_draws, advanced_equity, monte_carlo_equity, equity_vs_range, DrawInfo,
    BetSize, choose_bet_size, choose_raise_size, stack_depth_label,
    should_slow_play, should_semi_bluff,
    hand_in_range, should_3bet, position_to_range, should_defend_bb,
)
from strategies.profile import StyleProfile, PROFILES
from strategies.hand_score import score_starting_hand
from strategies.push_fold import should_jam, should_call_jam
from strategies.utils import pot_odds, calc_raise_amount
from strategies.difficulty import mistakes_for


# ── Board texture helpers (kept from v1) ─────────────────────────────────────

def _is_board_scary(community: List[Card]) -> bool:
    """True if the board has flush/straight/pair texture (good for bluffing)."""
    if len(community) < 3:
        return False
    suits = [c.suit for c in community]
    if max(suits.count(s) for s in set(suits)) >= 3:
        return True
    ranks = sorted(set(c.rank for c in community))
    for i in range(len(ranks) - 2):
        if ranks[i + 2] - ranks[i] <= 4:
            return True
    if len(ranks) < len(community):
        return True
    return False


def _is_opponent_weak(hand_log: list) -> bool:
    """Rough heuristic: opponent checked recently → likely weak."""
    if not hand_log:
        return True
    recent = hand_log[-6:]
    return any('check' in entry.lower() for entry in recent)


def _extract_opponent_ids(players_info: list, bot_name: str) -> List[str]:
    """Extract opponent identifiers from players_info."""
    return [p[0] for p in players_info if p[0] != bot_name]


# ── Core engine ──────────────────────────────────────────────────────────────

class DesignedBotStrategy(BotStrategy):
    """
    Enhanced bot with opponent modeling, draw detection, dynamic behavior,
    varied bet sizing, and position-aware preflop play.

    Args:
        profile    : StyleProfile (play_range, aggression, bluff_freq, call_freq)
        difficulty : 0.2 very_easy ... 1.0 perfect
    """

    def __init__(self, profile: StyleProfile, difficulty: float = 0.6):
        self.profile    = profile
        self.difficulty = difficulty
        self.mistakes   = mistakes_for(difficulty)
        # Dynamic state (persists across hands)
        self.tilt       = TiltState()
        self.image      = TableImage()
        self.tracker    = OpponentTracker()
        # Per-hand state
        self._big_blind = 20  # default; updated from game_state if available
        self._position  = 'MP'
        self._event_cursor = -1
        self._preflop_all_ins: list = []  # [(name, amount), ...] this hand
        self._preflop_actors: set = set()  # opponent names who acted preflop this hand

    # ── Public interface ─────────────────────────────────────────────────────

    def decide(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        community = game_state.get('community_cards', [])
        self._bot_name = game_state.get('self_name', '')
        position_idx = game_state.get('position', 0)
        num_active = game_state.get('num_active', 4)

        # Update big blind from min_raise (usually equals BB)
        self._big_blind = game_state.get('min_raise', self._big_blind)

        # Prefer the engine's real position label; fall back to the index
        # guess only when it's not supplied (e.g. in tests).
        player_role = game_state.get('player_role') or None
        if player_role == 'BTN/SB':
            player_role = 'BTN'
        self._position = player_role or self._position_label(position_idx, num_active)

        if not community:
            return self._decide_preflop(game_state, player)
        return self._decide_postflop(game_state, player)

    def _position_label(self, idx: int, n: int) -> str:
        if n <= 2:
            return 'BTN' if idx == 0 else 'BB'
        if idx == 0:
            return 'BTN'
        elif idx == 1:
            return 'SB'
        elif idx == 2:
            return 'BB'
        elif idx == n - 1:
            return 'CO'
        elif idx >= n - 3:
            return 'MP'
        return 'UTG'

    # ── Record opponent actions for modeling ─────────────────────────────────

    def _record_opponent_actions(self, game_state: dict):
        """Consume structured action_taken events to record opponent actions."""
        events = game_state.get('events', [])
        self_id = game_state.get('self_id', '')

        for event in events:
            if event.seq <= self._event_cursor:
                continue
            self._event_cursor = event.seq
            if event.type == 'hand_started':
                self._preflop_all_ins = []
                self._preflop_actors = set()
                continue
            if event.type != 'action_taken':
                continue
            data = event.data
            if data['player_id'] == self_id or data['name'] == self._bot_name:
                continue
            if data['street'] == 'preflop':
                self._preflop_actors.add(data['name'])
            if data.get('all_in') and data['street'] == 'preflop' and data['amount'] > 0:
                self._preflop_all_ins.append((data['name'], data['amount']))
            action = data['action']
            if action == 'all-in':
                action = 'raise'
            self.tracker.record_action(data['name'], action, data['street'])

    def _facing_preflop_jam(self, big_blind: int) -> Tuple[int, float]:
        """(num_all_ins, largest_jam_bb) from this hand's preflop all-ins."""
        if not self._preflop_all_ins:
            return 0, 0.0
        largest = max(amount for _, amount in self._preflop_all_ins)
        return len(self._preflop_all_ins), largest / max(1, big_blind)

    # ── Preflop ──────────────────────────────────────────────────────────────

    def _decide_preflop(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        """
        Enhanced preflop with position-aware ranges, 3-betting, and opponent exploitation.
        """
        min_call  = game_state.get('min_call', 0)
        min_raise = game_state.get('min_raise', 20)
        pot_size  = game_state.get('pot_size', 0)
        players_info = game_state.get('players_info', [])
        hand_log = game_state.get('hand_log', [])
        big_blind = game_state.get('big_blind', self._big_blind)
        current_bet = game_state.get('current_bet', big_blind)

        # Record opponent actions
        self._record_opponent_actions(game_state)

        # Get opponent IDs for exploitation, gated by difficulty: below hard,
        # bots never adapt to observed opponent tendencies.
        opponent_ids = _extract_opponent_ids(players_info, self._bot_name)
        n = self.mistakes.opp_model_min_hands
        modeled_ids = [oid for oid in opponent_ids
                       if n >= 0 and self.tracker.has_data(oid, n)]
        exploit = self.tracker.exploit_adjustment(modeled_ids)

        # No voluntary raise yet this street (BB's blind is not a "raise").
        unopened = current_bet <= big_blind

        # Hand score with noise (needed by the push/fold hook below too)
        score = self._noisy_score(score_starting_hand(*player.hole_cards))
        raw_score = score_starting_hand(*player.hole_cards)
        is_premium = raw_score >= 90  # AA, KK, AK always play regardless of range

        # ── Push/fold short-stack mode (Variant B) ──────────────────────────
        # Nash-style jam-or-fold charts replace normal preflop play below
        # ~15bb, and calling off vs. a preflop all-in is always a chart
        # decision regardless of our own stack depth.
        stack_bb = player.chips / big_blind
        skill = self.mistakes.push_fold_skill
        use_charts = random.random() < skill

        num_jams, jam_bb = self._facing_preflop_jam(big_blind)
        if num_jams > 0 and min_call > 0 and use_charts:
            players_behind = max(0, game_state.get('num_active', 2) - 2 - len(self._preflop_actors))
            if is_premium or should_call_jam(
                score, min(jam_bb, stack_bb), players_behind,
                num_jams, widen=self.mistakes.overcall_bias,
            ):
                return self._make_call(player.chips, min_call)
            self.image.record_preflop_fold()
            return PlayerAction.FOLD, 0

        if stack_bb <= 15 and use_charts:
            if self._position == 'BB' and min_call == 0:
                pass  # BB option: fall through to normal logic (check is free)
            elif unopened:
                if is_premium or should_jam(score, stack_bb, self._position, self.profile.aggression):
                    self.image.record_raise()
                    return PlayerAction.ALL_IN, player.chips
                if min_call == 0:
                    return PlayerAction.CHECK, 0
                self.image.record_preflop_fold()
                return PlayerAction.FOLD, 0
            else:
                # Facing a normal (non-all-in) raise while short: jam or fold.
                if is_premium or should_call_jam(score, stack_bb, 0, 0):
                    self.image.record_raise()
                    return PlayerAction.ALL_IN, player.chips
                self.image.record_preflop_fold()
                return PlayerAction.FOLD, 0

        # Position-aware range — a difficulty feature: beginners play the
        # same hands from every seat.
        if self.mistakes.position_aware:
            range_label = position_to_range(self._position, is_opening=unopened)
        else:
            range_label = 'medium'
        in_range = hand_in_range(*player.hole_cards, range_label)

        threshold = int((1.0 - self.profile.play_range) * 100)

        # ── Facing a raise (someone has voluntarily raised this street) ──
        if min_call > 0 and not unopened:
            # Consider 3-betting
            do_3bet, is_value, is_bluff = should_3bet(
                *player.hole_cards, range_label, self.profile.aggression
            )
            if do_3bet and random.random() < self.profile.aggression:
                amt = self._make_3bet_amount(pot_size, min_call, min_raise, player.chips, is_value)
                if is_bluff:
                    self.image.record_raise()
                return self._action_raise_or_all_in(amt, player.chips)

            # Consider defending BB
            if self._position == 'BB':
                raise_size_rel = min_call / max(1, pot_size)
                if should_defend_bb(*player.hole_cards, raise_size_rel, self.profile.aggression):
                    return self._make_call(player.chips, min_call)

            # Default: fold if out of range, call if in range. Margin-scaled
            # so a hand well inside the calling range isn't gated behind a
            # low call_freq — that's a difficulty mistake, not a permanent
            # personality tax (Phase 2 Task 3).
            if in_range or score >= threshold - 10 or is_premium:
                score_margin = (raw_score - (threshold - 10)) / 100.0
                p_call = self.profile.call_freq + exploit['equity_boost'] + score_margin * 1.5
                if self.mistakes.overcall_bias == 0.0 and raw_score >= 80:
                    p_call = max(p_call, 0.90)
                if is_premium:
                    p_call = 1.0
                if random.random() < min(1.0, p_call):
                    return self._make_call(player.chips, min_call)
            self.image.record_preflop_fold()
            return PlayerAction.FOLD, 0

        # ── Opening / limping into an unopened pot. This covers the BB's
        # own option (min_call == 0) as well as every other seat still
        # only owing the blind (min_call > 0, nobody has raised yet). With
        # nothing raised, a weak hand checks its option if free, else folds
        # rather than paying to enter with a bad hand. ──
        if not in_range and score < threshold and not is_premium:
            if min_call > 0:
                self.image.record_preflop_fold()
                return PlayerAction.FOLD, 0
            return PlayerAction.CHECK, 0

        self.image.record_preflop_enter()

        # Apply exploitation adjustments
        eff_aggression = self.profile.aggression + exploit['aggression_boost']
        eff_aggression += self.tilt.tilt_aggression_boost
        eff_aggression = min(1.0, max(0.0, eff_aggression))

        # Open raise
        if random.random() < eff_aggression:
            self.image.record_raise()
            fraction = 0.5 + eff_aggression * 0.5
            amt = calc_raise_amount(pot_size, min_call, min_raise, player.chips, fraction)
            return self._action_raise_or_all_in(amt, player.chips)

        # Premium hands always play (raise smaller or limp)
        if is_premium:
            self.image.record_raise()
            # Passive profiles limp/call more, aggressive raise
            if eff_aggression < 0.3:
                # Passive: just call/limp with premium
                return self._make_call(player.chips, min_call)
            else:
                # Aggressive: smaller raise with premium to trap
                fraction = 0.3 + eff_aggression * 0.3
                amt = calc_raise_amount(pot_size, min_call, min_raise, player.chips, fraction)
                return self._action_raise_or_all_in(amt, player.chips)

        # Limp (rare, only with medium hands in late position)
        if self._position in ('BTN', 'CO', 'SB') and random.random() < 0.15:
            return self._make_call(player.chips, min_call)

        # Otherwise: limp in if a blind is still owed, else check the option
        # rather than fold for free.
        if min_call > 0:
            return self._make_call(player.chips, min_call)
        return PlayerAction.CHECK, 0

    # ── Postflop ─────────────────────────────────────────────────────────────

    def _decide_postflop(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        """
        Enhanced postflop with draw detection, advanced equity, opponent modeling,
        varied bet sizing, slow-play, and semi-bluffing.
        """
        community = game_state.get('community_cards', [])
        min_call  = game_state.get('min_call', 0)
        min_raise = game_state.get('min_raise', 20)
        pot_size  = game_state.get('pot_size', 0)
        hand_log  = game_state.get('hand_log', [])
        players_info = game_state.get('players_info', [])
        num_active = game_state.get('num_active', 2)

        # Record opponent actions
        self._record_opponent_actions(game_state)

        # Opponent IDs and exploitation, gated by difficulty: below hard,
        # bots never adapt to observed opponent tendencies.
        opponent_ids = _extract_opponent_ids(players_info, self._bot_name)
        n = self.mistakes.opp_model_min_hands
        modeled_ids = [oid for oid in opponent_ids
                       if n >= 0 and self.tracker.has_data(oid, n)]
        exploit = self.tracker.exploit_adjustment(modeled_ids)
        fold_equity = self.tracker.opponent_fold_equity(modeled_ids)

        # Advanced equity with draw detection
        draw = detect_draws(player.hole_cards, community)
        if self.difficulty >= 0.75 and len(community) >= 4:
            # A flat 200 trials (±3.5pp) rather than difficulty-scaled — 37
            # trials at hard was ±8pp of pure noise, no more signal than none.
            raw_equity = monte_carlo_equity(
                player.hole_cards, community, num_active - 1, 200
            )
        else:
            raw_equity = advanced_equity(player.hole_cards, community, num_active - 1)
        # Range-aware equity (expert/perfect only): when facing a bet, shift
        # equity by the modeled opponents' observed looseness — aggression from
        # a tight field signals stronger hands (lower our equity); a loose field
        # signals weaker hands (raise it). Applied on top of raw_equity so the
        # Monte-Carlo estimate on turn/river is preserved.
        if self.mistakes.range_aware_equity and modeled_ids and min_call > 0:
            ranges = [self.tracker.get_stats(oid).vpip for oid in modeled_ids]
            opp_range = max(0.10, min(0.90, sum(ranges) / len(ranges)))
            raw_equity = equity_vs_range(
                player.hole_cards, community, opponent_range=opp_range,
                num_opponents=num_active - 1, base_equity=raw_equity,
            )
        equity = self._noisy_equity(raw_equity)
        equity += exploit['equity_boost']
        equity = min(1.0, max(0.0, equity))
        # Overvalue bias: a beginner genuinely believes top pair (or any ace)
        # is gold — this feeds every downstream use, including bet_equity.
        holds_ace = any(c.rank == 14 for c in player.hole_cards)
        if draw.hand_rank >= 2 or holds_ace:
            equity = min(1.0, equity + self.mistakes.overvalue_bias)
        # Fold equity (opponents folding to *our* bet) only applies when we're
        # betting/raising — it must not rescue a bad pot-odds call.
        bet_equity = min(1.0, equity + fold_equity)

        # Pot odds
        odds = self._noisy_odds(pot_odds(min_call, pot_size))

        # Stack depth
        stack_depth = stack_depth_label(player.chips, self._big_blind)

        # Effective aggression (tilt + exploitation)
        eff_aggression = self.profile.aggression + self.tilt.tilt_aggression_boost
        eff_aggression += exploit['aggression_boost']
        eff_aggression = min(1.0, max(0.0, eff_aggression))

        # Effective bluff frequency
        eff_bluff = self.profile.bluff_freq + exploit['bluff_boost']
        eff_bluff -= exploit['caution_penalty']
        eff_bluff = min(1.0, max(0.0, eff_bluff))

        # Opponent tendencies (modeled_ids only — gated by difficulty above)
        opp_folds_often = any(
            self.tracker.get_stats(oid).fold_to_bet > 0.5 for oid in modeled_ids
        )
        opp_calls_often = any(
            self.tracker.get_stats(oid).vpip > 0.5 for oid in modeled_ids
        )

        # ── Check for slow-play ──
        is_strong_made = draw.hand_rank >= 4 or equity >= 0.75  # trips+ or 75%+ equity
        is_made_hand = draw.hand_rank >= 2 or equity >= 0.42    # pair+ or 42%+ equity
        is_draw = draw.total_outs > 0
        is_strong_draw = draw.is_strong_draw

        # Slow-play logic: deliberately under-aggress with strong hands
        slow_play_tendency = getattr(self.profile, 'slow_play_freq', 0.0)
        is_slow_playing = False
        if is_strong_made and slow_play_tendency > 0:
            if random.random() < slow_play_tendency:
                is_slow_playing = True
                # If facing a bet, slow-play by calling instead of raising
                if min_call > 0:
                    return self._make_call(player.chips, min_call)
                # If no bet, check behind to trap
                return PlayerAction.CHECK, 0

        if min_call == 0 and not is_slow_playing and should_slow_play(equity, eff_aggression, self.image):
            return PlayerAction.CHECK, 0

        # ── Facing a bet ──
        if min_call > 0:
            # Semi-bluff raise with strong draws
            if is_draw and should_semi_bluff(
                bet_equity, eff_aggression, is_draw, is_strong_draw,
                odds, opp_folds_often
            ):
                self.image.record_raise()
                result = choose_raise_size(
                    pot_size, min_call, min_raise, player.chips, bet_equity,
                    is_draw=is_draw, is_strong_draw=is_strong_draw,
                    is_made_hand=is_made_hand, is_strong_made=is_strong_made,
                    opponent_folds_often=opp_folds_often,
                    opponent_calls_often=opp_calls_often,
                    stack_depth=stack_depth,
                    aggression=eff_aggression,
                    is_semi_bluff=True,
                )
                if result is not None:
                    size, amt = result
                    return self._action_raise_or_all_in(amt, player.chips)
                return PlayerAction.FOLD, 0

            # Value raise with strong hands
            if is_strong_made and random.random() < eff_aggression:
                result = choose_raise_size(
                    pot_size, min_call, min_raise, player.chips, bet_equity,
                    is_made_hand=True, is_strong_made=True,
                    opponent_folds_often=opp_folds_often,
                    opponent_calls_often=opp_calls_often,
                    stack_depth=stack_depth,
                    aggression=eff_aggression,
                )
                if result is not None:
                    size, amt = result
                    self.image.record_raise()
                    return self._action_raise_or_all_in(amt, player.chips)

            # Call with equity — margin-scaled so a clearly profitable call
            # isn't gated behind a low call_freq (that's a difficulty
            # mistake, not a permanent personality tax; Phase 2 Task 3).
            # Overcall bias applies only to this comparison, never to
            # bet_equity or the value-bet thresholds above (Task 4).
            margin = (equity + self.mistakes.overcall_bias) - (odds + exploit['caution_penalty'])
            if margin > 0:
                p_call = self.profile.call_freq + exploit['equity_boost'] + margin * 3.0
                if self.mistakes.overcall_bias == 0.0 and margin >= 0.10:
                    p_call = max(p_call, 0.90)      # hard+ never folds clearly winning hands
                if random.random() < min(1.0, p_call):
                    return self._make_call(player.chips, min_call)

            # Bluff catch with very weak hands (rare)
            if equity < 0.20 and opp_calls_often and random.random() < 0.1:
                return self._make_call(player.chips, min_call)

            # Draw chasing: a beginner calls draws it shouldn't, by mode.
            # Cap: a bet >= half the stack gives even a beginner pause,
            # except at 'always' (very_easy chases anything).
            if is_draw and min_call > 0:
                mode = self.mistakes.chase_draws
                if mode == 'always':
                    return self._make_call(player.chips, min_call)
                if min_call < player.chips // 2:
                    if mode == 'any_outs' and draw.total_outs >= 4:
                        return self._make_call(player.chips, min_call)
                    if mode == 'sloppy' and equity + 0.10 > odds:
                        return self._make_call(player.chips, min_call)
                    # 'correct': fall through to fold

            return PlayerAction.FOLD, 0

        # ── No bet to face (can check or bet) ──
        # Bluff
        if self._should_bluff_v2(community, hand_log, equity, eff_bluff, opp_folds_often):
            result = choose_bet_size(
                pot_size, min_call, min_raise, player.chips, bet_equity,
                is_bluff=True, opponent_folds_often=opp_folds_often,
                stack_depth=stack_depth, aggression=eff_aggression,
            )
            if result is not None:
                size, amt = result
                self.image.record_raise()
                return self._action_raise_or_all_in(amt, player.chips)

        # Semi-bluff bet with draws
        if is_draw and should_semi_bluff(
            bet_equity, eff_aggression, is_draw, is_strong_draw,
            odds, opp_folds_often
        ):
            result = choose_bet_size(
                pot_size, min_call, min_raise, player.chips, bet_equity,
                is_draw=is_draw, is_strong_draw=is_strong_draw,
                is_semi_bluff=True, opponent_folds_often=opp_folds_often,
                stack_depth=stack_depth, aggression=eff_aggression,
            )
            if result is not None:
                size, amt = result
                self.image.record_raise()
                return self._action_raise_or_all_in(amt, player.chips)

        # Value bet (skip if slow-playing)
        if is_made_hand and equity >= 0.45 and not is_slow_playing:
            result = choose_bet_size(
                pot_size, min_call, min_raise, player.chips, bet_equity,
                is_made_hand=is_made_hand, is_strong_made=is_strong_made,
                board_scary=_is_board_scary(community),
                opponent_folds_often=opp_folds_often,
                opponent_calls_often=opp_calls_often,
                stack_depth=stack_depth,
                aggression=eff_aggression,
            )
            if result is not None:
                size, amt = result
                self.image.record_raise()
                return self._action_raise_or_all_in(amt, player.chips)

        # Check
        return PlayerAction.CHECK, 0

    # ── Bluff logic v2 (enhanced) ────────────────────────────────────────────

    def _should_bluff_v2(
        self, community: List[Card], hand_log: list,
        equity: float, bluff_freq: float, opp_folds_often: bool,
    ) -> bool:
        """Enhanced bluff decision with board texture and opponent awareness."""
        if random.random() >= bluff_freq:
            return False
        # Don't bluff with made hands that can win at showdown
        if equity >= 0.40:
            return False
        # Low levels bluff randomly, with no board/opponent read at all.
        if self.mistakes.bluff_mode == 'random':
            return random.random() < 0.3
        # 'texture' and 'texture_image': bluff when board is scary and
        # opponents are weak, or when opponents fold often.
        board_scary = _is_board_scary(community)
        opponent_weak = _is_opponent_weak(hand_log)
        would_bluff = (board_scary and opponent_weak) or (opp_folds_often and equity < 0.25)
        if not would_bluff:
            return False
        if self.mistakes.bluff_mode == 'texture_image':
            # A tight image gets away with more bluffs; a loose one, fewer.
            return random.random() < min(1.0, 0.5 + self.image.bluff_success_rate)
        return True

    # ── Difficulty noise ─────────────────────────────────────────────────────

    def _noisy_score(self, score: int) -> int:
        noise = self.mistakes.score_noise
        if noise == 0.0:
            return score
        return max(0, min(100, int(score + random.uniform(-noise, noise))))

    def _noisy_equity(self, equity: float) -> float:
        noise = self.mistakes.equity_noise
        if noise == 0.0:
            return equity
        return max(0.0, min(1.0, equity + random.uniform(-noise, noise)))

    def _noisy_odds(self, odds: float) -> float:
        noise = self.mistakes.odds_noise
        if noise == 0.0:
            return odds
        return max(0.0, min(1.0, odds + random.uniform(-noise, noise)))

    # ── Action helpers ───────────────────────────────────────────────────────

    def _action_raise_or_all_in(self, amt: int, chips: int) -> Tuple[PlayerAction, int]:
        """Return RAISE or ALL_IN based on amount."""
        if amt >= chips:
            return PlayerAction.ALL_IN, chips
        return PlayerAction.RAISE, amt

    def _make_3bet_amount(self, pot_size: int, min_call: int, min_raise: int,
                          chips: int, is_value: bool) -> int:
        """Calculate 3-bet sizing: bigger for value, smaller for bluffs."""
        fraction = 0.6 if is_value else 0.4
        raw = int(pot_size * fraction) + min_call
        raw = max(raw, min_call + min_raise)
        return min(chips, raw)

    def _make_raise(self, pot_size: int, min_call: int, min_raise: int,
                    chips: int) -> Tuple[PlayerAction, int]:
        fraction = 0.5 + self.profile.aggression * 0.5
        amt = calc_raise_amount(pot_size, min_call, min_raise, chips, fraction)
        return self._action_raise_or_all_in(amt, chips)

    def _make_call(self, chips: int, min_call: int) -> Tuple[PlayerAction, int]:
        amt = min(chips, min_call)
        if amt >= chips:
            return PlayerAction.ALL_IN, chips
        return PlayerAction.CALL, amt

    # ── Hand-end tracking (call after each hand) ─────────────────────────────

    def record_hand_result(self, won: bool, amount: int, was_favorite: bool = False):
        """Call after showdown to update tilt and image."""
        if won:
            self.tilt.record_win(amount)
            if amount > 0:
                self.image.record_value_bet_won()
        else:
            self.tilt.record_loss(amount, was_favorite)
        self.tilt.record_hand_end()


# ── Registered style shortcuts ───────────────────────────────────────────────

@register('tight_passive')
class TightPassiveStrategy(DesignedBotStrategy):
    def __init__(self, difficulty: float = 0.6):
        super().__init__(PROFILES['tight_passive'], difficulty)


@register('tight_aggressive')
class TightAggressiveStrategy(DesignedBotStrategy):
    def __init__(self, difficulty: float = 0.6):
        super().__init__(PROFILES['tight_aggressive'], difficulty)


@register('loose_passive')
class LoosePassiveStrategy(DesignedBotStrategy):
    def __init__(self, difficulty: float = 0.6):
        super().__init__(PROFILES['loose_passive'], difficulty)


@register('loose_aggressive')
class LooseAggressiveStrategy(DesignedBotStrategy):
    def __init__(self, difficulty: float = 0.6):
        super().__init__(PROFILES['loose_aggressive'], difficulty)


@register('maniac')
class ManiacStrategy(DesignedBotStrategy):
    def __init__(self, difficulty: float = 0.6):
        super().__init__(PROFILES['maniac'], difficulty)


@register('nit')
class NitStrategy(DesignedBotStrategy):
    def __init__(self, difficulty: float = 0.6):
        super().__init__(PROFILES['nit'], difficulty)


@register('balanced')
class BalancedStrategy(DesignedBotStrategy):
    def __init__(self, difficulty: float = 0.6):
        super().__init__(PROFILES['balanced'], difficulty)


@register('trapper')
class TrapperStrategy(DesignedBotStrategy):
    """
    Deceptive player who deliberately slow-plays strong hands to trap opponents.
    Low aggression but high call frequency — invites action into monsters.
    """
    def __init__(self, difficulty: float = 0.6):
        super().__init__(PROFILES['trapper'], difficulty)
