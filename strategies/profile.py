"""
Style profiles — named parameter sets defining a bot's poker personality.
"""
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class StyleProfile:
    """
    Poker personality parameters.
    play_range    : fraction of starting hands to enter pots with (0.0=nit, 1.0=any two)
    aggression    : probability of raising when holding a strong hand
    bluff_freq    : base bluff frequency (modulated by board texture at higher difficulty)
    call_freq     : probability of calling when not raising
    slow_play_freq: probability of check-calling with strong hands instead of value-betting
    """
    name:           str
    play_range:     float
    aggression:     float
    bluff_freq:     float
    call_freq:      float
    slow_play_freq: float = 0.0  # Default 0 for backward compatibility


PROFILES: Dict[str, StyleProfile] = {
    'tight_passive':    StyleProfile('tight_passive',    play_range=0.25, aggression=0.15, bluff_freq=0.05, call_freq=0.80),
    'tight_aggressive': StyleProfile('tight_aggressive', play_range=0.25, aggression=0.80, bluff_freq=0.30, call_freq=0.20),
    'loose_passive':    StyleProfile('loose_passive',    play_range=0.75, aggression=0.15, bluff_freq=0.05, call_freq=0.85),
    'loose_aggressive': StyleProfile('loose_aggressive', play_range=0.75, aggression=0.80, bluff_freq=0.60, call_freq=0.40),
    'maniac':           StyleProfile('maniac',           play_range=0.95, aggression=0.95, bluff_freq=0.80, call_freq=0.50),
    'nit':              StyleProfile('nit',              play_range=0.10, aggression=0.40, bluff_freq=0.03, call_freq=0.20),
    'balanced':         StyleProfile('balanced',         play_range=0.50, aggression=0.50, bluff_freq=0.25, call_freq=0.50),
    'trapper':          StyleProfile('trapper',          play_range=0.30, aggression=0.20, bluff_freq=0.10, call_freq=0.85, slow_play_freq=0.75),
}
