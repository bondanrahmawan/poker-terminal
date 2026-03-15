"""
DesignedBotStrategy — full architecture from bot design document.

Flow: cards -> strength -> range -> odds -> style -> decision

Preflop:  score starting hand against play_range threshold
Postflop: evaluate hand strength, check pot odds, apply style

Difficulty injects noise into score/equity/odds estimates, simulating mistakes.
"""
import random
from typing import List, Tuple

from core.player import PlayerAction
from strategies import BotStrategy, PlayerView, register
from strategies.utils import estimate_equity, pot_odds, calc_raise_amount
from strategies.profile import StyleProfile, PROFILES
from strategies.hand_score import score_starting_hand
from core.card import Card


# ── Board texture helpers ────────────────────────────────────────────────────

def _is_board_scary(community: List[Card]) -> bool:
    """True if the board has flush/straight/pair texture (good for bluffing)."""
    if len(community) < 3:
        return False
    suits = [c.suit for c in community]
    if max(suits.count(s) for s in set(suits)) >= 3:
        return True                           # flush draw possible
    ranks = sorted(set(c.rank for c in community))
    for i in range(len(ranks) - 2):
        if ranks[i + 2] - ranks[i] <= 4:
            return True                       # straight draw possible
    if len(ranks) < len(community):
        return True                           # paired board
    return False


def _is_opponent_weak(hand_log: list) -> bool:
    """Rough heuristic: opponent checked recently → likely weak."""
    if not hand_log:
        return True
    recent = hand_log[-6:]
    return any('check' in entry.lower() for entry in recent)


# ── Core engine ──────────────────────────────────────────────────────────────

class DesignedBotStrategy(BotStrategy):
    """
    Bot with explicit style profile and difficulty level.

    Args:
        profile    : StyleProfile (play_range, aggression, bluff_freq, call_freq)
        difficulty : 0.2 very_easy ... 1.0 perfect
    """

    def __init__(self, profile: StyleProfile, difficulty: float = 0.6):
        self.profile    = profile
        self.difficulty = difficulty

    # ── Public interface ─────────────────────────────────────────────────────

    def decide(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        community = game_state.get('community_cards', [])
        if not community:
            return self._decide_preflop(game_state, player)
        return self._decide_postflop(game_state, player)

    # ── Preflop ──────────────────────────────────────────────────────────────

    def _decide_preflop(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        """
        Decision flow:
          1. Score the starting hand
          2. Compare against play_range threshold
          3. If in range: raise with prob aggression (preflop), else call/check
          4. If out of range: fold (or check if free)
        """
        score     = self._noisy_score(score_starting_hand(*player.hole_cards))
        threshold = int((1.0 - self.profile.play_range) * 100)
        in_range  = score >= threshold

        min_call  = game_state.get('min_call', 0)
        min_raise = game_state.get('min_raise', 0)
        pot_size  = game_state.get('pot_size', 0)

        if not in_range:
            return (PlayerAction.CHECK, 0) if min_call == 0 else (PlayerAction.FOLD, 0)

        # In range — decide action
        if min_call == 0:
            if random.random() < self.profile.aggression:
                return self._make_raise(pot_size, min_call, min_raise, player.chips)
            return PlayerAction.CHECK, 0
        else:
            strong = score >= 65
            if strong and random.random() < self.profile.aggression:
                return self._make_raise(pot_size, min_call, min_raise, player.chips)
            elif random.random() < self.profile.call_freq:
                return self._make_call(player.chips, min_call)
            else:
                return PlayerAction.FOLD, 0

    # ── Postflop ─────────────────────────────────────────────────────────────

    def _decide_postflop(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        """
        Decision flow:
          1. Estimate hand strength (equity)
          2. Check bluff opportunity
          3. If strong: raise with prob aggression
          4. Else if equity > pot odds: call with prob call_freq
          5. Else fold
        """
        community = game_state.get('community_cards', [])
        min_call  = game_state.get('min_call', 0)
        min_raise = game_state.get('min_raise', 0)
        pot_size  = game_state.get('pot_size', 0)
        hand_log  = game_state.get('hand_log', [])

        equity = self._noisy_equity(estimate_equity(player.hole_cards, community))

        # Bluff
        if self._should_bluff(community, hand_log):
            return self._make_raise(pot_size, min_call, min_raise, player.chips)

        if min_call == 0:
            if equity >= 0.55 and random.random() < self.profile.aggression:
                return self._make_raise(pot_size, min_call, min_raise, player.chips)
            return PlayerAction.CHECK, 0
        else:
            odds = self._noisy_odds(pot_odds(min_call, pot_size))
            if equity >= 0.60 and random.random() < self.profile.aggression:
                return self._make_raise(pot_size, min_call, min_raise, player.chips)
            elif equity > odds and random.random() < self.profile.call_freq:
                return self._make_call(player.chips, min_call)
            else:
                return PlayerAction.FOLD, 0

    # ── Bluff logic ──────────────────────────────────────────────────────────

    def _should_bluff(self, community: List[Card], hand_log: list) -> bool:
        if random.random() >= self.profile.bluff_freq:
            return False
        # At low difficulty bots bluff at wrong times
        if self.difficulty < 0.5:
            return True
        return _is_board_scary(community) and _is_opponent_weak(hand_log)

    # ── Difficulty noise ─────────────────────────────────────────────────────

    def _noisy_score(self, score: int) -> int:
        """Add noise to starting hand score proportional to (1 - difficulty)."""
        if self.difficulty >= 1.0:
            return score
        noise = (1.0 - self.difficulty) * 30
        return max(0, min(100, int(score + random.uniform(-noise, noise))))

    def _noisy_equity(self, equity: float) -> float:
        """Add noise to equity estimate proportional to (1 - difficulty)."""
        if self.difficulty >= 1.0:
            return equity
        noise = (1.0 - self.difficulty) * 0.25
        return max(0.0, min(1.0, equity + random.uniform(-noise, noise)))

    def _noisy_odds(self, odds: float) -> float:
        """Add noise to pot-odds reading proportional to (1 - difficulty)."""
        if self.difficulty >= 1.0:
            return odds
        noise = (1.0 - self.difficulty) * 0.15
        return max(0.0, min(1.0, odds + random.uniform(-noise, noise)))

    # ── Action helpers ───────────────────────────────────────────────────────

    def _make_raise(self, pot_size: int, min_call: int, min_raise: int,
                    chips: int) -> Tuple[PlayerAction, int]:
        fraction = 0.5 + self.profile.aggression * 0.5
        amt = calc_raise_amount(pot_size, min_call, min_raise, chips, fraction)
        if amt >= chips:
            return PlayerAction.ALL_IN, chips
        return PlayerAction.RAISE, amt

    def _make_call(self, chips: int, min_call: int) -> Tuple[PlayerAction, int]:
        amt = min(chips, min_call)
        if amt >= chips:
            return PlayerAction.ALL_IN, chips
        return PlayerAction.CALL, amt


# ── Registered style shortcuts ───────────────────────────────────────────────
# Each class is a zero-config wrapper that exposes a difficulty parameter.

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
