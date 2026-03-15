"""
Difficulty level constants for bot strategies.
Higher difficulty = fewer mistakes, more accurate play.
"""

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
