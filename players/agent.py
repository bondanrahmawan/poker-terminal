"""AgentPlayer — a human seat driven externally via Game.advance()/submit_action()."""
from core.player import Player


class AgentPlayer(Player):
    interactive = True

    def get_action(self, game_state: dict):
        # Never called: the engine pauses for interactive players instead.
        raise RuntimeError("AgentPlayer actions must be supplied via Game.submit_action()")
