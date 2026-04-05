"""
Unit tests for bot strategies.
No game infrastructure needed — strategies are tested in pure isolation.
Run with: pytest tests/test_strategies.py -v
"""
import pytest
from core.card import Card, Suit, Rank
from core.player import PlayerAction
from strategies import PlayerView, REGISTRY
from strategies.simple import SimpleStrategy
from strategies.engine import (
    DesignedBotStrategy,
    TightPassiveStrategy, TightAggressiveStrategy,
    LoosePassiveStrategy, LooseAggressiveStrategy,
    ManiacStrategy, NitStrategy, BalancedStrategy, TrapperStrategy,
)
from strategies.profile import PROFILES, StyleProfile
from strategies.hand_score import score_starting_hand
from strategies.difficulty import DIFFICULTY_LEVELS, NORMAL, HARD, EASY
from strategies.utils import estimate_equity, pot_odds, position_adjustment, calc_raise_amount


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_view(chips=1000, hole_cards=None):
    if hole_cards is None:
        hole_cards = [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)]
    return PlayerView(chips=chips, hole_cards=hole_cards)


def state(min_call=0, min_raise=20, pot_size=100, community_cards=None,
          position=0, num_active=4):
    return {
        'min_call': min_call,
        'min_raise': min_raise,
        'pot_size': pot_size,
        'community_cards': community_cards or [],
        'position': position,
        'num_active': num_active,
        'players_info': [],
        'hand_log': [],
    }


WEAK_HAND   = [Card(Rank.TWO, Suit.CLUBS),  Card(Rank.SEVEN, Suit.HEARTS)]
STRONG_HAND = [Card(Rank.ACE, Suit.SPADES), Card(Rank.ACE, Suit.HEARTS)]
MEDIUM_HAND = [Card(Rank.NINE, Suit.SPADES), Card(Rank.EIGHT, Suit.HEARTS)]


# ---------------------------------------------------------------------------
# PlayerView
# ---------------------------------------------------------------------------

class TestPlayerView:
    def test_is_frozen(self):
        view = make_view()
        with pytest.raises(Exception):
            view.chips = 500

    def test_holds_correct_data(self):
        view = PlayerView(chips=800, hole_cards=STRONG_HAND)
        assert view.chips == 800
        assert view.hole_cards == STRONG_HAND


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_simple_registered(self):
        assert 'simple' in REGISTRY

    def test_all_designed_styles_registered(self):
        for name in ('tight_passive', 'tight_aggressive', 'loose_passive',
                     'loose_aggressive', 'maniac', 'nit', 'balanced'):
            assert name in REGISTRY, f"'{name}' not in REGISTRY"

    def test_registry_values_implement_decide(self):
        for name, cls in REGISTRY.items():
            instance = cls()
            assert callable(getattr(instance, 'decide', None)), \
                f"{name} must implement decide()"


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

class TestProfiles:
    def test_all_seven_profiles_exist(self):
        for name in ('tight_passive', 'tight_aggressive', 'loose_passive',
                     'loose_aggressive', 'maniac', 'nit', 'balanced'):
            assert name in PROFILES

    def test_nit_tighter_than_maniac(self):
        assert PROFILES['nit'].play_range < PROFILES['maniac'].play_range

    def test_lag_more_aggressive_than_tp(self):
        assert PROFILES['loose_aggressive'].aggression > PROFILES['tight_passive'].aggression

    def test_maniac_highest_bluff_freq(self):
        assert PROFILES['maniac'].bluff_freq == max(p.bluff_freq for p in PROFILES.values())

    def test_loose_passive_highest_call_freq(self):
        assert PROFILES['loose_passive'].call_freq >= max(
            p.call_freq for n, p in PROFILES.items() if n != 'loose_passive'
        )


# ---------------------------------------------------------------------------
# Difficulty
# ---------------------------------------------------------------------------

class TestDifficulty:
    def test_all_levels_present(self):
        for name in ('very_easy', 'easy', 'normal', 'hard', 'expert', 'perfect'):
            assert name in DIFFICULTY_LEVELS

    def test_difficulty_ordering(self):
        vals = list(DIFFICULTY_LEVELS.values())
        assert vals == sorted(vals)

    def test_perfect_is_one(self):
        assert DIFFICULTY_LEVELS['perfect'] == 1.0


# ---------------------------------------------------------------------------
# Hand score
# ---------------------------------------------------------------------------

class TestHandScore:
    def test_aa_is_100(self):
        assert score_starting_hand(
            Card(Rank.ACE, Suit.SPADES), Card(Rank.ACE, Suit.HEARTS)) == 100

    def test_kk_is_98(self):
        assert score_starting_hand(
            Card(Rank.KING, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)) == 98

    def test_aks_is_95(self):
        assert score_starting_hand(
            Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.SPADES)) == 95

    def test_ako_is_90(self):
        assert score_starting_hand(
            Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)) == 90

    def test_kqo_is_80(self):
        assert score_starting_hand(
            Card(Rank.KING, Suit.SPADES), Card(Rank.QUEEN, Suit.HEARTS)) == 80

    def test_j7_is_20(self):
        assert score_starting_hand(
            Card(Rank.JACK, Suit.SPADES), Card(Rank.SEVEN, Suit.HEARTS)) == 20

    def test_72_is_5(self):
        assert score_starting_hand(
            Card(Rank.SEVEN, Suit.CLUBS), Card(Rank.TWO, Suit.HEARTS)) == 5

    def test_suited_beats_offsuit(self):
        suited   = score_starting_hand(Card(Rank.TEN, Suit.CLUBS),  Card(Rank.NINE, Suit.CLUBS))
        offsuit  = score_starting_hand(Card(Rank.TEN, Suit.CLUBS),  Card(Rank.NINE, Suit.HEARTS))
        assert suited > offsuit

    def test_returns_int(self):
        assert isinstance(score_starting_hand(
            Card(Rank.FIVE, Suit.SPADES), Card(Rank.THREE, Suit.HEARTS)), int)

    def test_score_between_0_and_100(self):
        import itertools
        from core.card import Rank as R, Suit as S
        for r1, r2 in itertools.combinations_with_replacement(R.get_all(), 2):
            for suited in [True, False]:
                if suited and r1 == r2:
                    continue
                suit2 = S.SPADES if suited else S.HEARTS
                s = score_starting_hand(Card(r1, S.SPADES), Card(r2, suit2))
                assert 0 <= s <= 100, f"score out of range for ({r1},{r2},suited={suited}): {s}"


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

class TestUtils:
    def test_estimate_equity_preflop_strong(self):
        eq = estimate_equity(STRONG_HAND, [])
        assert eq == 0.55

    def test_estimate_equity_preflop_weak(self):
        eq = estimate_equity(WEAK_HAND, [])
        assert eq == 0.32

    def test_estimate_equity_postflop(self):
        community = [
            Card(Rank.ACE, Suit.CLUBS),
            Card(Rank.ACE, Suit.DIAMONDS),
            Card(Rank.KING, Suit.CLUBS),
        ]
        eq = estimate_equity(STRONG_HAND, community)
        assert eq >= 0.90

    def test_pot_odds_standard(self):
        assert pot_odds(100, 300) == pytest.approx(0.25)

    def test_pot_odds_zero_call(self):
        assert pot_odds(0, 200) == 0.0

    def test_position_adjustment_button(self):
        assert position_adjustment(0, 6) == -0.08

    def test_position_adjustment_blinds(self):
        assert position_adjustment(1, 6) == +0.06

    def test_calc_raise_amount_never_below_min(self):
        amt = calc_raise_amount(0, 20, 20, 1000, 0.5)
        assert amt >= 40

    def test_calc_raise_amount_capped_at_chips(self):
        amt = calc_raise_amount(10000, 0, 20, 100, 1.0)
        assert amt == 100


# ---------------------------------------------------------------------------
# SimpleStrategy (unchanged)
# ---------------------------------------------------------------------------

class TestSimpleStrategy:
    def test_checks_with_weak_hand_no_call(self):
        strategy = SimpleStrategy(aggressiveness=0.0)
        action, amt = strategy.decide(state(min_call=0), make_view(hole_cards=WEAK_HAND))
        assert action == PlayerAction.CHECK
        assert amt == 0

    def test_folds_weak_hand_large_bet(self):
        strategy = SimpleStrategy(aggressiveness=0.1)
        gs = state(min_call=900, pot_size=100)
        action, _ = strategy.decide(gs, make_view(chips=1000, hole_cards=WEAK_HAND))
        assert action == PlayerAction.FOLD

    def test_all_in_when_call_equals_stack(self):
        strategy = SimpleStrategy(aggressiveness=0.0)
        gs = state(min_call=500, pot_size=1000)
        action, amt = strategy.decide(gs, make_view(chips=500, hole_cards=STRONG_HAND))
        assert action == PlayerAction.ALL_IN
        assert amt == 500

    def test_aggressiveness_default(self):
        s = SimpleStrategy()
        assert s.aggressiveness == 0.5


# ---------------------------------------------------------------------------
# TightPassiveStrategy
# ---------------------------------------------------------------------------

class TestTightPassiveStrategy:
    def test_folds_weak_hand_facing_bet(self):
        strategy = TightPassiveStrategy()
        gs = state(min_call=200, pot_size=100)
        action, _ = strategy.decide(gs, make_view(chips=1000, hole_cards=WEAK_HAND))
        assert action == PlayerAction.FOLD

    def test_checks_or_folds_medium_hand(self):
        """Tight-passive rarely raises with medium hands."""
        import random
        random.seed(0)
        strategy = TightPassiveStrategy()
        medium = [Card(Rank.JACK, Suit.CLUBS), Card(Rank.TWO, Suit.HEARTS)]
        gs = state(min_call=0, pot_size=100)
        raises = sum(1 for _ in range(50)
                     if strategy.decide(gs, make_view(hole_cards=medium))[0]
                     == PlayerAction.RAISE)
        assert raises <= 15  # tight-passive rarely raises with medium hands

    def test_raises_less_than_lag(self):
        import random
        random.seed(5)
        tp  = TightPassiveStrategy()
        lag = LooseAggressiveStrategy()
        gs  = state(min_call=0, pot_size=100)
        view = make_view(hole_cards=STRONG_HAND)
        tp_raises  = sum(1 for _ in range(50) if tp.decide(gs, view)[0]  == PlayerAction.RAISE)
        lag_raises = sum(1 for _ in range(50) if lag.decide(gs, view)[0] == PlayerAction.RAISE)
        assert lag_raises >= tp_raises


# ---------------------------------------------------------------------------
# TightAggressiveStrategy
# ---------------------------------------------------------------------------

class TestTightAggressiveStrategy:
    def test_raises_frequently_with_strong_hand(self):
        import random
        random.seed(10)
        strategy = TightAggressiveStrategy()
        gs = state(min_call=0, pot_size=100)
        raises = sum(1 for _ in range(100)
                     if strategy.decide(gs, make_view(hole_cards=STRONG_HAND))[0]
                     == PlayerAction.RAISE)
        assert raises >= 50  # TAG raises ~aggression% of the time with strong hands

    def test_folds_weak_hand_facing_call(self):
        strategy = TightAggressiveStrategy()
        gs = state(min_call=100, pot_size=100)
        action, _ = strategy.decide(gs, make_view(chips=1000, hole_cards=WEAK_HAND))
        assert action == PlayerAction.FOLD


# ---------------------------------------------------------------------------
# LooseAggressiveStrategy
# ---------------------------------------------------------------------------

class TestLooseAggressiveStrategy:
    def test_raises_frequently_medium_hand(self):
        import random
        random.seed(1)
        strategy = LooseAggressiveStrategy()
        gs = state(min_call=0, pot_size=100)
        raises = sum(1 for _ in range(100)
                     if strategy.decide(gs, make_view(hole_cards=MEDIUM_HAND))[0]
                     == PlayerAction.RAISE)
        assert raises > 30

    def test_raises_more_than_tight_passive(self):
        import random
        random.seed(5)
        lag = LooseAggressiveStrategy()
        tp  = TightPassiveStrategy()
        gs  = state(min_call=0, pot_size=150)
        view = make_view(hole_cards=STRONG_HAND)
        lag_raises = sum(1 for _ in range(50) if lag.decide(gs, view)[0] == PlayerAction.RAISE)
        tp_raises  = sum(1 for _ in range(50) if tp.decide(gs, view)[0]  == PlayerAction.RAISE)
        assert lag_raises >= tp_raises


# ---------------------------------------------------------------------------
# LoosePassiveStrategy
# ---------------------------------------------------------------------------

class TestLoosePassiveStrategy:
    def test_calls_frequently_medium_hand(self):
        import random
        random.seed(2)
        strategy = LoosePassiveStrategy()
        gs = state(min_call=50, pot_size=200)
        calls = sum(1 for _ in range(100)
                    if strategy.decide(gs, make_view(chips=1000, hole_cards=MEDIUM_HAND))[0]
                    in (PlayerAction.CALL, PlayerAction.ALL_IN))
        assert calls >= 50

    def test_rarely_raises(self):
        import random
        random.seed(3)
        strategy = LoosePassiveStrategy()
        gs = state(min_call=0, pot_size=200)
        raises = sum(1 for _ in range(100)
                     if strategy.decide(gs, make_view(hole_cards=STRONG_HAND))[0]
                     == PlayerAction.RAISE)
        assert raises <= 30  # loose-passive rarely raises


# ---------------------------------------------------------------------------
# ManiacStrategy
# ---------------------------------------------------------------------------

class TestManiacStrategy:
    def test_raises_very_frequently(self):
        import random
        random.seed(7)
        strategy = ManiacStrategy()
        gs = state(min_call=0, pot_size=100)
        raises = sum(1 for _ in range(100)
                     if strategy.decide(gs, make_view(hole_cards=MEDIUM_HAND))[0]
                     == PlayerAction.RAISE)
        assert raises > 60  # maniac very often raises

    def test_raises_more_than_balanced(self):
        import random
        random.seed(8)
        maniac   = ManiacStrategy()
        balanced = BalancedStrategy()
        gs   = state(min_call=0, pot_size=100)
        view = make_view(hole_cards=MEDIUM_HAND)
        maniac_raises   = sum(1 for _ in range(100) if maniac.decide(gs, view)[0]   == PlayerAction.RAISE)
        balanced_raises = sum(1 for _ in range(100) if balanced.decide(gs, view)[0] == PlayerAction.RAISE)
        assert maniac_raises > balanced_raises


# ---------------------------------------------------------------------------
# NitStrategy
# ---------------------------------------------------------------------------

class TestNitStrategy:
    def test_folds_medium_hand_facing_call(self):
        """Nit should fold or check most non-premium hands."""
        import random
        random.seed(9)
        strategy = NitStrategy()
        gs = state(min_call=50, pot_size=100)
        folds = sum(1 for _ in range(100)
                    if strategy.decide(gs, make_view(chips=1000, hole_cards=MEDIUM_HAND))[0]
                    == PlayerAction.FOLD)
        assert folds >= 80  # nit almost always folds medium hands

    def test_plays_strong_hand(self):
        import random
        random.seed(11)
        strategy = NitStrategy()
        gs = state(min_call=0, pot_size=100)
        non_checks = sum(1 for _ in range(100)
                         if strategy.decide(gs, make_view(hole_cards=STRONG_HAND))[0]
                         != PlayerAction.FOLD)
        assert non_checks >= 90  # nit plays AA


# ---------------------------------------------------------------------------
# TrapperStrategy
# ---------------------------------------------------------------------------

class TestTrapperStrategy:
    def test_slow_plays_strong_hand_postflop(self):
        """Trapper should check-call with strong hands instead of betting."""
        import random
        random.seed(42)
        strategy = TrapperStrategy()
        # Simulate postflop with strong hand, no bet to face
        gs = state(
            min_call=0, pot_size=100,
            community_cards=[Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS), Card(Rank.ACE, Suit.CLUBS)]
        )
        view = make_view(hole_cards=[Card(Rank.ACE, Suit.DIAMONDS), Card(Rank.QUEEN, Suit.SPADES)])  # Trips
        checks = sum(1 for _ in range(100)
                     if strategy.decide(gs, view)[0] == PlayerAction.CHECK)
        # Trapper has 0.75 slow_play_freq, should check most of the time with trips
        assert checks > 50  # Should check more than half the time

    def test_calls_when_facing_bet_with_monster(self):
        """Trapper should call (not raise) when facing a bet with a monster."""
        import random
        random.seed(55)
        strategy = TrapperStrategy()
        gs = state(
            min_call=50, pot_size=200,
            community_cards=[Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS), Card(Rank.ACE, Suit.CLUBS)]
        )
        view = make_view(
            chips=1000,
            hole_cards=[Card(Rank.ACE, Suit.DIAMONDS), Card(Rank.QUEEN, Suit.SPADES)]
        )
        calls = sum(1 for _ in range(100)
                    if strategy.decide(gs, view)[0] == PlayerAction.CALL)
        # Should call most of the time to trap
        assert calls > 40

    def test_raises_less_than_balanced(self):
        """Trapper should raise less frequently than Balanced with same strong hand."""
        import random
        random.seed(77)
        trapper = TrapperStrategy()
        balanced = BalancedStrategy()
        gs = state(
            min_call=0, pot_size=100,
            community_cards=[Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS), Card(Rank.ACE, Suit.CLUBS)]
        )
        view = make_view(hole_cards=[Card(Rank.ACE, Suit.DIAMONDS), Card(Rank.QUEEN, Suit.SPADES)])
        trapper_raises = sum(1 for _ in range(100) if trapper.decide(gs, view)[0] == PlayerAction.RAISE)
        balanced_raises = sum(1 for _ in range(100) if balanced.decide(gs, view)[0] == PlayerAction.RAISE)
        assert trapper_raises < balanced_raises

    def test_folds_weak_hand(self):
        """Trapper should fold when completely out of range."""
        import random
        random.seed(88)
        strategy = TrapperStrategy()
        gs = state(min_call=100, pot_size=300)
        folds = sum(1 for _ in range(100)
                    if strategy.decide(gs, make_view(hole_cards=WEAK_HAND))[0] == PlayerAction.FOLD)
        assert folds >= 80  # Trapper is selective, folds weak hands facing bets


# ---------------------------------------------------------------------------
# Difficulty
# ---------------------------------------------------------------------------

class TestDifficultyBehavior:
    def test_perfect_difficulty_is_deterministic(self):
        """With perfect difficulty, noise is zero — same seed gives same answer."""
        import random
        profile  = PROFILES['balanced']
        strategy = DesignedBotStrategy(profile, difficulty=1.0)
        gs       = state(min_call=50, pot_size=200)
        view     = make_view(hole_cards=STRONG_HAND)
        random.seed(42)
        a1, amt1 = strategy.decide(gs, view)
        random.seed(42)
        a2, amt2 = strategy.decide(gs, view)
        assert a1 == a2 and amt1 == amt2

    def test_easy_strategy_has_difficulty_attribute(self):
        s = TightAggressiveStrategy(difficulty=EASY)
        assert s.difficulty == EASY


# ---------------------------------------------------------------------------
# Cross-strategy invariants
# ---------------------------------------------------------------------------

class TestCrossStrategy:
    def test_all_strategies_return_valid_action(self):
        strategies = [
            SimpleStrategy(),
            TightPassiveStrategy(), TightAggressiveStrategy(),
            LoosePassiveStrategy(), LooseAggressiveStrategy(),
            ManiacStrategy(), NitStrategy(), BalancedStrategy(),
            TrapperStrategy(),
        ]
        game_states = [
            state(min_call=0),
            state(min_call=50, pot_size=200),
            state(min_call=1000, pot_size=50),
        ]
        views = [
            make_view(chips=1000, hole_cards=STRONG_HAND),
            make_view(chips=50,   hole_cards=WEAK_HAND),
        ]
        valid = set(PlayerAction)
        for s in strategies:
            for gs in game_states:
                for v in views:
                    action, amt = s.decide(gs, v)
                    assert action in valid, f"{s.__class__.__name__} returned invalid action"
                    assert isinstance(amt, int)
                    assert amt >= 0

    def test_no_strategy_bets_more_than_chips(self):
        strategies = [
            ManiacStrategy(), LooseAggressiveStrategy(),
            SimpleStrategy(aggressiveness=1.0),
        ]
        view = make_view(chips=100)
        gs   = state(min_call=0, pot_size=10000)
        for s in strategies:
            _, amt = s.decide(gs, view)
            assert amt <= 100, f"{s.__class__.__name__} bet more than chips"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
