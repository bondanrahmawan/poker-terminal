# AI Strategy Assessment & Advanced AI Design

## Executive Summary

The current bot AI system is **well-architected** with a solid foundation. It features:
- 7 distinct strategy archetypes (Nit, TAG, LAG, Maniac, etc.)
- 6 difficulty levels with realistic mistake simulation
- Style profiles with tunable parameters
- Preflop hand scoring and postflop equity estimation

**Overall Rating: 7/10** — Production-ready for casual play, but lacks advanced features for serious simulation or training purposes.

---

## Part 1: Current AI Assessment

### Architecture Overview

```
strategies/
├── engine.py        # DesignedBotStrategy (main AI engine)
├── simple.py        # SimpleStrategy (default/fallback AI)
├── profile.py       # StyleProfile dataclass, 7 profiles
├── difficulty.py    # Difficulty constants (EASY to PERFECT)
├── hand_score.py    # Starting hand scoring table (0-100)
├── utils.py         # Equity, pot odds, position helpers
└── roster.py        # Bot factory with 10 predefined bots
```

### Decision Flow

```
┌─────────────────────────────────────────────────────────────┐
│                     PREFLOP DECISION                         │
├─────────────────────────────────────────────────────────────┤
│  1. Score starting hand (0-100) using hand_score.py         │
│  2. Apply difficulty noise to score                         │
│  3. Compare vs play_range threshold                         │
│  4. If in range: raise (aggression%) or call/check          │
│  5. If out of range: fold or check (if free)                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     POSTFLOP DECISION                        │
├─────────────────────────────────────────────────────────────┤
│  1. Estimate hand equity (0.0-1.0)                          │
│  2. Apply difficulty noise to equity                        │
│  3. Check bluff opportunity (board texture + opponent weak) │
│  4. If strong (≥60%): raise with aggression%                │
│  5. Else if equity > pot_odds: call with call_freq%         │
│  6. Else: fold                                              │
└─────────────────────────────────────────────────────────────┘
```

### Strengths

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Code Quality** | 9/10 | Clean, well-documented, modular |
| **Strategy Variety** | 8/10 | 7 distinct archetypes with clear differentiation |
| **Difficulty Scaling** | 8/10 | Noise injection simulates human mistakes well |
| **Preflop Play** | 7/10 | Solid hand scoring table based on poker theory |
| **Position Awareness** | 7/10 | Basic position adjustment in SimpleStrategy |
| **Pot Odds** | 7/10 | Correctly calculates and uses pot odds |
| **Bluffing** | 6/10 | Heuristic-based, board-texture aware |

### Weaknesses

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Equity Calculation** | 4/10 | Lookup table by hand rank, not true equity |
| **Range Analysis** | 3/10 | No opponent range modeling |
| **Bet Sizing** | 5/10 | Pot-proportional only, no strategic sizing |
| **Multi-Street Planning** | 2/10 | No turn/river planning, purely reactive |
| **Opponent Modeling** | 1/10 | No tracking of opponent tendencies |
| **Exploitative Play** | 1/10 | No adjustment based on opponent weaknesses |
| **ICM Awareness** | 0/10 | No tournament equity considerations |
| **Monte Carlo** | 0/10 | No simulation-based equity calculation |

### Key Technical Limitations

#### 1. Equity Estimation is Over-Simplified

**Current approach** (`utils.py`):
```python
_EQUITY_BY_RANK = [0.0, 0.25, 0.42, 0.57, 0.67, 0.76, 0.84, 0.91, 0.96, 0.99]

def estimate_equity(hole_cards, community_cards):
    if len(community_cards) == 0:
        # Pre-flop heuristic based on ranks
        ranks = [c.rank for c in hole_cards]
        is_strong = max(ranks) > 10 or abs(ranks[0] - ranks[1]) <= 1
        return 0.55 if is_strong else 0.32
    score, _ = HandEvaluator.evaluate(hole_cards, community_cards)
    rank = score[0] if score else 0
    return _EQUITY_BY_RANK[min(rank, 9)]
```

**Problems:**
- Preflop equity is a binary heuristic (0.55 or 0.32) — doesn't account for opponent ranges
- Postflop equity uses hand **rank** (pair, flush, etc.) not actual win probability
- A top pair on a dry board has same equity as top pair on a wet board
- Doesn't consider number of opponents or their likely ranges

**Example failure:**
```
Board: K♠ Q♠ J♠
Hand:  K♥ K♦  (set of kings)
Current equity estimate: ~0.84 (based on "Set" rank)
Actual equity vs random hand: 98%
Actual equity vs A♠ T♠: 58% (vulnerable to straight/flush)
```

#### 2. No Opponent Range Modeling

The bot makes decisions based on:
- Its own hand strength
- Community cards
- Pot odds

It does **not** consider:
- What hands the opponent likely has
- How the opponent's range connects with the board
- How the bot's perceived range looks to the opponent

#### 3. No Multi-Street Planning

Each street is evaluated independently. The bot doesn't:
- Plan turn/river cards when calling
- Consider implied odds (future betting)
- Set up bluffs for later streets
- Recognize when it's drawing dead or near-dead

#### 4. Bet Sizing is One-Dimensional

```python
def _make_raise(self, pot_size, min_call, min_raise, chips, fraction):
    fraction = 0.5 + self.profile.aggression * 0.5  # 0.5 – 1.0
    amt = calc_raise_amount(pot_size, min_call, min_raise, chips, fraction)
```

**Missing considerations:**
- Value betting: size for maximum call from worse hands
- Bluff sizing: minimum effective bluff size
- Polarized vs merged ranges
- Stack-to-pot ratio (SPR) implications
- Board texture-based sizing (wet vs dry boards)

---

## Part 2: Advanced AI Design

### Proposed Architecture

```
strategies/
├── engine.py              # Existing DesignedBotStrategy (keep for simple bots)
├── simple.py              # Existing SimpleStrategy (keep as fallback)
├── advanced/              # NEW: Advanced AI module
│   ├── __init__.py
│   ├── monte_carlo.py     # Monte Carlo equity simulation
│   ├── ranges.py          # Hand range representation and manipulation
│   ├── opponent_model.py  # Opponent tendency tracking
│   ├── cfr.py             # Counterfactual Regret Minimization (GTO-adjacent)
│   ├── planner.py         # Multi-street planning
│   └── exploitative.py    # Exploitative adjustments
└── hybrid.py              # Hybrid AI (advanced + heuristic fallback)
```

---

### Feature 1: Monte Carlo Equity Calculation

**File: `advanced/monte_carlo.py`**

```python
import random
from typing import List, Tuple
from core.card import Card, Rank, Suit
from core.deck import Deck
from core.evaluator import HandEvaluator


class MonteCarloEquity:
    """
    Estimates hand equity via Monte Carlo simulation.
    
    Usage:
        mc = MonteCarloEquity()
        equity = mc.estimate(hole_cards, community_cards, opponent_ranges, iterations=10000)
    """
    
    def __init__(self, iterations: int = 10000):
        self.iterations = iterations
    
    def estimate(
        self,
        hole_cards: List[Card],
        community_cards: List[Card],
        opponent_ranges: List[Tuple[Card, Card]],  # Possible opponent hands
        num_opponents: int = 1
    ) -> float:
        """
        Run Monte Carlo simulation to estimate win probability.
        
        Returns:
            Equity as float 0.0–1.0
        """
        deck = Deck()
        deck.remove(hole_cards)
        deck.remove(community_cards)
        
        wins = 0
        ties = 0
        
        for _ in range(self.iterations):
            # Sample opponent hands from their range
            opponent_hands = []
            for _ in range(num_opponents):
                if opponent_ranges:
                    hand = random.choice(opponent_ranges)
                    # Remove sampled cards from deck
                    for c in hand:
                        if c in deck.cards:
                            deck.cards.remove(c)
                    opponent_hands.append(hand)
            
            # Deal remaining community cards
            remaining = 5 - len(community_cards)
            runout = deck.draw(remaining)
            full_board = community_cards + runout
            
            # Evaluate all hands
            my_score, _ = HandEvaluator.evaluate(hole_cards, full_board)
            
            best = True
            for opp_hand in opponent_hands:
                opp_score, _ = HandEvaluator.evaluate(opp_hand, full_board)
                if opp_score > my_score:
                    best = False
                    break
                elif opp_score == my_score:
                    # Could refine tie-breaking here
                    pass
            
            if best:
                wins += 1
            # Could track ties separately for more precision
        
        return wins / self.iterations
    
    def estimate_vs_random(
        self,
        hole_cards: List[Card],
        community_cards: List[Card],
        num_opponents: int = 1
    ) -> float:
        """
        Estimate equity against random hands (no range info).
        Faster but less accurate than range-based estimation.
        """
        deck = Deck()
        deck.remove(hole_cards)
        deck.remove(community_cards)
        
        wins = 0
        
        for _ in range(self.iterations):
            # Deal random opponent hands
            opponent_hands = []
            for _ in range(num_opponents):
                hand = deck.draw(2)
                opponent_hands.append(hand)
            
            # Deal remaining community cards
            remaining = 5 - len(community_cards)
            runout = deck.draw(remaining)
            full_board = community_cards + runout
            
            # Evaluate
            my_score, _ = HandEvaluator.evaluate(hole_cards, full_board)
            
            best = True
            for opp_hand in opponent_hands:
                opp_score, _ = HandEvaluator.evaluate(opp_hand, full_board)
                if opp_score > my_score:
                    best = False
                    break
            
            if best:
                wins += 1
        
        return wins / self.iterations
```

**Integration with existing AI:**

```python
# In DesignedBotStrategy._noisy_equity():
def _noisy_equity(self, equity: float) -> float:
    # Use Monte Carlo if available and time permits
    if self.use_monte_carlo and self.time_remaining > 100:  # ms
        mc_equity = self.mc_estimator.estimate_vs_random(
            self.hole_cards,
            self.community_cards,
            num_opponents=self.num_active - 1
        )
        # Blend heuristic and Monte Carlo
        equity = 0.3 * equity + 0.7 * mc_equity
    
    # Apply difficulty noise as before
    ...
```

---

### Feature 2: Hand Range Modeling

**File: `advanced/ranges.py`**

```python
from typing import Dict, List, Set, Tuple
from core.card import Card, Rank
from dataclasses import dataclass


@dataclass
class HandRange:
    """
    Represents a range of possible hands with weights.
    
    Example:
        # Top 10% of hands
        range = HandRange.from_percentage(0.10)
        
        # Custom range
        range = HandRange()
        range.add_hand(Rank.ACE, Rank.KING, suited=True, weight=1.0)
        range.add_hand(Rank.ACE, Rank.QUEEN, suited=False, weight=0.5)
    """
    
    # (high_rank, low_rank, suited) -> weight (0.0–1.0)
    hands: Dict[Tuple[int, int, bool], float] = None
    
    def __post_init__(self):
        if self.hands is None:
            self.hands = {}
    
    @classmethod
    def from_percentage(cls, pct: float) -> 'HandRange':
        """Create a range from top X% of hands (by preflop strength)."""
        from strategies.hand_score import _PAIR_SCORES, _HAND_TABLE
        
        range_inst = cls()
        
        # Collect all hands with their scores
        all_hands = []
        for rank, score in _PAIR_SCORES.items():
            all_hands.append(((rank, rank, False), score))
        
        for (high, low, suited), score in _HAND_TABLE.items():
            all_hands.append(((high, low, suited), score))
        
        # Sort by score descending
        all_hands.sort(key=lambda x: x[1], reverse=True)
        
        # Take top percentage
        cutoff_idx = int(len(all_hands) * pct)
        for i in range(cutoff_idx):
            hand, score = all_hands[i]
            range_inst.hands[hand] = 1.0
        
        return range_inst
    
    def add_hand(self, high: int, low: int, suited: bool, weight: float = 1.0):
        """Add a specific hand to the range."""
        self.hands[(high, low, suited)] = weight
    
    def remove_hand(self, high: int, low: int, suited: bool):
        """Remove a hand from the range."""
        self.hands.pop((high, low, suited), None)
    
    def get_possible_hands(self, known_cards: List[Card]) -> List[Tuple[Card, Card]]:
        """
        Get all possible hand combinations from the range,
        excluding hands that contain known cards.
        """
        from core.card import Card
        
        known_ranks = {c.rank for c in known_cards}
        known_suits = {c.suit for c in known_cards}
        
        possible = []
        for (high, low, suited), weight in self.hands.items():
            if weight <= 0:
                continue
            
            # Generate actual card combinations
            if high == low:
                # Pocket pair: need 2 cards of same rank, different suits
                suits_for_pair = [s for s in range(4) if s not in known_suits or len(known_suits) < 2]
                if len(suits_for_pair) >= 2:
                    possible.append((
                        (Card(high, suits_for_pair[0]), Card(high, suits_for_pair[1])),
                        weight
                    ))
            else:
                # Non-pair
                high_suits = [s for s in range(4) if s not in known_suits]
                low_suits = [s for s in range(4) if s not in known_suits]
                
                if suited:
                    for s in high_suits:
                        if s in low_suits:
                            possible.append((
                                (Card(high, s), Card(low, s)),
                                weight
                            ))
                else:
                    for hs in high_suits:
                        for ls in low_suits:
                            if hs != ls:
                                possible.append((
                                    (Card(high, hs), Card(low, ls)),
                                    weight
                                ))
        
        return possible
    
    def apply_board_interaction(self, board: List[Card]) -> 'HandRange':
        """
        Return a new range weighted by how well hands connect with the board.
        Hands that hit the board (pairs, draws) get higher weight.
        """
        new_range = HandRange()
        board_ranks = {c.rank for c in board}
        board_suits = [c.suit for c in board]
        
        for (high, low, suited), weight in self.hands.items():
            new_weight = weight
            
            # Pair on board
            if high in board_ranks or low in board_ranks:
                new_weight *= 1.5
            
            # Suited with board (flush potential)
            if suited:
                # Check if board has cards of same suit
                pass  # Would need actual suit info
            
            new_range.hands[(high, low, suited)] = min(1.0, new_weight)
        
        return new_range
    
    def combo_count(self) -> int:
        """Return total number of hand combinations in the range."""
        count = 0
        for (high, low, suited), weight in self.hands.items():
            if high == low:
                count += int(6 * weight)  # 6 combos for each pair
            elif suited:
                count += int(4 * weight)  # 4 suited combos
            else:
                count += int(12 * weight)  # 12 offsuit combos
        return count
```

---

### Feature 3: Opponent Modeling

**File: `advanced/opponent_model.py`**

```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class TendencyType(Enum):
    VPIP = "vpip"           # Voluntary Put $ In Pot
    PFR = "pfr"             # Preflop Raise
    AF = "af"               # Aggression Factor
    WTSD = "wtsd"           # Went to Showdown
    WWSF = "wwsf"           # Won $ When Saw Flop
    FOLD_TO_STEAL = "fold_to_steal"
    CALL_3BET = "call_3bet"
    CBET = "cbet"           # Continuation bet frequency


@dataclass
class PlayerTendencies:
    """Tracks statistical tendencies for an opponent."""
    player_id: str
    
    # Raw counts
    vpip_attempts: int = 0
    vpip_calls: int = 0
    pfr_attempts: int = 0
    pfr_raises: int = 0
    af_bets: int = 0
    af_calls: int = 0
    wtsd_reached: int = 0
    wtsd_won: int = 0
    fold_to_steal_attempts: int = 0
    fold_to_steal_folds: int = 0
    call_3bet_attempts: int = 0
    call_3bet_calls: int = 0
    cbet_attempts: int = 0
    cbet_made: int = 0
    
    # Derived stats (computed on demand)
    @property
    def vpip(self) -> float:
        if self.vpip_attempts == 0:
            return 0.30  # Default
        return self.vpip_calls / self.vpip_attempts
    
    @property
    def pfr(self) -> float:
        if self.pfr_attempts == 0:
            return 0.15  # Default
        return self.pfr_raises / self.pfr_attempts
    
    @property
    def aggression_factor(self) -> float:
        if self.af_calls == 0:
            return 1.0  # Default
        return (self.af_bets + self.af_calls) / (self.af_calls * 2) if self.af_calls > 0 else 2.0
    
    @property
    def wtsd(self) -> float:
        if self.wtsd_reached == 0:
            return 0.25  # Default
        return self.wtsd_won / self.wtsd_reached
    
    @property
    def fold_to_steal(self) -> float:
        if self.fold_to_steal_attempts == 0:
            return 0.60  # Default
        return self.fold_to_steal_folds / self.fold_to_steal_attempts
    
    def classify_player(self) -> str:
        """Classify player type based on tendencies."""
        if self.vpip < 0.20:
            if self.aggression_factor > 1.5:
                return "tight_aggressive"
            return "tight_passive"
        elif self.vpip > 0.40:
            if self.aggression_factor > 1.5:
                return "loose_aggressive"
            return "loose_passive"
        else:
            if self.aggression_factor > 1.5:
                return "balanced_aggressive"
            return "balanced_passive"


class OpponentModeler:
    """
    Tracks and utilizes opponent tendencies for exploitative play.
    """
    
    def __init__(self):
        self.tendencies: Dict[str, PlayerTendencies] = {}
    
    def get_tendencies(self, player_id: str) -> PlayerTendencies:
        if player_id not in self.tendencies:
            self.tendencies[player_id] = PlayerTendencies(player_id)
        return self.tendencies[player_id]
    
    def record_action(self, player_id: str, action: str, context: dict):
        """
        Record an action for opponent modeling.
        
        Args:
            player_id: The opponent's ID
            action: Action taken (fold, call, raise, check, bet)
            context: Dict with street, position, is_steal_attempt, etc.
        """
        t = self.get_tendencies(player_id)
        
        # Preflop tracking
        if context.get('street') == 'preflop':
            if action in ('call', 'raise'):
                t.vpip_attempts += 1
                t.vpip_calls += 1
            elif action == 'fold':
                t.vpip_attempts += 1
            
            if action == 'raise':
                t.pfr_attempts += 1
                t.pfr_raises += 1
            elif action in ('call', 'fold'):
                t.pfr_attempts += 1
        
        # Postflop aggression
        elif action in ('bet', 'raise'):
            t.af_bets += 1
        elif action == 'call':
            t.af_calls += 1
        
        # Showdown tracking
        if context.get('reached_showdown'):
            t.wtsd_reached += 1
            if context.get('won_hand'):
                t.wtsd_won += 1
        
        # Steal situations
        if context.get('is_steal_attempt'):
            t.fold_to_steal_attempts += 1
            if action == 'fold':
                t.fold_to_steal_folds += 1
        
        # 3-bet situations
        if context.get('facing_3bet'):
            t.call_3bet_attempts += 1
            if action == 'call':
                t.call_3bet_calls += 1
        
        # C-bet tracking
        if context.get('is_cbet_spot'):
            t.cbet_attempts += 1
            if action in ('bet', 'raise'):
                t.cbet_made += 1
    
    def get_exploitative_adjustment(self, player_id: str, my_action: str) -> dict:
        """
        Return exploitative adjustments based on opponent tendencies.
        
        Returns dict with suggested action modifications.
        """
        t = self.get_tendencies(player_id)
        adjustments = {}
        
        # Against high fold-to-steal: bluff more
        if t.fold_to_steal > 0.70:
            adjustments['bluff_freq_boost'] = 0.30
            adjustments['value_range_widen'] = True
        
        # Against low fold-to-steal: value bet thinner, bluff less
        if t.fold_to_steal < 0.40:
            adjustments['bluff_freq_reduction'] = 0.20
            adjustments['value_range_thin'] = True
        
        # Against high WTSD: value bet thinner
        if t.wtsd > 0.35:
            adjustments['value_call_down_lighter'] = True
        
        # Against low WTSD (folder): c-bet more, bluff more
        if t.wtsd < 0.20:
            adjustments['cbet_freq_boost'] = 0.25
            adjustments['bluff_freq_boost'] = 0.20
        
        # Against high aggression: trap more, bluff-catch more
        if t.aggression_factor > 2.5:
            adjustments['trap_freq_boost'] = True
            adjustments['bluff_catch_lighter'] = True
        
        # Against low aggression (passive): bluff less, value bet thinner
        if t.aggression_factor < 0.8:
            adjustments['bluff_freq_reduction'] = 0.15
            adjustments['fold_to_bluff_tighter'] = True
        
        return adjustments
```

---

### Feature 4: Counterfactual Regret Minimization (CFR)

**File: `advanced/cfr.py`**

```python
"""
Simplified Counterfactual Regret Minimization for approximate GTO play.

This is a lightweight implementation suitable for real-time play.
For full GTO, consider pre-computed solver outputs.
"""
import random
from typing import Dict, List, Tuple
from dataclasses import dataclass
from core.card import Card


@dataclass
class InformationSet:
    """
    Represents a decision point defined by:
    - Our cards
    - Board state
    - Action history (abstracted)
    - Position
    - Stack-to-pot ratio
    """
    hole_cards: Tuple[Card, Card]
    board: Tuple[Card, ...]
    street: str  # 'preflop', 'flop', 'turn', 'river'
    position: str  # 'ip' (in position) or 'oop' (out of position)
    spr: float  # Stack-to-pot ratio
    action_abstract: str  # e.g., "faced_bet", "checked_to", "opened"


class CFRTrainer:
    """
    Train CFR strategies through self-play.
    
    Note: Full CFR training takes millions of iterations.
    This is a simplified version for demonstration.
    """
    
    def __init__(self):
        # Regret sums and strategy tables for each information set
        self.regret_sums: Dict[str, Dict[str, float]] = {}
        self.strategy_sums: Dict[str, Dict[str, float]] = {}
        self.visit_counts: Dict[str, int] = {}
    
    def _get_info_set_key(self, info_set: InformationSet) -> str:
        """Convert information set to hashable string key."""
        # Abstract cards to rank combinations for tractability
        hc = tuple(sorted([c.rank for c in info_set.hole_cards]))
        board_ranks = tuple(sorted([c.rank for c in info_set.board]))
        return f"{hc}|{info_set.street}|{info_set.position}|{info_set.action_abstract}"
    
    def get_strategy(self, info_set: InformationSet) -> Dict[str, float]:
        """
        Get strategy for an information set (probabilities for each action).
        
        Returns dict like: {'fold': 0.1, 'call': 0.4, 'raise': 0.5}
        """
        key = self._get_info_set_key(info_set)
        
        if key not in self.strategy_sums:
            # Initialize with uniform strategy
            return {'fold': 0.33, 'call': 0.34, 'raise': 0.33}
        
        # Normalize strategy sums to get probabilities
        strat_sum = self.strategy_sums[key]
        total = sum(strat_sum.values())
        if total == 0:
            return {'fold': 0.33, 'call': 0.34, 'raise': 0.33}
        
        return {a: v / total for a, v in strat_sum.items()}
    
    def update_regrets(self, info_set: InformationSet, action: str, counterfactual_value: float):
        """Update regret sums based on counterfactual value."""
        key = self._get_info_set_key(info_set)
        
        if key not in self.regret_sums:
            self.regret_sums[key] = {'fold': 0.0, 'call': 0.0, 'raise': 0.0}
        
        # Regret = value of action - value of current strategy
        # Simplified: just accumulate counterfactual values
        self.regret_sums[key][action] += counterfactual_value
    
    def update_strategy(self, info_set: InformationSet, action: str, probability: float):
        """Add to strategy sum for regret matching."""
        key = self._get_info_set_key(info_set)
        
        if key not in self.strategy_sums:
            self.strategy_sums[key] = {'fold': 0.0, 'call': 0.0, 'raise': 0.0}
            self.visit_counts[key] = 0
        
        self.strategy_sums[key][action] += probability
        self.visit_counts[key] += 1
    
    def regret_matching(self, info_set: InformationSet) -> Dict[str, float]:
        """
        Compute strategy using regret matching.
        
        Action probability proportional to positive regret sum.
        """
        key = self._get_info_set_key(info_set)
        
        if key not in self.regret_sums:
            return {'fold': 0.33, 'call': 0.34, 'raise': 0.33}
        
        regrets = self.regret_sums[key]
        
        # Only positive regrets contribute to strategy
        positive_regrets = {a: max(0, r) for a, r in regrets.items()}
        total = sum(positive_regrets.values())
        
        if total == 0:
            return {'fold': 0.33, 'call': 0.34, 'raise': 0.33}
        
        return {a: r / total for a, r in positive_regrets.items()}


class GTOAdvisor:
    """
    Provides GTO-adjacent recommendations using pre-trained CFR data.
    Can be used to blend with exploitative play.
    """
    
    def __init__(self):
        self.cfr = CFRTrainer()
        self._load_pretrained()  # Would load from file in production
    
    def _load_pretrained(self):
        """Load pre-trained CFR strategy (placeholder)."""
        # In production, this would load from a file
        # For now, the CFR trainer starts fresh
        pass
    
    def recommend_action(self, info_set: InformationSet) -> Tuple[str, Dict[str, float]]:
        """
        Get GTO recommendation for a decision point.
        
        Returns:
            (recommended_action, strategy_distribution)
        """
        strategy = self.cfr.get_strategy(info_set)
        best_action = max(strategy, key=strategy.get)
        return best_action, strategy
    
    def blend_with_exploitative(
        self,
        gto_strategy: Dict[str, float],
        exploitative_strategy: Dict[str, float],
        exploitation_weight: float = 0.3
    ) -> Dict[str, float]:
        """
        Blend GTO and exploitative strategies.
        
        Args:
            gto_strategy: GTO strategy distribution
            exploitative_strategy: Exploitative strategy distribution
            exploitation_weight: 0.0 = pure GTO, 1.0 = pure exploitative
        
        Returns:
            Blended strategy distribution
        """
        blended = {}
        for action in gto_strategy:
            gto = gto_strategy.get(action, 0.0)
            exp = exploitative_strategy.get(action, 0.0)
            blended[action] = gto * (1 - exploitation_weight) + exp * exploitation_weight
        
        # Normalize
        total = sum(blended.values())
        if total > 0:
            blended = {a: v / total for a, v in blended.items()}
        
        return blended
```

---

## Part 3: Implementation Priority

### Phase 1: Quick Wins (1-2 weeks)

| Feature | Effort | Impact | Priority |
|---------|--------|--------|----------|
| Monte Carlo equity | Medium | High | P0 |
| Better preflop ranges | Low | Medium | P0 |
| Opponent tracking (basic) | Low | Medium | P1 |

### Phase 2: Core Improvements (2-4 weeks)

| Feature | Effort | Impact | Priority |
|---------|--------|--------|----------|
| Full range modeling | High | High | P0 |
| Opponent modeling (full) | Medium | High | P0 |
| Exploitative adjustments | Medium | High | P0 |
| Multi-street planning | High | Medium | P1 |

### Phase 3: Advanced Features (4-8 weeks)

| Feature | Effort | Impact | Priority |
|---------|--------|--------|----------|
| CFR training | Very High | Medium | P2 |
| GTO blending | High | Medium | P2 |
| ICM calculations | Medium | Low (cash) / High (tournament) | P1 |

---

## Part 4: Integration Example

Here's how the advanced AI would integrate with the existing system:

```python
# strategies/hybrid.py

from typing import Tuple
from core.player import PlayerAction
from strategies import BotStrategy, PlayerView, register
from strategies.engine import DesignedBotStrategy
from strategies.advanced.monte_carlo import MonteCarloEquity
from strategies.advanced.opponent_model import OpponentModeler
from strategies.advanced.ranges import HandRange


@register('advanced')
class AdvancedBotStrategy(BotStrategy):
    """
    Hybrid AI that combines:
    - Heuristic decision-making (fast, good enough)
    - Monte Carlo equity (accurate, slower)
    - Opponent modeling (exploitative)
    - Range analysis (GTO-adjacent)
    
    Configurable for different difficulty levels.
    """
    
    def __init__(
        self,
        difficulty: float = 0.6,
        use_monte_carlo: bool = True,
        mc_iterations: int = 5000,
        use_opponent_modeling: bool = True,
        exploitation_weight: float = 0.3
    ):
        self.difficulty = difficulty
        self.use_monte_carlo = use_monte_carlo
        self.use_opponent_modeling = use_opponent_modeling
        self.exploitation_weight = exploitation_weight
        
        self.mc_estimator = MonteCarloEquity(iterations=mc_iterations)
        self.opponent_modeler = OpponentModeler() if use_opponent_modeling else None
        
        # Fallback to designed strategy for speed
        self.heuristic_bot = DesignedBotStrategy(
            profile=PROFILES['balanced'],
            difficulty=difficulty
        )
    
    def decide(self, game_state: dict, player: PlayerView) -> Tuple[PlayerAction, int]:
        # Record opponent actions for modeling
        if self.use_opponent_modeling:
            self._record_opponent_actions(game_state)
        
        # Get heuristic action (fast)
        heuristic_action, heuristic_amt = self.heuristic_bot.decide(game_state, player)
        
        # If low difficulty, use heuristic only
        if self.difficulty < 0.5:
            return heuristic_action, heuristic_amt
        
        # Get Monte Carlo equity if time permits
        if self.use_monte_carlo:
            mc_equity = self.mc_estimator.estimate_vs_random(
                player.hole_cards,
                game_state.get('community_cards', []),
                num_opponents=game_state.get('num_active', 2) - 1
            )
            
            # Override heuristic if Monte Carlo suggests different play
            if mc_equity > 0.70 and heuristic_action == PlayerAction.FOLD:
                return PlayerAction.RAISE, self._calc_raise_amount(game_state, player)
            elif mc_equity < 0.20 and heuristic_action in (PlayerAction.CALL, PlayerAction.RAISE):
                return PlayerAction.FOLD, 0
        
        # Apply exploitative adjustments
        if self.use_opponent_modeling:
            adjustments = self._get_exploitative_adjustments(game_state)
            heuristic_action, heuristic_amt = self._apply_adjustments(
                heuristic_action, heuristic_amt, adjustments, game_state, player
            )
        
        return heuristic_action, heuristic_amt
    
    def _record_opponent_actions(self, game_state: dict):
        """Record opponent actions for modeling."""
        # Implementation would parse hand_log and record actions
        pass
    
    def _get_exploitative_adjustments(self, game_state: dict) -> dict:
        """Get exploitative adjustments based on opponent tendencies."""
        # Implementation would query opponent modeler
        return {}
    
    def _apply_adjustments(self, action, amount, adjustments, game_state, player):
        """Apply exploitative adjustments to action."""
        # Implementation would modify action based on adjustments
        return action, amount
    
    def _calc_raise_amount(self, game_state, player):
        """Calculate raise amount based on game state."""
        pot_size = game_state.get('pot_size', 0)
        min_call = game_state.get('min_call', 0)
        min_raise = game_state.get('min_raise', 0)
        fraction = 0.75  # Could be smarter
        return min(player.chips, int(pot_size * fraction) + min_call)
```

---

## Conclusion

The current AI is **solid for casual play** but has significant room for improvement:

### Keep (Don't Change)
- Style profile architecture
- Difficulty noise injection
- Hand scoring table
- Clean code structure

### Improve
1. **Equity calculation** → Monte Carlo simulation
2. **Opponent analysis** → Range modeling + tendency tracking
3. **Bet sizing** → Context-aware (board texture, SPR, ranges)
4. **Multi-street play** → Planning with implied odds

### Add (New Features)
1. **Opponent modeling system** → Track and exploit tendencies
2. **GTO advisor** → CFR-based recommendations
3. **Hybrid AI** → Blend heuristic speed with Monte Carlo accuracy

The advanced AI design maintains backward compatibility while adding powerful new capabilities. Implementation can be phased, starting with Monte Carlo equity (highest impact, lowest risk).
