"""Pydantic request models — used only at the transport boundary.

IMPORTANT: action `amount` is a DELTA (chips pushed in right now), not a raise-to
total. See core/action_request.py.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


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
