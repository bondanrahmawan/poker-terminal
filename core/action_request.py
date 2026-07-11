"""ActionRequest — emitted by the engine when an interactive player must act.

Amounts are DELTAS (chips pushed in right now), not raise-to totals.
"""
from dataclasses import dataclass
from typing import List


@dataclass
class ActionRequest:
    player_id: str
    street: str                  # 'preflop'|'flop'|'turn'|'river'
    legal_actions: List[str]     # subset of ['fold','check','call','raise','all-in']
    min_call: int                # chips owed to call (>= 0, NOT clamped to stack)
    min_raise_total: int         # minimum total delta for a legal raise, clamped to stack
    max_raise_total: int         # player's stack (no-limit)
    pot_size: int
    seq: int                     # event high-water mark at time of request (client sync cursor)

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "street": self.street,
            "legal_actions": list(self.legal_actions),
            "min_call": self.min_call,
            "min_raise_total": self.min_raise_total,
            "max_raise_total": self.max_raise_total,
            "pot_size": self.pot_size,
            "seq": self.seq,
        }
