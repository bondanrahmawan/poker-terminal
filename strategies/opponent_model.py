"""
Opponent modeling — track and exploit player tendencies.

Each bot maintains an `OpponentTracker` that records actions of every
opponent it has observed.  The tracker exposes aggregate stats (VPIP,
PFR, fold-to-bet, etc.) and an `exploit_adjustment()` method that
returns equity / aggression modifiers based on opponent weaknesses.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ── Per-opponent stats ───────────────────────────────────────────────────────

@dataclass
class OpponentStats:
    """Running counters for a single opponent."""
    opportunities_voluntary: int = 0   # times could have folded preflop
    voluntary_puts: int = 0            # times called/raised preflop
    opportunities_raise: int = 0       # times could have raised preflop
    preflop_raises: int = 0
    bets_faced: int = 0
    folds_to_bet: int = 0
    checks: int = 0
    checks_after_raise: int = 0        # check-raise potential
    total_hands_seen: int = 0

    @property
    def vpip(self) -> float:
        """Voluntarily Put $ In Pot — how loose the player is."""
        if self.opportunities_voluntary == 0:
            return 0.5
        return self.voluntary_puts / self.opportunities_voluntary

    @property
    def pfr(self) -> float:
        """Preflop Raise — how aggressive preflop."""
        if self.opportunities_raise == 0:
            return 0.2
        return self.preflop_raises / self.opportunities_raise

    @property
    def fold_to_bet(self) -> float:
        """How often they fold when facing a bet."""
        if self.bets_faced == 0:
            return 0.3
        return self.folds_to_bet / self.bets_faced

    @property
    def check_freq(self) -> float:
        if self.total_hands_seen == 0:
            return 0.3
        return self.checks / max(1, self.total_hands_seen)

    def classify(self) -> str:
        """Return a simple archetype label."""
        if self.vpip < 0.2 and self.pfr < 0.1:
            return 'nit'
        if self.vpip < 0.3 and self.pfr > 0.5:
            return 'tag'
        if self.vpip >= 0.5 and self.pfr < 0.3:
            return 'calling_station'
        if self.vpip >= 0.5 and self.pfr >= 0.5:
            return 'maniac'
        if self.vpip >= 0.4:
            return 'loose'
        if self.fold_to_bet > 0.6:
            return 'tight_foldy'
        return 'unknown'


# ── Tracker ──────────────────────────────────────────────────────────────────

class OpponentTracker:
    """
    Tracks all opponents at the table.  Call `record_action()` every
    time an opponent acts.  Query `get_stats(player_id)` or
    `exploit_adjustment(opponent_id)` for decision modifiers.
    """

    def __init__(self):
        self._stats: Dict[str, OpponentStats] = {}

    # ── Recording ────────────────────────────────────────────────────────────

    def record_action(self, player_id: str, action: str, street: str = 'preflop'):
        """
        Record an opponent action.
        action: 'fold', 'check', 'call', 'raise', 'all_in'
        street: 'preflop', 'flop', 'turn', 'river'
        """
        s = self._stats.setdefault(player_id, OpponentStats())
        s.total_hands_seen += 1

        if action == 'fold':
            if street == 'preflop':
                # Preflop fold = had chance to play but didn't
                s.opportunities_voluntary += 1
                s.opportunities_raise += 1
            else:
                s.bets_faced += 1
                s.folds_to_bet += 1
        elif action == 'check':
            s.checks += 1
        elif action in ('call', 'all_in'):
            if street == 'preflop':
                s.opportunities_voluntary += 1
                s.voluntary_puts += 1
            else:
                s.bets_faced += 1  # faced a bet and called
        elif action == 'raise':
            if street == 'preflop':
                s.opportunities_voluntary += 1
                s.voluntary_puts += 1
                s.opportunities_raise += 1
                s.preflop_raises += 1
            else:
                s.bets_faced += 1  # raised over a bet (aggressive)

    def record_missed_opportunity(self, player_id: str, street: str = 'preflop'):
        """Called when a player had a chance to act but checked/folded."""
        s = self._stats.setdefault(player_id, OpponentStats())
        if street == 'preflop':
            s.opportunities_voluntary += 1
            s.opportunities_raise += 1

    # ── Querying ─────────────────────────────────────────────────────────────

    def get_stats(self, player_id: str) -> OpponentStats:
        return self._stats.get(player_id, OpponentStats())

    def get_all_stats(self) -> Dict[str, OpponentStats]:
        return dict(self._stats)

    def has_data(self, player_id: str, min_hands: int = 5) -> bool:
        s = self._stats.get(player_id)
        return s is not None and s.total_hands_seen >= min_hands

    # ── Exploit adjustments ─────────────────────────────────────────────────

    def exploit_adjustment(self, opponent_ids: List[str]) -> Dict[str, float]:
        """
        Return modifiers for decision-making based on opponent tendencies.

        Keys:
          'equity_boost'    : float — add to equity when opponents are loose/passive
          'aggression_boost': float — add to aggression when opponents fold a lot
          'bluff_boost'     : float — add to bluff frequency vs tight_foldy opponents
          'caution_penalty' : float — subtract from equity when opponents are maniacs
        """
        if not opponent_ids:
            return {'equity_boost': 0.0, 'aggression_boost': 0.0,
                    'bluff_boost': 0.0, 'caution_penalty': 0.0}

        adjustments = {
            'equity_boost': 0.0,
            'aggression_boost': 0.0,
            'bluff_boost': 0.0,
            'caution_penalty': 0.0,
        }

        for oid in opponent_ids:
            s = self.get_stats(oid)
            classification = s.classify()

            if classification == 'calling_station':
                # Value bet more, bluff less
                adjustments['equity_boost'] += 0.05
                adjustments['bluff_boost'] -= 0.10
            elif classification == 'nit':
                # Bluff more, fold to their aggression
                adjustments['bluff_boost'] += 0.08
                adjustments['caution_penalty'] += 0.05
            elif classification == 'maniac':
                # Call down lighter, bluff less
                adjustments['equity_boost'] -= 0.03
                adjustments['caution_penalty'] += 0.08
            elif classification == 'tight_foldy':
                # Bluff relentlessly
                adjustments['bluff_boost'] += 0.12
                adjustments['aggression_boost'] += 0.05
            elif classification == 'tag':
                # Balanced — slight caution
                adjustments['caution_penalty'] += 0.02
            elif classification == 'loose':
                # Value bet wider
                adjustments['equity_boost'] += 0.03

        # Average across opponents
        n = len(opponent_ids)
        for key in adjustments:
            adjustments[key] /= n

        return adjustments

    def opponent_fold_equity(self, opponent_ids: List[str]) -> float:
        """
        Estimated extra equity from opponents folding.
        If opponents fold 40% of the time, that's ~0.04 extra equity.
        """
        if not opponent_ids:
            return 0.0
        total_fold = sum(self.get_stats(oid).fold_to_bet for oid in opponent_ids)
        avg_fold = total_fold / len(opponent_ids)
        # Fold equity scales with fold frequency: 0%→0, 50%→0.05, 80%→0.12
        return min(0.15, avg_fold * 0.15)

    def reset(self):
        self._stats.clear()
