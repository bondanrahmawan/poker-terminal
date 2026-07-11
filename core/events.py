"""Structured game events. The single source of truth for 'what happened'."""
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class GameEvent:
    seq: int                    # monotonically increasing per Game instance, from 0
    type: str                   # one of the documented event types
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"seq": self.seq, "type": self.type, "data": self.data}
