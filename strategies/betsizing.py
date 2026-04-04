"""
Advanced bet sizing — varied sizing for different situations.

Provides:
  - BetSize enum for sizing types
  - calc_bet_size() — returns amount based on context (value, bluff, semi-bluff, etc.)
  - Sizing considers hand strength, board texture, stack depth, and opponent tendencies
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
from core.card import Card


class BetSize(Enum):
    """Types of bet sizes."""
    SMALL = 'small'           # 25-33% pot — probe/continuation
    HALF = 'half'             # 50% pot — standard value
    POT = 'pot'               # 75-100% pot — strong value / polarized
    OVERBET = 'overbet'       # 125-150% pot — very polarized
    BLOCK = 'block'           # 40-50% pot — blocking bet on draws
    MIN_RAISE = 'min_raise'   # minimum legal raise
    ALL_IN = 'all_in'


# Default sizing fractions
_SIZE_FRACTIONS = {
    BetSize.SMALL: 0.33,
    BetSize.HALF: 0.50,
    BetSize.POT: 0.75,
    BetSize.OVERBET: 1.25,
    BetSize.BLOCK: 0.45,
    BetSize.MIN_RAISE: 0.0,  # handled separately
}


def calc_bet_size(
    size_type: BetSize,
    pot_size: int,
    min_call: int,
    min_raise: int,
    chips: int,
    fraction: Optional[float] = None,
) -> int:
    """
    Calculate a bet/raise amount.

    Args:
        size_type: The sizing category
        pot_size: Current total pot
        min_call: Amount needed to call
        min_raise: Minimum raise amount (usually big blind)
        chips: Player's remaining stack
        fraction: Override fraction (0.0-2.0+); if None uses default for size_type

    Returns:
        Bet amount (already capped at chips)
    """
    if size_type == BetSize.ALL_IN:
        return chips

    frac = fraction if fraction is not None else _SIZE_FRACTIONS[size_type]

    if size_type == BetSize.MIN_RAISE:
        raw = min_call + min_raise
    else:
        raw = int(pot_size * frac) + min_call
        # Ensure at least min_raise
        raw = max(raw, min_call + min_raise)

    return min(chips, raw)


def choose_bet_size(
    pot_size: int,
    min_call: int,
    min_raise: int,
    chips: int,
    equity: float,
    is_draw: bool = False,
    is_strong_draw: bool = False,
    is_made_hand: bool = False,
    is_strong_made: bool = False,
    board_scary: bool = False,
    opponent_folds_often: bool = False,
    opponent_calls_often: bool = False,
    stack_depth: str = 'medium',  # 'short', 'medium', 'deep'
    aggression: float = 0.5,
    is_bluff: bool = False,
    is_semi_bluff: bool = False,
    is_slow_play: bool = False,
    num_opponents: int = 1,
) -> tuple:
    """
    Choose the optimal bet size given the context.

    Returns:
        (BetSize, amount) tuple
    """
    # ── All-in when short-stacked ──
    if chips <= min_call + min_raise:
        return BetSize.ALL_IN, chips

    # ── Slow-playing: check/call with strong hands ──
    if is_slow_play and is_strong_made:
        if min_call == 0:
            from core.player import PlayerAction
            return (PlayerAction.CHECK, 0)
        else:
            # Just call instead of raise
            from core.player import PlayerAction
            return (PlayerAction.CALL, min(chips, min_call))

    # ── Bluff sizing ──
    if is_bluff and not is_semi_bluff:
        # Pure bluff: small bet to steal, or overbet if opponent folds often
        if opponent_folds_often:
            # Can use larger sizing to maximize fold equity
            size = BetSize.POT if aggression > 0.6 else BetSize.HALF
        else:
            size = BetSize.SMALL
        amt = calc_bet_size(size, pot_size, min_call, min_raise, chips)
        return size, amt

    # ── Semi-bluff sizing (draws with equity) ──
    if is_semi_bluff or (is_draw and equity > 0.35):
        if is_strong_draw:
            # Combo draw — bet bigger for value + fold equity
            size = BetSize.POT if aggression > 0.5 else BetSize.HALF
        else:
            # Simple draw — block bet or small bet
            size = BetSize.BLOCK if stack_depth == 'medium' else BetSize.SMALL
        amt = calc_bet_size(size, pot_size, min_call, min_raise, chips)
        return size, amt

    # ── Value bet sizing ──
    if is_made_hand:
        if is_strong_made:
            # Strong hand: pot or overbet for value
            if opponent_calls_often:
                # Calling station — bet big, they'll pay
                size = BetSize.OVERBET if stack_depth == 'deep' else BetSize.POT
            elif board_scary:
                # Scary board — smaller bet to keep opponents in
                size = BetSize.HALF
            else:
                size = BetSize.POT
        elif equity > 0.60:
            # Medium-strong hand — standard value bet
            if opponent_calls_often:
                size = BetSize.POT
            else:
                size = BetSize.HALF
        else:
            # Thin value / weak made hand
            if opponent_folds_often:
                size = BetSize.SMALL  # small bet to steal
            else:
                size = BetSize.BLOCK  # block bet to control pot
        amt = calc_bet_size(size, pot_size, min_call, min_raise, chips)
        return size, amt

    # ── Default: no clear hand ──
    if min_call == 0:
        from core.player import PlayerAction
        return (PlayerAction.CHECK, 0)
    else:
        from core.player import PlayerAction
        return (PlayerAction.FOLD, 0)


def choose_raise_size(
    pot_size: int,
    min_call: int,
    min_raise: int,
    chips: int,
    equity: float,
    is_draw: bool = False,
    is_strong_draw: bool = False,
    is_made_hand: bool = False,
    is_strong_made: bool = False,
    opponent_folds_often: bool = False,
    opponent_calls_often: bool = False,
    stack_depth: str = 'medium',
    aggression: float = 0.5,
    is_bluff: bool = False,
    is_semi_bluff: bool = False,
    is_slow_play: bool = False,
) -> tuple:
    """
    Choose raise size (as opposed to bet size — used when facing a bet).
    Returns (BetSize, amount).
    """
    return choose_bet_size(
        pot_size=pot_size,
        min_call=min_call,
        min_raise=min_raise,
        chips=chips,
        equity=equity,
        is_draw=is_draw,
        is_strong_draw=is_strong_draw,
        is_made_hand=is_made_hand,
        is_strong_made=is_strong_made,
        board_scary=False,
        opponent_folds_often=opponent_folds_often,
        opponent_calls_often=opponent_calls_often,
        stack_depth=stack_depth,
        aggression=aggression,
        is_bluff=is_bluff,
        is_semi_bluff=is_semi_bluff,
        is_slow_play=is_slow_play,
    )


def stack_depth_label(chips: int, big_blind: int) -> str:
    """Classify stack depth in terms of big blinds."""
    bb_count = chips / max(1, big_blind)
    if bb_count <= 10:
        return 'short'
    elif bb_count <= 40:
        return 'medium'
    else:
        return 'deep'
