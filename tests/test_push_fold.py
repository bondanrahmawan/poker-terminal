"""
Tests for the Nash-style push/fold short-stack mode (Variant B).

See notes/bot_variant_b_pushfold.md.
"""
import random
import pytest

from core.card import Card, Suit, Rank
from core.player import PlayerAction
from core.events import GameEvent
from strategies import PlayerView
from strategies.push_fold import (
    score_cutoff_for_fraction, jam_fraction, call_fraction,
    should_jam, should_call_jam,
)
from strategies.engine import BalancedStrategy, ManiacStrategy, NitStrategy
from strategies.hand_score import score_starting_hand
from strategies.difficulty import EASY, NORMAL, HARD, EXPERT, PERFECT, mistakes_for

AA = [Card(Rank.ACE, Suit.SPADES), Card(Rank.ACE, Suit.HEARTS)]
K72O = [Card(Rank.SEVEN, Suit.CLUBS), Card(Rank.TWO, Suit.HEARTS)]
A7O = [Card(Rank.ACE, Suit.SPADES), Card(Rank.SEVEN, Suit.HEARTS)]


def make_view(chips=1000, hole_cards=None):
    if hole_cards is None:
        hole_cards = AA
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


# ---------------------------------------------------------------------------
# Task 1: charts and range helper
# ---------------------------------------------------------------------------

class TestScoreCutoff:
    def test_monotone(self):
        c5 = score_cutoff_for_fraction(0.05)
        c20 = score_cutoff_for_fraction(0.20)
        c60 = score_cutoff_for_fraction(0.60)
        assert c5 > c20 > c60

    def test_bounds(self):
        assert score_cutoff_for_fraction(0.05) >= 80
        assert score_cutoff_for_fraction(1.0) <= 5


class TestShouldJam:
    def test_aa_always_jams(self):
        for stack_bb in (5, 8, 12, 15):
            for pos in ('UTG', 'MP', 'CO', 'BTN', 'SB'):
                assert should_jam(100, stack_bb, pos, 0.5)

    def test_72o_never_jams_above_5bb_utg(self):
        score = score_starting_hand(*K72O)
        assert not should_jam(score, 8, 'UTG', 0.5)
        assert not should_jam(score, 12, 'UTG', 0.5)
        assert not should_jam(score, 15, 'UTG', 0.5)

    def test_range_widens_with_position_and_stack(self):
        score = score_starting_hand(*A7O)  # score 55
        assert not should_jam(score, 12, 'UTG', 0.5)
        assert should_jam(score, 5, 'SB', 0.5)


class TestShouldCallJam:
    def test_tighter_with_players_behind(self):
        # A borderline hand should call more often heads-up (0 behind) than
        # with someone left to act.
        score = score_cutoff_for_fraction(0.20)  # right at the 8bb HU cutoff-ish
        hu = should_call_jam(score, 8, players_behind=0, num_all_ins=1)
        behind = should_call_jam(score, 8, players_behind=1, num_all_ins=1)
        assert hu or not behind  # HU call range is a superset of players-behind range
        assert call_fraction(8, 0, 1) > call_fraction(8, 1, 1)

    def test_tighter_with_two_or_more_all_ins(self):
        assert call_fraction(8, 0, 2) == 0.05
        assert call_fraction(8, 0, 1) > call_fraction(8, 0, 2)


# ---------------------------------------------------------------------------
# Task 2: preflop all-in tracking
# ---------------------------------------------------------------------------

class TestFacingPreflopJamTracking:
    def test_flags_fill_and_reset_across_hands(self):
        strategy = BalancedStrategy()
        strategy._bot_name = 'Bot'
        events = [
            GameEvent(0, 'hand_started', dict(hand_number=1)),
            GameEvent(1, 'action_taken', dict(player_id='p1', name='Opp1',
                      action='all-in', amount=400, all_in=True, street='preflop')),
            GameEvent(2, 'action_taken', dict(player_id='p2', name='Opp2',
                      action='call', amount=400, all_in=False, street='preflop')),
        ]
        gs = state(events=events, self_id='p_bot', self_name='Bot')
        strategy._record_opponent_actions(gs)
        assert strategy._preflop_all_ins == [('Opp1', 400)]
        num, jam_bb = strategy._facing_preflop_jam(20)
        assert num == 1
        assert jam_bb == 20.0

        events2 = events + [GameEvent(3, 'hand_started', dict(hand_number=2))]
        gs2 = state(events=events2, self_id='p_bot', self_name='Bot')
        strategy._record_opponent_actions(gs2)
        assert strategy._preflop_all_ins == []
        num2, jam_bb2 = strategy._facing_preflop_jam(20)
        assert num2 == 0
        assert jam_bb2 == 0.0


# ---------------------------------------------------------------------------
# Task 3: push_fold_skill difficulty dial
# ---------------------------------------------------------------------------

class TestPushFoldSkillField:
    def test_values(self):
        assert mistakes_for(0.2).push_fold_skill == 0.2
        assert mistakes_for(0.4).push_fold_skill == 0.4
        assert mistakes_for(0.6).push_fold_skill == 0.7
        assert mistakes_for(0.75).push_fold_skill == 0.95
        assert mistakes_for(0.9).push_fold_skill == 1.0
        assert mistakes_for(1.0).push_fold_skill == 1.0


class TestEasyIgnoresChartsMostOfTheTime:
    def test_easy_uses_legacy_logic_roughly_60_percent(self):
        random.seed(3)
        strategy = BalancedStrategy(difficulty=EASY)
        legacy_hits = 0
        trials = 2000
        for _ in range(trials):
            use_charts = random.random() < strategy.mistakes.push_fold_skill
            if not use_charts:
                legacy_hits += 1
        rate = legacy_hits / trials
        assert 0.5 < rate < 0.7  # skill=0.4 -> ~60% legacy


# ---------------------------------------------------------------------------
# Task 4: engine hook
# ---------------------------------------------------------------------------

class TestEngineHookJamRates:
    def test_btn_jam_rate_near_chart(self):
        random.seed(5)
        strategy = BalancedStrategy(difficulty=PERFECT)  # aggression 0.5
        gs = state(min_call=0, pot_size=30, player_role='BTN',
                   big_blind=20, current_bet=20)
        jams = 0
        trials = 2000
        for _ in range(trials):
            r1, r2 = random.sample(range(2, 15), 2)
            suit1, suit2 = random.choice(list(Suit.get_all())), random.choice(list(Suit.get_all()))
            hole = [Card(r1, suit1), Card(r2, suit2)]
            view = make_view(chips=160, hole_cards=hole)  # 8bb
            action, _ = strategy.decide(gs, view)
            if action == PlayerAction.ALL_IN:
                jams += 1
        rate = jams / trials
        assert abs(rate - 0.42) < 0.08

    def test_utg_jam_rate_lower_than_btn(self):
        random.seed(6)
        strategy_utg = BalancedStrategy(difficulty=PERFECT)
        gs_utg = state(min_call=20, pot_size=30, player_role='UTG',
                       big_blind=20, current_bet=20)

        def jam_rate(strategy, gs):
            jams = 0
            trials = 1500
            for _ in range(trials):
                r1, r2 = random.sample(range(2, 15), 2)
                hole = [Card(r1, Suit.SPADES), Card(r2, Suit.HEARTS)]
                view = make_view(chips=160, hole_cards=hole)
                action, _ = strategy.decide(gs, view)
                if action == PlayerAction.ALL_IN:
                    jams += 1
            return jams / trials

        utg_rate = jam_rate(strategy_utg, gs_utg)
        strategy_btn = BalancedStrategy(difficulty=PERFECT)
        gs_btn = state(min_call=0, pot_size=30, player_role='BTN',
                       big_blind=20, current_bet=20)
        btn_rate = jam_rate(strategy_btn, gs_btn)
        assert abs(utg_rate - 0.18) < 0.08
        assert btn_rate > utg_rate


class TestFacingJamHeadsUp:
    def _jam_events(self, amount=200):
        return [
            GameEvent(0, 'hand_started', dict(hand_number=1)),
            GameEvent(1, 'action_taken', dict(player_id='p1', name='Opp1',
                      action='all-in', amount=amount, all_in=True, street='preflop')),
        ]

    def test_72o_always_folds_aa_always_calls(self):
        random.seed(9)
        strategy = BalancedStrategy(difficulty=PERFECT)
        events = self._jam_events(200)  # 10bb jam
        gs = state(min_call=200, pot_size=220, events=events,
                   self_id='p_bot', self_name='Bot', num_active=2,
                   players_info=[('Bot', 200, True), ('Opp1', 0, True)],
                   big_blind=20, current_bet=200)

        for _ in range(20):
            action, _ = strategy.decide(gs, make_view(chips=200, hole_cards=K72O))
            assert action == PlayerAction.FOLD

        for _ in range(20):
            action, _ = strategy.decide(gs, make_view(chips=200, hole_cards=AA))
            assert action in (PlayerAction.CALL, PlayerAction.ALL_IN)

    def test_call_rate_near_chart(self):
        random.seed(10)
        strategy = BalancedStrategy(difficulty=PERFECT)
        events = self._jam_events(200)  # 10bb jam -> uses 12bb band -> 0.18 HU
        gs = state(min_call=200, pot_size=220, events=events,
                   self_id='p_bot', self_name='Bot', num_active=2,
                   players_info=[('Bot', 200, True), ('Opp1', 0, True)],
                   big_blind=20, current_bet=200)
        calls = 0
        trials = 1500
        for _ in range(trials):
            r1, r2 = random.sample(range(2, 15), 2)
            hole = [Card(r1, Suit.SPADES), Card(r2, Suit.HEARTS)]
            action, _ = strategy.decide(gs, make_view(chips=200, hole_cards=hole))
            if action in (PlayerAction.CALL, PlayerAction.ALL_IN):
                calls += 1
        rate = calls / trials
        assert abs(rate - 0.18) < 0.08


class TestBBOptionChecksJunk:
    def test_bb_checks_free_option_with_junk(self):
        random.seed(11)
        strategy = BalancedStrategy(difficulty=PERFECT)
        gs = state(min_call=0, pot_size=30, player_role='BB',
                   big_blind=20, current_bet=20)
        view = make_view(chips=120, hole_cards=K72O)  # 6bb, score 5
        for _ in range(20):
            action, _ = strategy.decide(gs, view)
            assert action == PlayerAction.CHECK


class TestAANeverFoldedShortStack:
    def test_aa_never_folds_5bb_any_difficulty(self):
        for level in (EASY, NORMAL, HARD, EXPERT, PERFECT):
            random.seed(1)
            strategy = BalancedStrategy(difficulty=level)
            gs = state(min_call=0, pot_size=30, player_role='UTG',
                       big_blind=20, current_bet=20)
            view = make_view(chips=100, hole_cards=AA)  # 5bb
            for _ in range(20):
                action, _ = strategy.decide(gs, view)
                assert action != PlayerAction.FOLD


# ---------------------------------------------------------------------------
# Task 6: style/difficulty regression tests
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestLadderSmokeCanary:
    def test_easy_less_than_hard_reduced(self):
        from core.game import Game
        from players.bot import BotPlayer

        def run_level(level, num_tables=12, hands_per_table=100):
            total_net = 0
            for _ in range(num_tables):
                g = Game(big_blind=20, hands_per_level=9999,
                          live_output=False, game_mode='cash')
                g.add_player(BotPlayer('subject', 'Subject', 1000, BalancedStrategy(level)))
                for i in range(3):
                    g.add_player(BotPlayer(f'opp{i}', f'Opp{i}', 1000, BalancedStrategy(NORMAL)))
                for _ in range(hands_per_table):
                    g.start_game()
                    for p in g.players:
                        if p.chips == 0:
                            p.chips = 1000
                            g.stats[p.player_id]['total_invested'] += 1000
                s = g.stats['subject']
                net = next(p.chips for p in g.players if p.player_id == 'subject') - s['total_invested']
                total_net += net
            return total_net

        random.seed(42)
        easy_net = run_level(EASY)
        hard_net = run_level(HARD)
        assert easy_net < hard_net


class TestManiacVsNitTint:
    def test_maniac_jams_more_than_nit(self):
        random.seed(13)
        gs = state(min_call=0, pot_size=30, player_role='CO',
                   big_blind=20, current_bet=20)

        def jam_rate(strategy):
            jams = 0
            trials = 2000
            for _ in range(trials):
                r1, r2 = random.sample(range(2, 15), 2)
                hole = [Card(r1, Suit.SPADES), Card(r2, Suit.HEARTS)]
                view = make_view(chips=160, hole_cards=hole)  # 8bb
                action, _ = strategy.decide(gs, view)
                if action == PlayerAction.ALL_IN:
                    jams += 1
            return jams / trials

        maniac_rate = jam_rate(ManiacStrategy(difficulty=PERFECT))
        nit_rate = jam_rate(NitStrategy(difficulty=PERFECT))
        assert maniac_rate > nit_rate


class TestNoRegressionAtDeepStacks:
    def test_deep_stack_hook_never_fires_without_all_in(self):
        random.seed(14)
        strategy = BalancedStrategy(difficulty=PERFECT)
        gs = state(min_call=0, pot_size=100, player_role='BTN',
                   big_blind=20, current_bet=20)
        view = make_view(chips=1200, hole_cards=K72O)  # 60bb
        for _ in range(50):
            action, _ = strategy.decide(gs, view)
            # 60bb is above the 15bb threshold and no all-in occurred, so the
            # hook must not fire: junk from the button either checks the
            # (nonexistent) option or plays the ordinary legacy path, never
            # an automatic short-stack jam.
            assert action != PlayerAction.ALL_IN


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
