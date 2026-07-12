"""
Bot roster — names, strategy assignments, and factory.
Edit this file to change who sits at the table and how they play.
"""
import random
from players.bot import BotPlayer
from strategies.engine import (
    TightPassiveStrategy, TightAggressiveStrategy,
    LoosePassiveStrategy, LooseAggressiveStrategy,
    BalancedStrategy, NitStrategy,
    ManiacStrategy, TrapperStrategy,
)
from strategies.difficulty import EASY, NORMAL, HARD

# (name, strategy_factory) pairs — factory takes difficulty float
_ROSTER = [
    ("Bot_Alice",   lambda d: BalancedStrategy(d)),
    ("Bot_Bob",     lambda d: TightAggressiveStrategy(d)),
    ("Bot_Charlie", lambda d: LoosePassiveStrategy(d)),
    ("Bot_Dave",    lambda d: TightPassiveStrategy(d)),
    ("Bot_Eve",     lambda d: BalancedStrategy(d)),
    ("Bot_Frank",   lambda d: TightAggressiveStrategy(max(d, HARD))),
    ("Bot_Grace",   lambda d: NitStrategy(d)),
    ("Bot_Hank",    lambda d: LooseAggressiveStrategy(d)),
    ("Bot_Iris",    lambda d: BalancedStrategy(EASY if d <= NORMAL else d)),
    ("Bot_Jack",    lambda d: TightAggressiveStrategy(EASY if d <= NORMAL else d)),
    ("Bot_Mike",    lambda d: ManiacStrategy(d)),
    ("Bot_Victoria", lambda d: TrapperStrategy(d)),
]

MAX_BOTS = len(_ROSTER)


def create_bots(num_bots: int, starting_chips: int,
                difficulty: float = NORMAL, shuffled: bool = False) -> list:
    """
    Return a list of BotPlayer instances.
    difficulty : override difficulty for all bots (EASY/NORMAL/HARD)
    shuffled   : randomise which bots from the roster are picked
    """
    pool = list(_ROSTER)
    if shuffled:
        random.shuffle(pool)
    selected = pool[:num_bots]
    return [
        BotPlayer(f"b{i}", name, starting_chips, factory(difficulty))
        for i, (name, factory) in enumerate(selected)
    ]
