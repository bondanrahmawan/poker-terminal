"""
Tests for the Phase 1 structured event stream (core/events.py + Game.emit).
Run with: pytest tests/test_events.py -v
"""
import random

from core.game import Game
from core.player import Player, PlayerAction
from players.bot import BotPlayer
from strategies.simple import SimpleStrategy


class CallingPlayer(Player):
    """Deterministic, non-interactive: always checks or calls (no randomness)."""

    def get_action(self, game_state):
        min_call = game_state['min_call']
        if min_call == 0:
            return PlayerAction.CHECK, 0
        amt = min(self.chips, min_call)
        if amt >= self.chips:
            return PlayerAction.ALL_IN, self.chips
        return PlayerAction.CALL, amt


def _build_game(seed, n=3, chips=1000, big_blind=20, aggressiveness=0.4):
    random.seed(seed)
    g = Game(big_blind=big_blind, live_output=False)
    for i in range(n):
        g.add_player(BotPlayer(f"p{i}", f"Player{i}", chips,
                               SimpleStrategy(aggressiveness=aggressiveness)))
    return g


def test_event_sequence_prefix():
    """The event stream must open with the deal/blind structure in order."""
    g = _build_game(seed=42, n=3)
    n_active = len([p for p in g.players if p.is_active])
    g.start_game()

    types = [e.type for e in g.events]

    assert types[0] == 'hand_started'
    assert types[1] == 'seating'
    # One hole_cards_dealt per active player
    assert types[2:2 + n_active] == ['hole_cards_dealt'] * n_active

    idx = 2 + n_active
    assert g.events[idx].type == 'street_started'
    assert g.events[idx].data['street'] == 'preflop'
    assert g.events[idx + 1].type == 'blind_posted'
    assert g.events[idx + 1].data['kind'] == 'small'
    assert g.events[idx + 2].type == 'blind_posted'
    assert g.events[idx + 2].data['kind'] == 'big'


def test_seq_is_dense_and_increasing():
    """seq values must be 0, 1, 2, ... with no gaps or repeats."""
    g = _build_game(seed=123, n=4)
    g.start_game()

    seqs = [e.seq for e in g.events]
    assert seqs == list(range(len(seqs)))


def test_hand_started_payload():
    g = _build_game(seed=7, n=3, big_blind=20)
    g.start_game()

    started = next(e for e in g.events if e.type == 'hand_started')
    d = started.data
    assert d['hand_number'] == 1
    assert d['big_blind'] == 20
    assert d['small_blind'] == 10
    assert d['game_mode'] == 'tournament'
    assert d['dealer_player_id'] in {p.player_id for p in g.players}


def test_action_pot_is_monotonic_non_decreasing():
    """Pot recorded on blinds/actions only ever grows within a hand."""
    g = _build_game(seed=222, n=3)
    g.start_game()

    pots = [e.data['pot'] for e in g.events
            if e.type in ('blind_posted', 'action_taken')]
    assert pots == sorted(pots)
    assert all(isinstance(p, int) for p in pots)


def test_winnings_equal_total_pot():
    """The sum of pot_awarded amounts must equal the total contributed pot."""
    g = _build_game(seed=333, n=3)
    g.start_game()

    awarded = [e for e in g.events if e.type == 'pot_awarded']
    assert awarded, "every hand must award the pot to at least one player"
    total_awarded = sum(e.data['amount'] for e in awarded)
    assert total_awarded == g.pot_manager.total_pot()


def test_hand_ended_emitted_last():
    g = _build_game(seed=444, n=3)
    g.start_game()

    assert g.events[-1].type == 'hand_ended'
    ended = g.events[-1]
    assert ended.data['hand_number'] == 1
    assert set(ended.data['chip_counts']) == {p.player_id for p in g.players}


def test_events_cleared_per_hand_in_sim_mode():
    """In non-live mode the event list is bounded (reset each hand)."""
    g = _build_game(seed=555, n=3)
    g.start_game()
    g.start_game()
    # The list holds only the second hand's events, not both hands'.
    hand_starts = [e for e in g.events if e.type == 'hand_started']
    assert len(hand_starts) == 1
    assert hand_starts[0].data['hand_number'] == 2
    assert g.events[0].type == 'hand_started'


def test_pot_structure_emitted_with_side_pots():
    """A short-stacked all-in forces a main + side pot; the showdown emits one
    pot_structure event describing both."""
    random.seed(0)
    g = Game(big_blind=100, live_output=False)
    # p0's 60 chips can't cover the 100 BB, so it's all-in for 60 preflop while
    # the two deep stacks equalize at 100 → one main pot + one side pot.
    g.add_player(CallingPlayer("p0", "Player0", 60))
    g.add_player(CallingPlayer("p1", "Player1", 1000))
    g.add_player(CallingPlayer("p2", "Player2", 1000))
    g.start_game()

    structures = [e for e in g.events if e.type == 'pot_structure']
    assert len(structures) == 1
    pots = structures[0].data['pots']
    assert len(pots) == 2
    assert pots[0]['label'] == 'Main Pot'
    assert pots[1]['label'] == 'Side Pot 1'


def test_event_to_dict():
    g = _build_game(seed=666, n=3)
    g.start_game()
    d = g.events[0].to_dict()
    assert set(d) == {'seq', 'type', 'data'}
    assert d['seq'] == 0
    assert d['type'] == 'hand_started'
