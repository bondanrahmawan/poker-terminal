"""
Tests for the Phase 2 resumable engine (start_hand / advance / submit_action).
Run with: pytest tests/test_resumable_engine.py -v
"""
import random

import pytest

from core.game import Game
from core.player import Player, PlayerAction
from core.errors import IllegalActionError
from players.bot import BotPlayer
from players.agent import AgentPlayer
from strategies.simple import SimpleStrategy


class ScriptedPlayer(Player):
    """Non-interactive player that plays a fixed list of intents synchronously.
    Mirrors the normalization the engine applies to interactive actions so the
    synchronous path and the AgentPlayer path feed identical actions to the engine.
    """

    def __init__(self, player_id, name, chips, script):
        super().__init__(player_id, name, chips)
        self._script = list(script)
        self._i = 0

    def _next_intent(self):
        intent = self._script[self._i] if self._i < len(self._script) else 'call'
        self._i += 1
        return intent

    def get_action(self, game_state):
        intent = self._next_intent()
        min_call = game_state['min_call']
        min_raise = game_state['min_raise']
        if intent == 'fold':
            return PlayerAction.FOLD, 0
        if intent == 'check':
            return PlayerAction.CHECK, 0
        if intent == 'call':
            if min_call == 0:
                return PlayerAction.CHECK, 0
            amt = min(self.chips, min_call)
            if amt >= self.chips:
                return PlayerAction.ALL_IN, self.chips
            return PlayerAction.CALL, amt
        if intent == 'raise':
            amt = min(self.chips, min_call + min_raise)
            if amt >= self.chips:
                return PlayerAction.ALL_IN, self.chips
            return PlayerAction.RAISE, amt
        if intent == 'all-in':
            return PlayerAction.ALL_IN, self.chips
        raise ValueError(intent)


def _submit_intent(g, req, intent):
    """Drive an AgentPlayer with the same intent semantics as ScriptedPlayer."""
    if intent == 'call' and 'check' in req.legal_actions:
        return g.submit_action(req.player_id, PlayerAction.CHECK, 0)
    if intent == 'raise':
        return g.submit_action(req.player_id, PlayerAction.RAISE, req.min_raise_total)
    mapping = {
        'fold': PlayerAction.FOLD, 'check': PlayerAction.CHECK,
        'call': PlayerAction.CALL, 'all-in': PlayerAction.ALL_IN,
    }
    return g.submit_action(req.player_id, mapping[intent], 0)


# ── 1. Equivalence: synchronous scripted seat == AgentPlayer via submit_action ──

SEED = 20240607


def _sig(g):
    """A behavioral signature: final chips + the money-moving event stream."""
    chips = {p.player_id: p.chips for p in g.players}
    stream = [(e.type, e.data.get('player_id'), e.data.get('action'),
               e.data.get('amount')) for e in g.events
              if e.type in ('blind_posted', 'action_taken', 'pot_awarded')]
    return chips, stream


def _build(human_cls, human_script=None):
    random.seed(SEED)
    g = Game(big_blind=20, live_output=False)
    if human_cls is ScriptedPlayer:
        g.add_player(ScriptedPlayer("h1", "Human", 1000, human_script))
    else:
        g.add_player(AgentPlayer("h1", "Human", 1000))
    g.add_player(BotPlayer("b1", "Bot1", 1000, SimpleStrategy(aggressiveness=0.5)))
    g.add_player(BotPlayer("b2", "Bot2", 1000, SimpleStrategy(aggressiveness=0.5)))
    return g


def test_agent_path_equivalent_to_synchronous():
    intents = ['call'] * 40

    g_sync = _build(ScriptedPlayer, intents)
    g_sync.start_game()

    g_agent = _build(AgentPlayer)
    req = g_agent.start_hand()
    i = 0
    while req is not None:
        assert req.player_id == "h1"
        req = _submit_intent(g_agent, req, intents[i])
        i += 1

    assert _sig(g_sync) == _sig(g_agent)


# ── 2. Pause/resume mechanics ─────────────────────────────────────────────────

def _agent_table(chips=1000, big_blind=20, seed=1):
    random.seed(seed)
    g = Game(big_blind=big_blind, live_output=False)
    g.add_player(AgentPlayer("h1", "Human", chips))
    g.add_player(BotPlayer("b1", "Bot1", chips, SimpleStrategy(aggressiveness=0.4)))
    g.add_player(BotPlayer("b2", "Bot2", chips, SimpleStrategy(aggressiveness=0.4)))
    return g


def test_start_hand_pauses_for_agent():
    g = _agent_table()
    req = g.start_hand()
    assert req is not None
    assert req.player_id == "h1"
    assert 'fold' in req.legal_actions
    assert 'all-in' in req.legal_actions


def test_pending_request_stable_and_idempotent():
    g = _agent_table()
    req = g.start_hand()
    assert g.pending_request is req
    assert g.advance() is req          # advance while paused is idempotent
    assert g.advance() is req
    assert g.pending_request is req


def test_action_request_seq_is_last_emitted_event():
    """req.seq must be the event high-water mark (same cursor semantics as
    view.last_event_seq), so clients can use it as an /events `since` value
    without missing the first post-pause event."""
    g = _agent_table()
    req = g.start_hand()
    assert req.seq == g.events[-1].seq
    assert req.seq == g.view_for("h1")["last_event_seq"]


def test_out_of_turn_submission_raises():
    g = _agent_table()
    g.start_hand()
    with pytest.raises(IllegalActionError):
        g.submit_action("b1", PlayerAction.CALL, 0)


def test_illegal_raise_size_raises():
    g = _agent_table()
    req = g.start_hand()
    with pytest.raises(IllegalActionError):
        g.submit_action("h1", PlayerAction.RAISE, req.max_raise_total + 1000)


def test_submit_with_no_pending_raises():
    g = _agent_table()
    with pytest.raises(IllegalActionError):
        g.submit_action("h1", PlayerAction.CALL, 0)


def test_fold_runs_hand_to_completion():
    g = _agent_table()
    g.start_hand()
    result = g.submit_action("h1", PlayerAction.FOLD, 0)
    assert result is None
    assert g.pending_request is None
    assert g.state.name == "WAITING"
    # The hand still resolved for the two bots.
    assert any(e.type == 'pot_awarded' for e in g.events)


# ── 3. Raise re-opens betting ─────────────────────────────────────────────────

def test_raise_reopens_betting_for_agent():
    random.seed(5)
    g = Game(big_blind=20, live_output=False)
    g.add_player(AgentPlayer("h1", "Human", 1000))          # seat 0, acts first preflop
    g.add_player(ScriptedPlayer("s1", "Raiser", 1000, ['raise', 'call', 'call']))
    g.add_player(ScriptedPlayer("s2", "Caller", 1000, ['call', 'call', 'call']))

    req = g.start_hand()
    assert req.player_id == "h1"
    first_call = req.min_call

    # Agent calls; s1 then raises, which must re-open the action back to the agent.
    req2 = g.submit_action("h1", PlayerAction.CALL, 0)
    assert req2 is not None
    assert req2.player_id == "h1"
    assert req2.street == "preflop"
    assert req2.min_call > 0
    assert req2.min_call >= first_call


# ── 4. All-in agent ───────────────────────────────────────────────────────────

def test_all_in_agent_needs_no_more_input():
    g = _agent_table()
    g.start_hand()
    result = g.submit_action("h1", PlayerAction.ALL_IN, 0)
    assert result is None                     # no further requests for the agent
    assert g.pending_request is None
    assert g.state.name == "WAITING"


# ── 5. Bot-only regression ────────────────────────────────────────────────────

def test_bot_only_start_game_conserves_chips():
    random.seed(99)
    g = Game(big_blind=20, live_output=False)
    for i in range(8):
        g.add_player(BotPlayer(f"b{i}", f"Bot{i}", 1000,
                               SimpleStrategy(aggressiveness=0.3 + i * 0.05)))
    start_total = sum(p.chips for p in g.players)

    for _ in range(200):
        active = [p for p in g.players if p.chips > 0]
        if len(active) <= 1:
            break
        g.start_game()

    assert sum(p.chips for p in g.players) == start_total


def test_start_game_rejects_interactive_table():
    g = _agent_table()
    with pytest.raises(RuntimeError):
        g.start_game()
