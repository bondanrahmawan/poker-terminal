"""
Bot roster — names, strategy assignments, and factory.
Edit this file to change who sits at the table and how they play.
main.py has no knowledge of bot personalities.
"""
from players.bot import BotPlayer
from strategies.engine import (
    TightPassiveStrategy, TightAggressiveStrategy,
    LoosePassiveStrategy, LooseAggressiveStrategy,
    BalancedStrategy, NitStrategy,
)
from strategies.difficulty import EASY, NORMAL, HARD

# (name, strategy) pairs — index determines seat order
_ROSTER = [
    ("Bot_Alice",   BalancedStrategy(NORMAL)),
    ("Bot_Bob",     TightAggressiveStrategy(NORMAL)),
    ("Bot_Charlie", LoosePassiveStrategy(NORMAL)),
    ("Bot_Dave",    TightPassiveStrategy(NORMAL)),
    ("Bot_Eve",     BalancedStrategy(NORMAL)),
    ("Bot_Frank",   TightAggressiveStrategy(HARD)),
    ("Bot_Grace",   NitStrategy(NORMAL)),
    ("Bot_Hank",    LooseAggressiveStrategy(NORMAL)),
    ("Bot_Iris",    BalancedStrategy(EASY)),
    ("Bot_Jack",    TightAggressiveStrategy(EASY)),
]

MAX_BOTS = len(_ROSTER)


def create_bots(num_bots: int, starting_chips: int) -> list:
    """Return a list of BotPlayer instances for the first num_bots roster slots."""
    return [
        BotPlayer(f"b{i}", name, starting_chips, strategy)
        for i, (name, strategy) in enumerate(_ROSTER[:num_bots])
    ]
