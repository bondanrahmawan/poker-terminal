from enum import Enum

class GameState(Enum):
    WAITING = "WAITING"
    DEAL = "DEAL"
    PREFLOP = "PREFLOP"
    FLOP = "FLOP"
    TURN = "TURN"
    RIVER = "RIVER"
    SHOWDOWN = "SHOWDOWN"
    END = "END"
