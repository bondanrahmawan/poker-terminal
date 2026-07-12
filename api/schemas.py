"""Pydantic request models — used only at the transport boundary.

IMPORTANT: action `amount` is a DELTA (chips pushed in right now), not a raise-to
total. See core/action_request.py.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class CreateGameRequest(BaseModel):
    player_name: str = "Player"
    num_bots: int = Field(default=3, ge=1, le=12)
    difficulty: Literal["easy", "normal", "hard"] = "normal"
    game_mode: Literal["tournament", "cash"] = "tournament"
    starting_chips: int = Field(default=1000, ge=1)
    big_blind: int = Field(default=20, ge=2)
    hands_per_level: int = Field(default=10, ge=1)
    enable_ante: bool = False
    short_deck: bool = False
    shuffle_bots: bool = False
    seed: Optional[int] = None


class StartHandRequest(BaseModel):
    rebuy: bool = False


class ActionRequestBody(BaseModel):
    action: str                          # fold | check | call | raise | all-in
    amount: int = 0                      # DELTA chips (only meaningful for raise)


_DIFFICULTY_LABELS = {"easy": 0.4, "normal": 0.6, "hard": 0.75, "expert": 0.9}
_DIFFICULTY_VALUES = {0.4, 0.6, 0.75, 0.9}


class CreateSimulationRequest(BaseModel):
    """A benchmark job request. difficulty accepts a label or one of the four
    floats; the browser caps (tables ≤ 200, hands ≤ 1000) are clamped in the
    endpoint, not here."""
    type: Literal["all_vs_all", "h2h", "param_sweep"]
    num_tables: int = Field(ge=1)
    hands_per_table: int = Field(ge=1)
    starting_chips: int = Field(default=1000, ge=100)
    big_blind: int = Field(default=20, ge=2)
    difficulty: float = 0.6
    ante: bool = False
    short_deck: bool = False
    param_name: Optional[Literal["aggression", "play_range", "bluff_freq"]] = None

    @field_validator("difficulty", mode="before")
    @classmethod
    def _normalize_difficulty(cls, v):
        if isinstance(v, str):
            key = v.strip().lower()
            if key in _DIFFICULTY_LABELS:
                return _DIFFICULTY_LABELS[key]
            try:
                v = float(key)
            except ValueError:
                raise ValueError("difficulty must be easy/normal/hard/expert or 0.4/0.6/0.75/0.9")
        if float(v) not in _DIFFICULTY_VALUES:
            raise ValueError("difficulty must be one of 0.4/0.6/0.75/0.9")
        return float(v)

    @model_validator(mode="after")
    def _require_param_name(self):
        if self.type == "param_sweep" and self.param_name is None:
            raise ValueError("param_name is required for param_sweep")
        return self
