"""
Unit tests for bot strategies.
No game infrastructure needed — strategies are tested in pure isolation.
Run with: pytest test_strategies.py -v
"""
import pytest
from card import Card, Suit, Rank
from player import PlayerAction
from strategies import PlayerView, REGISTRY
from strategies.simple import SimpleStrategy
from strategies.archetypes import TightPassiveStrategy, LooseAggressiveStrategy, CallingStationStrategy
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


WEAK_HAND  = [Card(Rank.TWO, Suit.CLUBS),  Card(Rank.SEVEN, Suit.HEARTS)]
STRONG_HAND = [Card(Rank.ACE, Suit.SPADES), Card(Rank.ACE, Suit.HEARTS)]


# ---------------------------------------------------------------------------
# PlayerView
# ---------------------------------------------------------------------------

class TestPlayerView:
    def test_is_frozen(self):
        view = make_view()
        with pytest.raises(Exception):
            view.chips = 500  # frozen=True prevents mutation

    def test_holds_correct_data(self):
        cards = STRONG_HAND
        view = PlayerView(chips=800, hole_cards=cards)
        assert view.chips == 800
        assert view.hole_cards == cards


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_simple_registered(self):
        assert 'simple' in REGISTRY

    def test_archetypes_registered(self):
        assert 'tight_passive'    in REGISTRY
        assert 'loose_aggressive' in REGISTRY
        assert 'calling_station'  in REGISTRY

    def test_registry_values_are_classes(self):
        for name, cls in REGISTRY.items():
            instance = cls()
            assert callable(getattr(instance, 'decide', None)), \
                f"{name} strategy must implement decide()"


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
        assert eq >= 0.90  # quad aces / full house = very strong

    def test_pot_odds_standard(self):
        # pot=300, call=100 → 100/400 = 0.25
        assert pot_odds(100, 300) == pytest.approx(0.25)

    def test_pot_odds_zero_call(self):
        assert pot_odds(0, 200) == 0.0

    def test_position_adjustment_button(self):
        adj = position_adjustment(0, 6)
        assert adj == -0.08  # button plays looser

    def test_position_adjustment_blinds(self):
        adj = position_adjustment(1, 6)
        assert adj == +0.06  # SB plays tighter

    def test_position_adjustment_heads_up(self):
        assert position_adjustment(0, 2) == 0.0
        assert position_adjustment(1, 2) == 0.0

    def test_calc_raise_amount_never_below_min(self):
        amt = calc_raise_amount(pot_size=0, min_call=20, min_raise=20,
                                chips=1000, fraction=0.5)
        assert amt >= 40  # min_raise + min_call

    def test_calc_raise_amount_capped_at_chips(self):
        amt = calc_raise_amount(pot_size=10000, min_call=0, min_raise=20,
                                chips=100, fraction=1.0)
        assert amt == 100


# ---------------------------------------------------------------------------
# SimpleStrategy
# ---------------------------------------------------------------------------

class TestSimpleStrategy:
    def test_checks_with_weak_hand_no_call(self):
        strategy = SimpleStrategy(aggressiveness=0.0)
        action, amt = strategy.decide(state(min_call=0), make_view(hole_cards=WEAK_HAND))
        assert action == PlayerAction.CHECK
        assert amt == 0

    def test_folds_weak_hand_large_bet(self):
        strategy = SimpleStrategy(aggressiveness=0.1)
        # Large call relative to pot → pot odds unfavourable for weak hand
        gs = state(min_call=900, pot_size=100)
        action, _ = strategy.decide(gs, make_view(chips=1000, hole_cards=WEAK_HAND))
        assert action == PlayerAction.FOLD

    def test_calls_positive_ev(self):
        # Strong hand (AA), small call, big pot → positive EV → call or raise
        strategy = SimpleStrategy(aggressiveness=0.0)  # never raises
        gs = state(min_call=10, pot_size=200)
        action, _ = strategy.decide(gs, make_view(hole_cards=STRONG_HAND))
        assert action in (PlayerAction.CALL, PlayerAction.RAISE, PlayerAction.ALL_IN)

    def test_aggressive_bot_raises_more(self):
        """Aggressive bot should raise more often than passive bot given same hand."""
        import random
        random.seed(42)
        agg_strategy  = SimpleStrategy(aggressiveness=0.95)
        pass_strategy = SimpleStrategy(aggressiveness=0.05)
        gs = state(min_call=0, pot_size=100)
        view = make_view(hole_cards=STRONG_HAND)

        agg_raises  = sum(1 for _ in range(100)
                          if agg_strategy.decide(gs, view)[0] == PlayerAction.RAISE)
        pass_raises = sum(1 for _ in range(100)
                          if pass_strategy.decide(gs, view)[0] == PlayerAction.RAISE)
        assert agg_raises > pass_raises

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
    def test_checks_medium_hand_no_bet(self):
        """Tight-passive rarely bets with medium hands."""
        import random
        random.seed(0)
        strategy = TightPassiveStrategy()
        # Medium hand — equity ~0.42 (One Pair range)
        medium_hand = [Card(Rank.JACK, Suit.CLUBS), Card(Rank.TWO, Suit.HEARTS)]
        gs = state(min_call=0, pot_size=100)
        checks = sum(1 for _ in range(50)
                     if strategy.decide(gs, make_view(hole_cards=medium_hand))[0]
                     == PlayerAction.CHECK)
        assert checks >= 40  # almost always checks with medium hand

    def test_folds_to_aggression_weak_hand(self):
        strategy = TightPassiveStrategy()
        gs = state(min_call=200, pot_size=100)
        action, _ = strategy.decide(gs, make_view(chips=1000, hole_cards=WEAK_HAND))
        assert action == PlayerAction.FOLD


# ---------------------------------------------------------------------------
# LooseAggressiveStrategy
# ---------------------------------------------------------------------------

class TestLooseAggressiveStrategy:
    def test_raises_frequently_even_medium_hand(self):
        import random
        random.seed(1)
        strategy = LooseAggressiveStrategy()
        medium_hand = [Card(Rank.NINE, Suit.SPADES), Card(Rank.EIGHT, Suit.HEARTS)]
        gs = state(min_call=0, pot_size=100)
        raises = sum(1 for _ in range(100)
                     if strategy.decide(gs, make_view(hole_cards=medium_hand))[0]
                     == PlayerAction.RAISE)
        assert raises > 30  # LAG bets with medium hands

    def test_raises_more_than_tight_passive(self):
        import random
        random.seed(5)
        lag = LooseAggressiveStrategy()
        nit = TightPassiveStrategy()
        gs = state(min_call=0, pot_size=150)
        view = make_view(hole_cards=STRONG_HAND)
        lag_raises = sum(1 for _ in range(50)
                         if lag.decide(gs, view)[0] == PlayerAction.RAISE)
        nit_raises = sum(1 for _ in range(50)
                         if nit.decide(gs, view)[0] == PlayerAction.RAISE)
        assert lag_raises >= nit_raises


# ---------------------------------------------------------------------------
# CallingStationStrategy
# ---------------------------------------------------------------------------

class TestCallingStationStrategy:
    def test_calls_frequently_medium_hand(self):
        import random
        random.seed(2)
        strategy = CallingStationStrategy()
        medium_hand = [Card(Rank.SEVEN, Suit.CLUBS), Card(Rank.EIGHT, Suit.SPADES)]
        gs = state(min_call=50, pot_size=200)
        calls = sum(1 for _ in range(100)
                    if strategy.decide(gs, make_view(chips=1000, hole_cards=medium_hand))[0]
                    in (PlayerAction.CALL, PlayerAction.ALL_IN))
        assert calls >= 60  # calling station calls most of the time

    def test_rarely_raises(self):
        import random
        random.seed(3)
        strategy = CallingStationStrategy()
        gs = state(min_call=0, pot_size=200)
        raises = sum(1 for _ in range(100)
                     if strategy.decide(gs, make_view(hole_cards=STRONG_HAND))[0]
                     == PlayerAction.RAISE)
        assert raises <= 40  # calling station rarely raises

    def test_folds_only_trash(self):
        """Even with a bad hand, calling station mostly calls."""
        import random
        random.seed(4)
        strategy = CallingStationStrategy()
        gs = state(min_call=10, pot_size=500)  # great pot odds
        folds = sum(1 for _ in range(100)
                    if strategy.decide(gs, make_view(chips=1000, hole_cards=WEAK_HAND))[0]
                    == PlayerAction.FOLD)
        assert folds <= 20  # rarely folds when pot odds are good


# ---------------------------------------------------------------------------
# Cross-strategy consistency
# ---------------------------------------------------------------------------

class TestCrossStrategy:
    def test_all_strategies_return_valid_action(self):
        """Every strategy must return a valid (action, int) pair in all situations."""
        strategies = [
            SimpleStrategy(),
            TightPassiveStrategy(),
            LooseAggressiveStrategy(),
            CallingStationStrategy(),
        ]
        game_states = [
            state(min_call=0),
            state(min_call=50, pot_size=200),
            state(min_call=1000, pot_size=50),  # call bigger than pot
        ]
        views = [
            make_view(chips=1000, hole_cards=STRONG_HAND),
            make_view(chips=50,   hole_cards=WEAK_HAND),
        ]
        valid_actions = set(PlayerAction)

        for s in strategies:
            for gs in game_states:
                for v in views:
                    action, amt = s.decide(gs, v)
                    assert action in valid_actions, f"{s.__class__.__name__} returned invalid action"
                    assert isinstance(amt, int), f"{s.__class__.__name__} returned non-int amount"
                    assert amt >= 0

    def test_no_strategy_bets_more_than_chips(self):
        """No strategy should request more chips than the player has."""
        strategies = [
            SimpleStrategy(aggressiveness=1.0),
            LooseAggressiveStrategy(),
        ]
        view = make_view(chips=100)
        gs = state(min_call=0, pot_size=10000)

        for s in strategies:
            _, amt = s.decide(gs, view)
            assert amt <= 100, f"{s.__class__.__name__} bet more than chips"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
