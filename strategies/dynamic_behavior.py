"""
Dynamic bot behavior — tilt, stack awareness, table image, slow-play, semi-bluff.

Bots are no longer static; they adapt based on:
  - Recent results (tilt after bad beats)
  - Stack size relative to blinds (desperation when short)
  - Table image (tight image = more successful bluffs)
  - Hand-specific deception (slow-playing monsters, semi-bluffing draws)
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import List, Optional
from core.card import Card


# ── Tilt tracking ────────────────────────────────────────────────────────────

@dataclass
class TiltState:
    """Tracks a bot's emotional state after bad beats."""
    tilt_level: float = 0.0        # 0.0 = calm, 1.0 = full tilt
    recent_losses: List[int] = field(default_factory=list)  # last N hand losses
    recent_wins: List[int] = field(default_factory=list)    # last N hand wins
    bad_beat_count: int = 0
    hands_since_tilt_check: int = 0

    TILT_WINDOW = 10  # track last 10 hands

    def record_loss(self, amount: int, was_favorite: bool = False):
        """Record a loss. Big losses while favored increase tilt."""
        self.recent_losses.append(amount)
        if len(self.recent_losses) > self.TILT_WINDOW:
            self.recent_losses.pop(0)
        if was_favorite:
            self.tilt_level = min(1.0, self.tilt_level + 0.15)
            self.bad_beat_count += 1
        else:
            self.tilt_level = min(1.0, self.tilt_level + 0.05)

    def record_win(self, amount: int):
        """Record a win. Wins reduce tilt."""
        self.recent_wins.append(amount)
        if len(self.recent_wins) > self.TILT_WINDOW:
            self.recent_wins.pop(0)
        self.tilt_level = max(0.0, self.tilt_level - 0.08)

    def record_hand_end(self):
        self.hands_since_tilt_check += 1
        # Natural tilt decay over time
        if self.hands_since_tilt_check % 5 == 0:
            self.tilt_level = max(0.0, self.tilt_level - 0.03)

    @property
    def is_tilting(self) -> bool:
        return self.tilt_level > 0.5

    @property
    def tilt_aggression_boost(self) -> float:
        """Tilted players play looser and more aggressive."""
        if self.tilt_level < 0.3:
            return 0.0
        return (self.tilt_level - 0.3) * 0.4  # up to +0.28 at full tilt

    @property
    def tilt_caution_penalty(self) -> float:
        """Tilted players make worse reads."""
        if self.tilt_level < 0.5:
            return 0.0
        return (self.tilt_level - 0.5) * 0.1  # up to +0.05 at full tilt


# ── Table image ──────────────────────────────────────────────────────────────

@dataclass
class TableImage:
    """
    How the table perceives this bot.
    Tight image (few VPIP hands) → bluffs work better.
    Loose image → value bets get called more.
    """
    hands_played_tight: int = 0    # times folded preflop
    hands_played_loose: int = 0    # times entered pot
    raises_made: int = 0
    bluffs_caught: int = 0         # times bluff was called and lost
    value_bets_won: int = 0        # times value bet won

    @property
    def tightness(self) -> float:
        """0.0 = very loose, 1.0 = very tight image."""
        total = self.hands_played_tight + self.hands_played_loose
        if total == 0:
            return 0.5
        return self.hands_played_tight / total

    @property
    def bluff_success_rate(self) -> float:
        """How often bluffs work against this player's image."""
        total = self.bluffs_caught + self.value_bets_won  # rough proxy
        if total == 0:
            return 0.5
        # Tight image → bluff success higher
        return 0.3 + 0.4 * self.tightness

    @property
    def value_bet_call_rate(self) -> float:
        """How likely opponents are to call this player's value bets."""
        # Loose image → opponents call more lightly
        return 0.3 + 0.3 * (1.0 - self.tightness)

    def record_preflop_fold(self):
        self.hands_played_tight += 1

    def record_preflop_enter(self):
        self.hands_played_loose += 1

    def record_raise(self):
        self.raises_made += 1

    def record_bluff_caught(self):
        self.bluffs_caught += 1

    def record_value_bet_won(self):
        self.value_bets_won += 1


# ── Deception helpers ────────────────────────────────────────────────────────

def should_slow_play(equity: float, aggression: float, table_image: TableImage) -> bool:
    """
    Decide whether to slow-play (trap) with a strong hand.
    More likely when:
      - Equity is very high (trips+, strong two pair)
      - Aggression is low (passive players trap more)
      - Table image is loose (opponents expect action)
    """
    if equity < 0.70:
        return False
    # Base chance from aggression (passive players trap more)
    base_chance = (1.0 - aggression) * 0.3
    # Loose image bonus (opponents will bet into you)
    image_bonus = (1.0 - table_image.tightness) * 0.15
    # Very strong hands trap more
    strength_bonus = (equity - 0.70) * 0.5
    total_chance = base_chance + image_bonus + strength_bonus
    return random.random() < min(0.4, total_chance)


def should_semi_bluff(
    equity: float,
    aggression: float,
    is_draw: bool,
    is_strong_draw: bool,
    pot_odds: float,
    opponent_folds_often: bool,
) -> bool:
    """
    Decide whether to semi-bluff (bet/raise with a draw).
    More likely when:
      - Have a strong draw (combo draw, flush+straight)
      - Opponent folds often
      - Equity is decent (not just a gutshot)
    """
    if not is_draw:
        return False
    if equity < pot_odds:
        # Drawing hand doesn't have direct equity, but semi-bluff
        # can still work if opponent folds enough
        if not opponent_folds_often:
            return False

    base_chance = aggression * 0.3
    if is_strong_draw:
        base_chance += 0.25  # combo draws are great semi-bluffs
    elif equity > 0.35:
        base_chance += 0.10
    if opponent_folds_often:
        base_chance += 0.15

    return random.random() < min(0.6, base_chance)


def desperation_factor(chips: int, big_blind: int) -> float:
    """
    How desperate the bot should play based on stack size.
    0.0 = comfortable, 1.0 = must go all-in soon.
    """
    bb_count = chips / max(1, big_blind)
    if bb_count <= 5:
        return 1.0  # critical — push any reasonable hand
    elif bb_count <= 10:
        return 0.7  # urgent — widen shoving range
    elif bb_count <= 20:
        return 0.3  # cautious — look for spots
    else:
        return 0.0  # comfortable — play normal


def adjust_for_desperation(
    action_choice: str,
    desperation: float,
    hand_score: float,
    min_call: int,
    chips: int,
) -> tuple:
    """
    Modify a decision based on desperation level.
    Returns (modified_action, amount).
    """
    from core.player import PlayerAction

    if desperation <= 0:
        return None, 0  # no change

    # Very desperate — shove wider
    if desperation >= 0.7 and hand_score > 0.30:
        if action_choice in ('fold', 'check'):
            # Push instead of folding/checking
            return (PlayerAction.ALL_IN, chips)
        elif action_choice == 'call':
            # Already calling, maybe shove instead
            if hand_score > 0.45:
                return (PlayerAction.ALL_IN, chips)

    # Moderately desperate — call wider
    if desperation >= 0.3 and action_choice == 'fold' and hand_score > 0.35:
        return (PlayerAction.CALL, min(chips, min_call))

    return None, 0
