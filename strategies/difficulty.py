"""
Difficulty level constants for bot strategies.
Higher difficulty = fewer mistakes, more accurate play.
"""
from dataclasses import dataclass
from typing import Dict

DIFFICULTY_LEVELS = {
    'very_easy': 0.2,
    'easy':      0.4,
    'normal':    0.6,
    'hard':      0.75,
    'expert':    0.9,
    'perfect':   1.0,
}

# Convenience names for passing to DesignedBotStrategy
VERY_EASY = 0.2
EASY      = 0.4
NORMAL    = 0.6
HARD      = 0.75
EXPERT    = 0.9
PERFECT   = 1.0


@dataclass(frozen=True)
class MistakeProfile:
    """A named bundle of biased mistakes a bot makes at a given difficulty
    level, replacing symmetric noise with beginner-like tendencies."""
    label: str
    overcall_bias: float    # added to equity ONLY in facing-a-bet call decisions
    overvalue_bias: float   # added to equity when holding any pair or an ace
    chase_draws: str        # 'always' | 'any_outs' | 'sloppy' | 'correct'
    position_aware: bool    # False -> use the 'medium' range for every seat
    opp_model_min_hands: int  # min observed hands before exploit adjustments apply; -1 = never
    bluff_mode: str         # 'random' | 'texture' | 'texture_image'
    score_noise: float      # ± points on the 0-100 preflop score
    equity_noise: float     # ± on postflop equity
    odds_noise: float       # ± on pot odds
    push_fold_skill: float  # 1.0 = follows push/fold charts exactly; 0.0 = doesn't know them


MISTAKE_PROFILES: Dict[str, MistakeProfile] = {
    'very_easy': MistakeProfile('very_easy', 0.15, 0.10, 'always',   False, -1, 'random',         15, 0.12, 0.08, 0.2),
    'easy':      MistakeProfile('easy',      0.10, 0.05, 'any_outs', False, -1, 'random',         10, 0.08, 0.05, 0.4),
    'normal':    MistakeProfile('normal',    0.04, 0.02, 'sloppy',   True,  -1, 'texture',          6, 0.05, 0.03, 0.7),
    'hard':      MistakeProfile('hard',      0.0,  0.0,  'correct',  True,  10, 'texture',          3, 0.03, 0.02, 0.95),
    'expert':    MistakeProfile('expert',    0.0,  0.0,  'correct',  True,   5, 'texture_image',    1, 0.01, 0.01, 1.0),
    'perfect':   MistakeProfile('perfect',   0.0,  0.0,  'correct',  True,   3, 'texture_image',    0, 0.0,  0.0, 1.0),
}


def mistakes_for(difficulty: float) -> MistakeProfile:
    """Map a difficulty float to the nearest level at or below it."""
    if difficulty >= PERFECT:
        return MISTAKE_PROFILES['perfect']
    if difficulty >= EXPERT:
        return MISTAKE_PROFILES['expert']
    if difficulty >= HARD:
        return MISTAKE_PROFILES['hard']
    if difficulty >= NORMAL:
        return MISTAKE_PROFILES['normal']
    if difficulty >= EASY:
        return MISTAKE_PROFILES['easy']
    return MISTAKE_PROFILES['very_easy']
