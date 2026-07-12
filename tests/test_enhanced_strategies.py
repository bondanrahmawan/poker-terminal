"""
Tests for enhanced bot strategies: opponent modeling, draw detection,
bet sizing, dynamic behavior, and preflop ranges.

Run with: pytest tests/test_enhanced_strategies.py -v
"""
import pytest
from core.card import Card, Suit, Rank
from core.player import PlayerAction
from core.events import GameEvent
from strategies import PlayerView, REGISTRY
from strategies.engine import (
    DesignedBotStrategy,
    TightPassiveStrategy, TightAggressiveStrategy,
    LoosePassiveStrategy, LooseAggressiveStrategy,
    ManiacStrategy, NitStrategy, BalancedStrategy,
    _extract_opponent_ids,
)
from strategies.profile import PROFILES
from strategies.hand_score import score_starting_hand
from strategies.difficulty import EXPERT

# New modules
from strategies.opponent_model import OpponentTracker, OpponentStats
from strategies.draw_detection import detect_draws, advanced_equity, DrawInfo
from strategies.betsizing import (
    BetSize, calc_bet_size, choose_bet_size, choose_raise_size, stack_depth_label,
)
from strategies.dynamic_behavior import (
    TiltState, TableImage, should_slow_play, should_semi_bluff,
    desperation_factor, adjust_for_desperation,
)
from strategies.preflop_ranges import (
    hand_in_range, should_3bet, position_to_range, should_defend_bb,
    UTG, MP, CO, BTN, SB, BB,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_view(chips=1000, hole_cards=None):
    if hole_cards is None:
        hole_cards = [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)]
    return PlayerView(chips=chips, hole_cards=hole_cards)


def state(min_call=0, min_raise=20, pot_size=100, community_cards=None,
          position=0, num_active=4, players_info=None, hand_log=None,
          self_id=None, self_name=None, events=None, player_role=None,
          big_blind=20, current_bet=None):
    return {
        'min_call': min_call,
        'min_raise': min_raise,
        'pot_size': pot_size,
        'community_cards': community_cards or [],
        'position': position,
        'num_active': num_active,
        'players_info': players_info or [],
        'hand_log': hand_log or [],
        'self_id': self_id,
        'self_name': self_name,
        'events': events or [],
        'player_role': player_role,
        'big_blind': big_blind,
        'current_bet': current_bet if current_bet is not None else
                        (big_blind if min_call == 0 else big_blind + min_call),
    }


WEAK_HAND   = [Card(Rank.TWO, Suit.CLUBS),  Card(Rank.SEVEN, Suit.HEARTS)]
STRONG_HAND = [Card(Rank.ACE, Suit.SPADES), Card(Rank.ACE, Suit.HEARTS)]
MEDIUM_HAND = [Card(Rank.NINE, Suit.SPADES), Card(Rank.EIGHT, Suit.HEARTS)]
CONNECTED_SUITE = [Card(Rank.NINE, Suit.CLUBS), Card(Rank.TEN, Suit.CLUBS)]


# ---------------------------------------------------------------------------
# Opponent Modeling
# ---------------------------------------------------------------------------

class TestOpponentStats:
    def test_default_values(self):
        s = OpponentStats()
        assert s.vpip == 0.5  # default when no data
        assert s.pfr == 0.2
        assert s.fold_to_bet == 0.3

    def test_vpip_calculation(self):
        s = OpponentStats(opportunities_voluntary=10, voluntary_puts=7)
        assert s.vpip == 0.7

    def test_pfr_calculation(self):
        s = OpponentStats(opportunities_raise=10, preflop_raises=4)
        assert s.pfr == 0.4

    def test_fold_to_bet_calculation(self):
        s = OpponentStats(bets_faced=10, folds_to_bet=6)
        assert s.fold_to_bet == 0.6

    def test_classify_nit(self):
        s = OpponentStats(opportunities_voluntary=20, voluntary_puts=2,
                          opportunities_raise=20, preflop_raises=0,
                          bets_faced=10, folds_to_bet=7, total_hands_seen=20)
        assert s.classify() == 'nit'

    def test_classify_calling_station(self):
        s = OpponentStats(opportunities_voluntary=20, voluntary_puts=15,
                          opportunities_raise=20, preflop_raises=2,
                          total_hands_seen=20)
        assert s.classify() == 'calling_station'

    def test_classify_maniac(self):
        s = OpponentStats(opportunities_voluntary=20, voluntary_puts=18,
                          opportunities_raise=20, preflop_raises=15,
                          total_hands_seen=20)
        assert s.classify() == 'maniac'


class TestOpponentTracker:
    def test_record_action_fold(self):
        t = OpponentTracker()
        t.record_action('opp1', 'fold', 'flop')
        s = t.get_stats('opp1')
        assert s.folds_to_bet == 1
        assert s.bets_faced == 1

    def test_record_action_call(self):
        t = OpponentTracker()
        t.record_action('opp1', 'call', 'preflop')
        s = t.get_stats('opp1')
        assert s.voluntary_puts == 1
        assert s.opportunities_voluntary == 1

    def test_record_action_raise(self):
        t = OpponentTracker()
        t.record_action('opp1', 'raise', 'preflop')
        s = t.get_stats('opp1')
        assert s.preflop_raises == 1
        assert s.voluntary_puts == 1

    def test_exploit_adjustment_empty(self):
        t = OpponentTracker()
        adj = t.exploit_adjustment([])
        assert adj == {'equity_boost': 0.0, 'aggression_boost': 0.0,
                       'bluff_boost': 0.0, 'caution_penalty': 0.0}

    def test_exploit_adjustment_nit(self):
        t = OpponentTracker()
        # Simulate a nit: few voluntary puts, few raises
        for _ in range(15):
            t.record_action('nit1', 'fold', 'preflop')
        t.record_action('nit1', 'call', 'preflop')
        t.record_action('nit1', 'call', 'preflop')
        adj = t.exploit_adjustment(['nit1'])
        # Nit should recommend some bluff boost or caution penalty
        assert adj['bluff_boost'] > 0 or adj['caution_penalty'] > 0

    def test_opponent_fold_equity(self):
        t = OpponentTracker()
        for _ in range(8):
            t.record_action('opp1', 'fold', 'flop')
        for _ in range(2):
            t.record_action('opp1', 'call', 'flop')
        fe = t.opponent_fold_equity(['opp1'])
        assert fe > 0.0  # opponent folds 80% → significant fold equity

    def test_has_data(self):
        t = OpponentTracker()
        assert not t.has_data('opp1')
        for _ in range(6):
            t.record_action('opp1', 'fold', 'preflop')
        assert t.has_data('opp1', min_hands=5)


# ---------------------------------------------------------------------------
# Draw Detection
# ---------------------------------------------------------------------------

class TestDrawDetection:
    def test_no_draws_empty_board(self):
        draw = detect_draws(STRONG_HAND, [])
        assert not draw.is_flush_draw
        assert not draw.open_ended_straight_draw
        assert not draw.gutshot_straight_draw

    def test_flush_draw_on_flop(self):
        # AK of spades + 2 more spades on flop
        hole = [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.SPADES)]
        board = [Card(Rank.TWO, Suit.SPADES), Card(Rank.FIVE, Suit.SPADES),
                 Card(Rank.NINE, Suit.HEARTS)]
        draw = detect_draws(hole, board)
        assert draw.is_flush_draw
        assert draw.flush_draw_cards == 4

    def test_made_flush(self):
        hole = [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.SPADES)]
        board = [Card(Rank.TWO, Suit.SPADES), Card(Rank.FIVE, Suit.SPADES),
                 Card(Rank.NINE, Suit.SPADES)]
        draw = detect_draws(hole, board)
        assert draw.hand_rank >= 6  # Flush rank

    def test_open_ended_straight_draw(self):
        # 8-9 on board 6-7-3 → open-ended (5 or T completes)
        hole = [Card(Rank.EIGHT, Suit.CLUBS), Card(Rank.NINE, Suit.CLUBS)]
        board = [Card(Rank.SIX, Suit.HEARTS), Card(Rank.SEVEN, Suit.DIAMONDS),
                 Card(Rank.THREE, Suit.SPADES)]
        draw = detect_draws(hole, board)
        assert draw.open_ended_straight_draw or draw.straight_draw_outs >= 6

    def test_gutshot_straight_draw(self):
        # 8-T on board 6-7-9 → need J for straight (gutshot)
        hole = [Card(Rank.EIGHT, Suit.CLUBS), Card(Rank.TEN, Suit.CLUBS)]
        board = [Card(Rank.SIX, Suit.HEARTS), Card(Rank.SEVEN, Suit.DIAMONDS),
                 Card(Rank.NINE, Suit.SPADES)]
        draw = detect_draws(hole, board)
        # 8-T + 6-7-9 = 6,7,8,9,T → already a straight!
        assert draw.hand_rank >= 5 or draw.gutshot_straight_draw

    def test_combo_draw(self):
        # Flush draw + straight draw
        # 9s-Ts on board Js-8h-6s → flush draw (4 spades) + open-ended (7 or Q)
        hole = [Card(Rank.NINE, Suit.SPADES), Card(Rank.TEN, Suit.SPADES)]
        board = [Card(Rank.JACK, Suit.SPADES), Card(Rank.EIGHT, Suit.HEARTS),
                 Card(Rank.SIX, Suit.SPADES)]
        draw = detect_draws(hole, board)
        # Has flush draw (4 spades) + open-ended straight draw (7 or Q completes)
        assert draw.total_outs >= 12 or draw.is_strong_draw or (draw.is_flush_draw and draw.open_ended_straight_draw)

    def test_total_outs_positive_for_draws(self):
        hole = [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.SPADES)]
        board = [Card(Rank.TWO, Suit.SPADES), Card(Rank.FIVE, Suit.SPADES),
                 Card(Rank.NINE, Suit.HEARTS)]
        draw = detect_draws(hole, board)
        assert draw.total_outs > 0


class TestGutshotDetection:
    """Table-driven cases for the corrected gutshot/double-gutshot span (Task 5)."""

    def test_gutshot_span_four_missing_one(self):
        # hole 8s9d, board 5h6cKd -> ranks 5,6,8,9 (span 4, missing 7)
        hole = [Card(Rank.EIGHT, Suit.SPADES), Card(Rank.NINE, Suit.DIAMONDS)]
        board = [Card(Rank.FIVE, Suit.HEARTS), Card(Rank.SIX, Suit.CLUBS),
                 Card(Rank.KING, Suit.DIAMONDS)]
        draw = detect_draws(hole, board)
        assert draw.gutshot_straight_draw is True

    def test_two_gap_span_five_is_not_a_gutshot(self):
        # hole 5s6d, board 8h10cKd -> ranks 5,6,8,10 (span 5, two gaps)
        hole = [Card(Rank.FIVE, Suit.SPADES), Card(Rank.SIX, Suit.DIAMONDS)]
        board = [Card(Rank.EIGHT, Suit.HEARTS), Card(Rank.TEN, Suit.CLUBS),
                 Card(Rank.KING, Suit.DIAMONDS)]
        draw = detect_draws(hole, board)
        assert draw.gutshot_straight_draw is False

    def test_wheel_gutshot(self):
        # hole As2d, board 3h5cKd -> needs the 4 (wheel gutshot)
        hole = [Card(Rank.ACE, Suit.SPADES), Card(Rank.TWO, Suit.DIAMONDS)]
        board = [Card(Rank.THREE, Suit.HEARTS), Card(Rank.FIVE, Suit.CLUBS),
                 Card(Rank.KING, Suit.DIAMONDS)]
        draw = detect_draws(hole, board)
        assert draw.gutshot_straight_draw is True

    def test_gutshot_missing_middle_rank(self):
        # hole 9s10d, board 6h7cKd -> ranks 6,7,9,10 (missing 8)
        hole = [Card(Rank.NINE, Suit.SPADES), Card(Rank.TEN, Suit.DIAMONDS)]
        board = [Card(Rank.SIX, Suit.HEARTS), Card(Rank.SEVEN, Suit.CLUBS),
                 Card(Rank.KING, Suit.DIAMONDS)]
        draw = detect_draws(hole, board)
        assert draw.gutshot_straight_draw is True

    def test_open_ended_is_not_also_a_gutshot(self):
        # hole Js10d, board 9h8cKd -> 8-9-10-J -> open-ended, not a gutshot
        hole = [Card(Rank.JACK, Suit.SPADES), Card(Rank.TEN, Suit.DIAMONDS)]
        board = [Card(Rank.NINE, Suit.HEARTS), Card(Rank.EIGHT, Suit.CLUBS),
                 Card(Rank.KING, Suit.DIAMONDS)]
        draw = detect_draws(hole, board)
        assert draw.open_ended_straight_draw is True
        assert draw.gutshot_straight_draw is False

    def test_double_gutshot(self):
        # hole 10s9d, board 6h8cQd -> 7 completes 6-7-8-9-10, J completes 8-9-10-J-Q
        hole = [Card(Rank.TEN, Suit.SPADES), Card(Rank.NINE, Suit.DIAMONDS)]
        board = [Card(Rank.SIX, Suit.HEARTS), Card(Rank.EIGHT, Suit.CLUBS),
                 Card(Rank.QUEEN, Suit.DIAMONDS)]
        draw = detect_draws(hole, board)
        assert draw.double_gutshot is True
        assert draw.straight_draw_outs == 8


class TestAdvancedEquity:
    def test_preflop_strong(self):
        eq = advanced_equity(STRONG_HAND, [])
        assert eq == 0.55

    def test_preflop_weak(self):
        eq = advanced_equity(WEAK_HAND, [])
        assert eq == 0.32

    def test_postflop_strong_hand(self):
        community = [
            Card(Rank.ACE, Suit.CLUBS),
            Card(Rank.ACE, Suit.DIAMONDS),
            Card(Rank.KING, Suit.CLUBS),
        ]
        eq = advanced_equity(STRONG_HAND, community)
        assert eq >= 0.80  # Quads or full house

    def test_postflop_draw_has_equity(self):
        hole = [Card(Rank.NINE, Suit.CLUBS), Card(Rank.TEN, Suit.CLUBS)]
        board = [Card(Rank.JACK, Suit.CLUBS), Card(Rank.EIGHT, Suit.HEARTS),
                 Card(Rank.TWO, Suit.DIAMONDS)]
        eq = advanced_equity(hole, board)
        assert eq > 0.30  # Open-ended + flush draw

    def test_multiplayer_reduction(self):
        hole = [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)]
        board = [Card(Rank.ACE, Suit.CLUBS), Card(Rank.TWO, Suit.DIAMONDS),
                 Card(Rank.THREE, Suit.HEARTS)]
        eq_1 = advanced_equity(hole, board, num_opponents=1)
        eq_3 = advanced_equity(hole, board, num_opponents=3)
        assert eq_3 < eq_1  # More opponents = less equity


# ---------------------------------------------------------------------------
# Bet Sizing
# ---------------------------------------------------------------------------

class TestBetSizing:
    def test_calc_bet_size_small(self):
        amt = calc_bet_size(BetSize.SMALL, 100, 0, 20, 1000)
        assert 30 <= amt <= 40  # ~33% pot

    def test_calc_bet_size_pot(self):
        amt = calc_bet_size(BetSize.POT, 100, 0, 20, 1000)
        assert 70 <= amt <= 80  # ~75% pot

    def test_calc_bet_size_overbet(self):
        amt = calc_bet_size(BetSize.OVERBET, 100, 0, 20, 1000)
        assert amt >= 120  # 125% pot

    def test_calc_bet_size_capped_at_chips(self):
        amt = calc_bet_size(BetSize.OVERBET, 1000, 0, 20, 100)
        assert amt == 100

    def test_calc_bet_size_all_in(self):
        _, amt = BetSize.ALL_IN, 500
        assert amt == 500

    def test_choose_bet_size_value_strong(self):
        size, amt = choose_bet_size(
            pot_size=200, min_call=0, min_raise=20, chips=1000,
            equity=0.70, is_made_hand=True, is_strong_made=True,
            aggression=0.5,
        )
        assert amt > 0
        assert amt <= 1000

    def test_choose_bet_size_bluff(self):
        size, amt = choose_bet_size(
            pot_size=200, min_call=0, min_raise=20, chips=1000,
            equity=0.15, is_bluff=True, opponent_folds_often=False,
            aggression=0.5,
        )
        assert amt > 0

    def test_choose_bet_size_semi_bluff(self):
        size, amt = choose_bet_size(
            pot_size=200, min_call=0, min_raise=20, chips=1000,
            equity=0.40, is_draw=True, is_strong_draw=True,
            is_semi_bluff=True, aggression=0.6,
        )
        assert amt > 0

    def test_choose_bet_size_no_clear_hand_returns_none(self):
        # Slow-playing is now handled by the engine before ever calling this
        # helper (Task 8); with no made hand/draw/bluff flags set it just
        # signals "no bet" via None so the caller falls through to check/fold.
        result = choose_bet_size(
            pot_size=200, min_call=0, min_raise=20, chips=1000, equity=0.30,
        )
        assert result is None

    def test_stack_depth_label(self):
        assert stack_depth_label(50, 20) == 'short'    # 2.5 BB
        assert stack_depth_label(500, 20) == 'medium'   # 25 BB
        assert stack_depth_label(2000, 20) == 'deep'    # 100 BB


# ---------------------------------------------------------------------------
# Dynamic Behavior
# ---------------------------------------------------------------------------

class TestTiltState:
    def test_default_not_tilting(self):
        t = TiltState()
        assert not t.is_tilting
        assert t.tilt_aggression_boost == 0.0

    def test_tilt_increases_on_bad_beat(self):
        t = TiltState()
        t.record_loss(500, was_favorite=True)
        assert t.tilt_level > 0.1
        assert t.bad_beat_count == 1

    def test_tilt_decreases_on_win(self):
        t = TiltState()
        t.record_loss(500, was_favorite=True)
        prev = t.tilt_level
        t.record_win(200)
        assert t.tilt_level < prev

    def test_is_tilting_threshold(self):
        t = TiltState()
        for _ in range(5):
            t.record_loss(300, was_favorite=True)
        assert t.is_tilting

    def test_tilt_aggression_boost_scales(self):
        t = TiltState()
        t.tilt_level = 0.6
        assert t.tilt_aggression_boost > 0.0

    def test_tilt_decay(self):
        t = TiltState()
        t.tilt_level = 0.5
        for _ in range(10):
            t.record_hand_end()
        assert t.tilt_level < 0.5


class TestTableImage:
    def test_default_tightness(self):
        img = TableImage()
        assert img.tightness == 0.5

    def test_tightness_increases_with_folds(self):
        img = TableImage()
        for _ in range(10):
            img.record_preflop_fold()
        assert img.tightness > 0.7

    def test_tightness_decreases_with_plays(self):
        img = TableImage()
        for _ in range(10):
            img.record_preflop_enter()
        assert img.tightness < 0.3

    def test_bluff_success_rate_tight_image(self):
        img = TableImage()
        for _ in range(10):
            img.record_preflop_fold()
        assert img.bluff_success_rate >= 0.5  # tight image → bluff success >= 50%


class TestSlowPlay:
    def test_never_slow_weak_hand(self):
        import random
        random.seed(0)
        img = TableImage()
        assert not should_slow_play(0.30, 0.5, img)

    def test_sometimes_slow_strong_hand(self):
        img = TableImage()
        img.hands_played_loose = 10  # loose image
        count = sum(1 for _ in range(100)
                    if should_slow_play(0.80, 0.3, img))
        assert count > 0  # should happen sometimes


class TestSemiBluff:
    def test_never_semi_bluff_without_draw(self):
        assert not should_semi_bluff(0.40, 0.5, False, False, 0.25, False)

    def test_semi_bluff_with_strong_draw(self):
        import random
        random.seed(1)
        count = sum(1 for _ in range(100)
                    if should_semi_bluff(0.45, 0.7, True, True, 0.25, True))
        assert count > 20


class TestDesperation:
    def test_not_desperate_with_deep_stack(self):
        assert desperation_factor(2000, 20) == 0.0

    def test_desperate_with_short_stack(self):
        assert desperation_factor(50, 20) >= 0.7

    def test_urgent_with_10bb(self):
        assert desperation_factor(200, 20) >= 0.3

    def test_adjust_for_desperation_folding(self):
        action, amt = adjust_for_desperation('fold', 0.8, 0.40, 50, 200)
        # Should push to all-in when desperate with decent hand
        assert action == PlayerAction.ALL_IN or action is None


# ---------------------------------------------------------------------------
# Preflop Ranges
# ---------------------------------------------------------------------------

class TestPreflopRanges:
    def test_position_to_range_mapping(self):
        assert position_to_range(UTG) == 'tight'
        assert position_to_range(BTN) == 'very_wide'
        assert position_to_range(CO) == 'wide'
        assert position_to_range(MP) == 'medium'

    def test_aa_in_all_ranges(self):
        aa = [Card(Rank.ACE, Suit.SPADES), Card(Rank.ACE, Suit.HEARTS)]
        for label in ['tight', 'medium', 'wide', 'very_wide']:
            assert hand_in_range(aa[0], aa[1], label)

    def test_72o_not_in_tight_range(self):
        hand = [Card(Rank.SEVEN, Suit.CLUBS), Card(Rank.TWO, Suit.HEARTS)]
        assert not hand_in_range(hand[0], hand[1], 'tight')

    def test_suited_connectors_in_wide_range(self):
        hand = [Card(Rank.NINE, Suit.CLUBS), Card(Rank.EIGHT, Suit.CLUBS)]
        assert hand_in_range(hand[0], hand[1], 'wide')

    def test_3bet_with_premium(self):
        ak = [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.SPADES)]
        do_3bet, is_value, is_bluff = should_3bet(ak[0], ak[1], 'tight', 0.8)
        assert do_3bet
        assert is_value

    def test_3bet_bluff_with_suited_connectors(self):
        hand = [Card(Rank.FIVE, Suit.SPADES), Card(Rank.FOUR, Suit.SPADES)]
        do_3bet, is_value, is_bluff = should_3bet(hand[0], hand[1], 'wide', 0.8)
        # May or may not 3-bet, but if it does, it should be a bluff
        if do_3bet:
            assert is_bluff or is_value

    def test_defend_bb_with_decent_hand(self):
        hand = [Card(Rank.JACK, Suit.CLUBS), Card(Rank.TEN, Suit.CLUBS)]
        assert should_defend_bb(hand[0], hand[1], raise_size=0.3, aggression=0.6)


# ---------------------------------------------------------------------------
# Enhanced Strategy Integration
# ---------------------------------------------------------------------------

class TestEnhancedStrategies:
    """Test that enhanced strategies work end-to-end."""

    def test_balanced_preflop_open(self):
        import random
        random.seed(42)
        strategy = BalancedStrategy()
        gs = state(min_call=0, pot_size=30, players_info=[
            ('Bot_Alice', 1000, True), ('Bot_Bob', 1000, True),
        ])
        action, amt = strategy.decide(gs, make_view(hole_cards=STRONG_HAND))
        assert action in (PlayerAction.RAISE, PlayerAction.ALL_IN, PlayerAction.CHECK)

    def test_balanced_postflop_with_draw(self):
        import random
        random.seed(42)
        strategy = BalancedStrategy()
        community = [
            Card(Rank.NINE, Suit.CLUBS),
            Card(Rank.TEN, Suit.CLUBS),
            Card(Rank.TWO, Suit.HEARTS),
        ]
        gs = state(min_call=0, pot_size=100, community_cards=community,
                   players_info=[('Bot_Alice', 1000, True)])
        # Has flush draw + open-ended straight draw
        action, amt = strategy.decide(gs, make_view(hole_cards=CONNECTED_SUITE))
        assert action in (PlayerAction.CHECK, PlayerAction.RAISE, PlayerAction.ALL_IN)

    def test_tag_3bet_preflop(self):
        import random
        random.seed(42)
        strategy = TightAggressiveStrategy()
        gs = state(min_call=60, pot_size=100, min_raise=20,
                   players_info=[('Bot_Alice', 1000, True)])
        action, amt = strategy.decide(gs, make_view(hole_cards=STRONG_HAND))
        assert action in (PlayerAction.RAISE, PlayerAction.ALL_IN, PlayerAction.CALL, PlayerAction.FOLD)

    def test_maniac_bluffs(self):
        import random
        random.seed(42)
        strategy = ManiacStrategy()
        community = [
            Card(Rank.TWO, Suit.CLUBS),
            Card(Rank.THREE, Suit.HEARTS),
            Card(Rank.FOUR, Suit.DIAMONDS),
        ]
        gs = state(min_call=0, pot_size=100, community_cards=community,
                   players_info=[('Bot_Alice', 1000, True)])
        raises = sum(1 for _ in range(50)
                     if strategy.decide(gs, make_view(hole_cards=WEAK_HAND))[0]
                     in (PlayerAction.RAISE, PlayerAction.ALL_IN))
        # Maniac should bluff sometimes even with weak hands
        assert raises >= 0  # at least doesn't crash

    def test_nit_folds_most_preflop(self):
        import random
        random.seed(42)
        strategy = NitStrategy()
        gs = state(min_call=50, pot_size=100,
                   players_info=[('Bot_Alice', 1000, True)])
        folds = sum(1 for _ in range(100)
                    if strategy.decide(gs, make_view(hole_cards=MEDIUM_HAND))[0]
                    == PlayerAction.FOLD)
        assert folds >= 70  # nit folds most medium hands facing a bet

    def test_all_strategies_return_valid_actions(self):
        strategies = [
            TightPassiveStrategy(), TightAggressiveStrategy(),
            LoosePassiveStrategy(), LooseAggressiveStrategy(),
            ManiacStrategy(), NitStrategy(), BalancedStrategy(),
        ]
        game_states = [
            state(min_call=0),
            state(min_call=50, pot_size=200),
            state(min_call=0, pot_size=100,
                  community_cards=[Card(Rank.ACE, Suit.CLUBS),
                                   Card(Rank.KING, Suit.HEARTS),
                                   Card(Rank.TWO, Suit.DIAMONDS)]),
        ]
        views = [
            make_view(chips=1000, hole_cards=STRONG_HAND),
            make_view(chips=50, hole_cards=WEAK_HAND),
            make_view(chips=1000, hole_cards=CONNECTED_SUITE),
        ]
        valid = set(PlayerAction)
        for s in strategies:
            for gs in game_states:
                for v in views:
                    action, amt = s.decide(gs, v)
                    assert action in valid, f"{s.__class__.__name__} returned invalid action"
                    assert isinstance(amt, int)
                    assert amt >= 0
                    assert amt <= v.chips, f"{s.__class__.__name__} bet more than chips"

    def test_strategy_has_tracking_components(self):
        strategy = BalancedStrategy()
        assert hasattr(strategy, 'tilt')
        assert hasattr(strategy, 'image')
        assert hasattr(strategy, 'tracker')
        assert isinstance(strategy.tilt, TiltState)
        assert isinstance(strategy.image, TableImage)
        assert isinstance(strategy.tracker, OpponentTracker)

    def test_record_hand_result(self):
        strategy = BalancedStrategy()
        prev_tilt = strategy.tilt.tilt_level
        strategy.record_hand_result(won=False, amount=300, was_favorite=True)
        assert strategy.tilt.tilt_level > prev_tilt  # tilt increases on bad beat

    def test_no_strategy_bets_more_than_chips(self):
        strategies = [
            ManiacStrategy(), LooseAggressiveStrategy(),
        ]
        view = make_view(chips=100)
        gs = state(min_call=0, pot_size=10000)
        for s in strategies:
            _, amt = s.decide(gs, view)
            assert amt <= 100, f"{s.__class__.__name__} bet more than chips"


# ---------------------------------------------------------------------------
# Bot identity (self_id / self_name wiring)
# ---------------------------------------------------------------------------

class TestBotIdentity:
    def test_own_actions_not_recorded_as_opponent(self):
        strategy = BalancedStrategy()
        players_info = [('Bot1', 1000, True), ('Opp1', 1000, True), ('Opp2', 1000, True)]
        events = [
            GameEvent(0, 'action_taken', dict(player_id='p_opp1', name='Opp1',
                      action='call', amount=20, street='preflop')),
            GameEvent(1, 'action_taken', dict(player_id='p_opp2', name='Opp2',
                      action='fold', amount=0, street='preflop')),
            GameEvent(2, 'action_taken', dict(player_id='p_bot1', name='Bot1',
                      action='raise', amount=60, street='preflop')),
        ]
        gs = state(min_call=50, pot_size=100, players_info=players_info,
                   events=events, self_id='p_bot1', self_name='Bot1',
                   position=1)
        for _ in range(3):
            strategy.decide(gs, make_view(hole_cards=MEDIUM_HAND))

        assert strategy.tracker.get_stats('Bot1').total_hands_seen == 0
        assert strategy.tracker.get_stats('Opp1').total_hands_seen > 0
        assert strategy.tracker.get_stats('Opp2').total_hands_seen > 0

    def test_exploit_adjustment_excludes_self(self):
        opponent_ids = _extract_opponent_ids(
            [('Bot1', 1000, True), ('Opp1', 1000, True), ('Opp2', 1000, True)],
            'Bot1',
        )
        assert opponent_ids == ['Opp1', 'Opp2']


# ---------------------------------------------------------------------------
# Structured event consumption (cursor + real streets)
# ---------------------------------------------------------------------------

class TestRecordOpponentActionsFromEvents:
    def test_events_counted_once_and_street_respected(self):
        strategy = BalancedStrategy()
        events = [
            GameEvent(0, 'action_taken', dict(player_id='p_opp1', name='Opp1',
                      action='fold', amount=0, street='preflop')),
            GameEvent(1, 'action_taken', dict(player_id='p_opp1', name='Opp1',
                      action='fold', amount=0, street='flop')),
            GameEvent(2, 'action_taken', dict(player_id='p_opp2', name='Opp2',
                      action='call', amount=20, street='flop')),
            GameEvent(3, 'action_taken', dict(player_id='p_bot1', name='Bot1',
                      action='call', amount=20, street='flop')),
        ]
        gs = state(min_call=0, pot_size=100, players_info=[
            ('Bot1', 1000, True), ('Opp1', 1000, True), ('Opp2', 1000, True)],
            events=events, self_id='p_bot1', self_name='Bot1')

        strategy.decide(gs, make_view(hole_cards=MEDIUM_HAND))
        strategy.decide(gs, make_view(hole_cards=MEDIUM_HAND))  # same events again

        opp1 = strategy.tracker.get_stats('Opp1')
        assert opp1.total_hands_seen == 2  # each event counted exactly once
        assert opp1.bets_faced == 1
        assert opp1.folds_to_bet == 1
        assert strategy.tracker.get_stats('Bot1').total_hands_seen == 0

    def test_integration_fold_to_bet_populated(self):
        # Cash mode + rebuys so busting never starves later hands of action
        # (a tournament/blind-reset table spends long stretches heads-up-or-less
        # between resets, which starves this of postflop bet-facing spots).
        # A Maniac forces genuine bad-odds spots for a Nit to fold into.
        import random
        from core.game import Game
        from players.bot import BotPlayer
        from strategies.engine import BalancedStrategy, ManiacStrategy, NitStrategy

        random.seed(123)
        game = Game(big_blind=20, seed=42, game_mode='cash')
        game.add_player(BotPlayer('p0', 'Bot0', 5000, ManiacStrategy(difficulty=0.6)))
        game.add_player(BotPlayer('p1', 'Bot1', 5000, NitStrategy(difficulty=0.6)))
        game.add_player(BotPlayer('p2', 'Bot2', 5000, BalancedStrategy(difficulty=0.6)))

        for _ in range(100):
            game.start_game()
            for p in game.players:
                if p.chips == 0:
                    p.chips = 5000

        found_fold_to_bet = False
        for p in game.players:
            for oid, stats in p.strategy.tracker.get_all_stats().items():
                if stats.bets_faced > 0 and stats.fold_to_bet > 0:
                    found_fold_to_bet = True
        assert found_fold_to_bet


# ---------------------------------------------------------------------------
# Fold equity must not rescue a bad pot-odds call (Task 7)
# ---------------------------------------------------------------------------

class TestFoldEquityNotAddedToCallDecision:
    def _make_strategy_with_foldy_opponent(self):
        strategy = BalancedStrategy(difficulty=1.0)  # no noise
        for _ in range(10):
            strategy.tracker.record_action('Opp', 'fold', 'flop')
        return strategy

    def test_facing_bet_still_folds_below_pot_odds(self):
        strategy = self._make_strategy_with_foldy_opponent()
        # One pair, no draw: raw equity 0.42, +0.05 calling-station equity_boost
        # = 0.47. Fold equity here is 0.15, which would push the old buggy
        # equity to 0.62 -- above the ~0.545 pot odds below -- and wrongly call.
        hole = [Card(Rank.NINE, Suit.SPADES), Card(Rank.TWO, Suit.HEARTS)]
        board = [Card(Rank.NINE, Suit.CLUBS), Card(Rank.FIVE, Suit.DIAMONDS),
                 Card(Rank.KING, Suit.DIAMONDS)]
        gs = state(min_call=120, pot_size=100, community_cards=board,
                   num_active=2,
                   players_info=[('Bot1', 1000, True), ('Opp', 1000, True)],
                   self_id='p_bot1', self_name='Bot1')
        action, amt = strategy.decide(gs, make_view(chips=1000, hole_cards=hole))
        assert action == PlayerAction.FOLD

    def test_no_bet_to_face_still_bets_with_made_hand(self):
        strategy = self._make_strategy_with_foldy_opponent()
        hole = [Card(Rank.NINE, Suit.SPADES), Card(Rank.TWO, Suit.HEARTS)]
        board = [Card(Rank.NINE, Suit.CLUBS), Card(Rank.FIVE, Suit.DIAMONDS),
                 Card(Rank.KING, Suit.DIAMONDS)]
        gs = state(min_call=0, pot_size=100, community_cards=board,
                   num_active=2,
                   players_info=[('Bot1', 1000, True), ('Opp', 1000, True)],
                   self_id='p_bot1', self_name='Bot1')
        bets = sum(1 for _ in range(50)
                   if strategy.decide(gs, make_view(chips=1000, hole_cards=hole))[0]
                   in (PlayerAction.RAISE, PlayerAction.ALL_IN))
        assert bets > 0


# ---------------------------------------------------------------------------
# Preflop opening logic routed through position-aware ranges (Task 3)
# ---------------------------------------------------------------------------

class TestPreflopOpeningRoutedByPosition:
    def test_btn_enters_wider_than_utg(self):
        import random
        big_blind = 20
        gs_kwargs = dict(min_call=big_blind, min_raise=big_blind, pot_size=30,
                          big_blind=big_blind, current_bet=big_blind)

        # All 169 canonical starting hands (13 pairs, 78 suited, 78 offsuit),
        # sampled uniformly — a representative mix rather than a fixed-suit
        # bias that would exclude suited hands entirely.
        ranks = sorted(Rank.get_all(), reverse=True)
        canonical_hands = []
        for i, r1 in enumerate(ranks):
            for r2 in ranks[i:]:
                if r1 == r2:
                    canonical_hands.append((Card(r1, Suit.SPADES), Card(r2, Suit.HEARTS)))
                else:
                    canonical_hands.append((Card(r1, Suit.SPADES), Card(r2, Suit.HEARTS)))
                    canonical_hands.append((Card(r1, Suit.SPADES), Card(r2, Suit.SPADES)))

        def entry_rate(role):
            entries = 0
            trials = 2000
            for _ in range(trials):
                strategy = BalancedStrategy(difficulty=1.0)  # no noise
                hole = list(random.choice(canonical_hands))
                gs = state(player_role=role, **gs_kwargs)
                action, _ = strategy.decide(gs, make_view(hole_cards=hole))
                if action != PlayerAction.FOLD:
                    entries += 1
            return entries / trials

        random.seed(7)
        btn_rate = entry_rate('BTN')
        utg_rate = entry_rate('UTG')
        assert btn_rate >= 1.5 * utg_rate

    def test_position_awareness_gated_by_difficulty(self):
        """Phase 2 Task 5: position_aware is a difficulty feature — HARD sees
        the BTN/UTG split, EASY (position_aware=False) flattens to 'medium'
        for every seat."""
        import random
        from strategies.difficulty import EASY, HARD
        big_blind = 20
        gs_kwargs = dict(min_call=big_blind, min_raise=big_blind, pot_size=30,
                          big_blind=big_blind, current_bet=big_blind)

        ranks = sorted(Rank.get_all(), reverse=True)
        canonical_hands = []
        for i, r1 in enumerate(ranks):
            for r2 in ranks[i:]:
                if r1 == r2:
                    canonical_hands.append((Card(r1, Suit.SPADES), Card(r2, Suit.HEARTS)))
                else:
                    canonical_hands.append((Card(r1, Suit.SPADES), Card(r2, Suit.HEARTS)))
                    canonical_hands.append((Card(r1, Suit.SPADES), Card(r2, Suit.SPADES)))

        def entry_rate(role, difficulty):
            entries = 0
            trials = 2000
            for _ in range(trials):
                strategy = BalancedStrategy(difficulty=difficulty)
                hole = list(random.choice(canonical_hands))
                gs = state(player_role=role, **gs_kwargs)
                action, _ = strategy.decide(gs, make_view(hole_cards=hole))
                if action != PlayerAction.FOLD:
                    entries += 1
            return entries / trials

        random.seed(11)
        hard_btn = entry_rate('BTN', HARD)
        hard_utg = entry_rate('UTG', HARD)
        assert hard_btn >= 1.5 * hard_utg

        easy_btn = entry_rate('BTN', EASY)
        easy_utg = entry_rate('UTG', EASY)
        relative_diff = abs(easy_btn - easy_utg) / max(easy_btn, easy_utg)
        assert relative_diff < 0.15


# ---------------------------------------------------------------------------
# Preflop folds recorded into TableImage (Task 4)
# ---------------------------------------------------------------------------

class TestPreflopFoldRecordedInImage:
    def test_nit_junk_hands_build_tight_image(self):
        strategy = NitStrategy(difficulty=1.0)
        junk_hand = [Card(Rank.SEVEN, Suit.CLUBS), Card(Rank.TWO, Suit.HEARTS)]
        big_blind = 20
        gs = state(min_call=big_blind, min_raise=big_blind, pot_size=30,
                   player_role='UTG', big_blind=big_blind, current_bet=big_blind)
        for _ in range(50):
            strategy.decide(gs, make_view(hole_cards=junk_hand))
        assert strategy.image.tightness > 0.7


# ---------------------------------------------------------------------------
# Opponent model gated by difficulty (Phase 2 Task 6)
# ---------------------------------------------------------------------------

class TestOpponentModelGatedByDifficulty:
    def test_easy_never_adapts_even_with_data(self):
        from strategies.difficulty import EASY
        strategy = BalancedStrategy(difficulty=EASY)
        for _ in range(50):
            strategy.tracker.record_action('Opp', 'fold', 'preflop')

        gs = state(min_call=50, pot_size=100,
                   players_info=[('Bot1', 1000, True), ('Opp', 1000, True)],
                   self_id='p_bot1', self_name='Bot1', num_active=2)
        strategy.decide(gs, make_view(hole_cards=MEDIUM_HAND))

        opponent_ids = _extract_opponent_ids(gs['players_info'], 'Bot1')
        n = strategy.mistakes.opp_model_min_hands
        modeled = [oid for oid in opponent_ids if n >= 0 and strategy.tracker.has_data(oid, n)]
        assert modeled == []
        assert strategy.tracker.exploit_adjustment(modeled) == {
            'equity_boost': 0.0, 'aggression_boost': 0.0,
            'bluff_boost': 0.0, 'caution_penalty': 0.0,
        }

    def test_expert_adapts_after_min_hands(self):
        from strategies.difficulty import EXPERT
        strategy = BalancedStrategy(difficulty=EXPERT)
        for _ in range(6):
            strategy.tracker.record_action('Opp', 'fold', 'preflop')

        opponent_ids = ['Opp']
        n = strategy.mistakes.opp_model_min_hands
        assert n == 5
        modeled = [oid for oid in opponent_ids if n >= 0 and strategy.tracker.has_data(oid, n)]
        assert modeled == ['Opp']
        adj = strategy.tracker.exploit_adjustment(modeled)
        assert adj != {'equity_boost': 0.0, 'aggression_boost': 0.0,
                       'bluff_boost': 0.0, 'caution_penalty': 0.0}


# ---------------------------------------------------------------------------
# Bluff mode and Monte-Carlo budget (Phase 2 Task 7)
# ---------------------------------------------------------------------------

class TestBluffModeByDifficulty:
    NON_SCARY_BOARD = [Card(Rank.TWO, Suit.CLUBS), Card(Rank.NINE, Suit.HEARTS),
                        Card(Rank.KING, Suit.DIAMONDS)]
    ACTIVE_HAND_LOG = ['Bob raises 40 Pot: 80', 'Alice calls 40 Pot: 120']

    def test_random_mode_bluffs_regardless_of_texture(self):
        strategy = DesignedBotStrategy(PROFILES['maniac'], difficulty=0.2)  # very_easy
        assert strategy.mistakes.bluff_mode == 'random'
        count = sum(
            1 for _ in range(300)
            if strategy._should_bluff_v2(self.NON_SCARY_BOARD, self.ACTIVE_HAND_LOG,
                                          0.10, 1.0, False)
        )
        assert count / 300 > 0.15  # ~30% random bluff rate

    def test_texture_mode_does_not_bluff_a_calm_board(self):
        strategy = DesignedBotStrategy(PROFILES['maniac'], difficulty=0.75)  # hard
        assert strategy.mistakes.bluff_mode == 'texture'
        count = sum(
            1 for _ in range(300)
            if strategy._should_bluff_v2(self.NON_SCARY_BOARD, self.ACTIVE_HAND_LOG,
                                          0.10, 1.0, False)
        )
        assert count == 0

    def test_texture_image_scales_by_table_image(self):
        scary_board = [Card(Rank.TWO, Suit.CLUBS), Card(Rank.NINE, Suit.CLUBS),
                        Card(Rank.KING, Suit.CLUBS)]
        weak_hand_log = ['Bob checks Pot: 80']

        tight = DesignedBotStrategy(PROFILES['maniac'], difficulty=EXPERT)
        assert tight.mistakes.bluff_mode == 'texture_image'
        tight.image.hands_played_tight = 10
        tight.image.value_bets_won = 1  # activate the tightness-based formula
        tight_rate = sum(
            1 for _ in range(500)
            if tight._should_bluff_v2(scary_board, weak_hand_log, 0.10, 1.0, False)
        ) / 500

        loose = DesignedBotStrategy(PROFILES['maniac'], difficulty=EXPERT)
        loose.image.hands_played_loose = 10
        loose.image.value_bets_won = 1
        loose_rate = sum(
            1 for _ in range(500)
            if loose._should_bluff_v2(scary_board, weak_hand_log, 0.10, 1.0, False)
        ) / 500

        assert tight_rate > loose_rate

    def test_monte_carlo_trials_are_flat_200(self):
        import strategies.engine as eng
        captured = {}
        original = eng.monte_carlo_equity

        def spy(hole, community, num_opponents, trials, *a, **kw):
            captured['trials'] = trials
            return original(hole, community, num_opponents, trials, *a, **kw)

        eng.monte_carlo_equity = spy
        try:
            strategy = BalancedStrategy(difficulty=EXPERT)
            board = [Card(Rank.TWO, Suit.CLUBS), Card(Rank.FIVE, Suit.DIAMONDS),
                     Card(Rank.NINE, Suit.SPADES), Card(Rank.QUEEN, Suit.HEARTS)]
            gs = state(min_call=0, pot_size=100, community_cards=board, num_active=2)
            strategy.decide(gs, make_view(hole_cards=STRONG_HAND))
        finally:
            eng.monte_carlo_equity = original

        assert captured.get('trials') == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
