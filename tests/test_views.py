"""
Tests for Phase 3 serialization / per-viewer snapshots (core/views.py) and the
seedable deck.
Run with: pytest tests/test_views.py -v
"""
import json
import random

from core.game import Game
from core.player import Player, PlayerAction
from core.card import Card, Suit, Rank
from players.bot import BotPlayer
from players.agent import AgentPlayer
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


def _agent_table(seed_global=1):
    random.seed(seed_global)
    g = Game(big_blind=20, live_output=False)
    g.add_player(AgentPlayer("h1", "Human", 1000))
    g.add_player(BotPlayer("b1", "Bot1", 1000, SimpleStrategy(aggressiveness=0.4)))
    g.add_player(BotPlayer("b2", "Bot2", 1000, SimpleStrategy(aggressiveness=0.4)))
    return g


# ── Card serialization ────────────────────────────────────────────────────────

def test_card_to_dict():
    c = Card(Rank.ACE, Suit.SPADES)
    assert c.to_dict() == {"rank": 14, "suit": "S", "display": "A♠"}
    assert json.dumps(c.to_dict())


# ── json.dumps survives before / during / after a hand ────────────────────────

def test_view_serializable_between_hands():
    g = _agent_table()
    # Before any hand: WAITING, no cards.
    json.dumps(g.view_for("h1"))
    json.dumps(g.view_for(None))
    assert g.view_for("h1")["state"] == "WAITING"


def test_view_serializable_mid_hand():
    g = _agent_table()
    g.start_hand()  # pauses for h1
    view = g.view_for("h1")
    json.dumps(view)                    # must not raise
    assert view["you"]["to_act"] is True
    assert view["you"]["action_request"] is not None


def test_view_serializable_after_showdown():
    random.seed(3)
    g = Game(big_blind=20, live_output=False)
    for i in range(3):
        g.add_player(BotPlayer(f"p{i}", f"P{i}", 1000, SimpleStrategy(aggressiveness=0.3)))
    g.start_game()
    view = g.view_for(None)
    json.dumps(view)
    # The hand is over (WAITING): the pot has been distributed, so the view
    # reports an empty pot even though pot_manager retains last-hand state.
    assert view["pots"] == []
    assert view["pot"] == 0


def _drive_fold_out(g):
    g.start_hand()
    while g.pending_request is not None:
        g.submit_action(g.pending_request.player_id, PlayerAction.FOLD, 0)


def test_all_in_flag_cleared_between_hands():
    """After a hand ends, no player should still read as all-in (regression:
    is_all_in lingered, incl. for busted all-in players)."""
    g = Game(big_blind=20, live_output=False, game_mode="tournament")
    g.add_player(AgentPlayer("h1", "You", 40))
    g.add_player(AgentPlayer("h2", "Opp", 40))
    g.start_hand()
    while g.pending_request is not None:
        req = g.pending_request
        if "all-in" in req.legal_actions:
            g.submit_action(req.player_id, PlayerAction.ALL_IN, req.max_raise_total)
        elif "call" in req.legal_actions:
            g.submit_action(req.player_id, PlayerAction.CALL, req.min_call)
        else:
            g.submit_action(req.player_id, PlayerAction.CHECK, 0)
    view = g.view_for("h1")
    assert all(not p["is_all_in"] for p in view["players"])


def test_blind_countdown_reaches_one_on_boundary_hand():
    """The in-progress boundary hand must read 'next in 1', not a full level."""
    g = Game(big_blind=20, hands_per_level=5, live_output=False, game_mode="tournament")
    g.add_player(AgentPlayer("h1", "You", 10_000_000))
    g.add_player(AgentPlayer("h2", "Opp", 10_000_000))
    g.start_hand()                       # hand 1, in progress
    assert g.view_for("h1")["blinds"]["hands_to_level"] == 5
    while g.pending_request is not None:
        g.submit_action(g.pending_request.player_id, PlayerAction.FOLD, 0)
    for _ in range(3):                   # finish hands 2, 3, 4
        _drive_fold_out(g)
    g.start_hand()                       # hand 5 (boundary), in progress
    assert g.view_for("h1")["blinds"]["hands_to_level"] == 1


# ── Hidden-information filtering ───────────────────────────────────────────────

def test_viewer_sees_only_own_hole_cards():
    g = _agent_table()
    g.start_hand()
    view = g.view_for("h1")

    for p in view["players"]:
        if p["player_id"] == "h1":
            assert p["is_you"] is True
            assert "hole_cards" in p
            assert len(p["hole_cards"]) == 2
        else:
            # No opponent hole cards, ever — key omitted entirely.
            assert "hole_cards" not in p


def test_spectator_sees_no_hole_cards():
    g = _agent_table()
    g.start_hand()
    view = g.view_for(None)
    assert view["you"] is None
    for p in view["players"]:
        assert "hole_cards" not in p


def test_events_for_filters_other_hole_cards():
    random.seed(7)
    g = Game(big_blind=20, live_output=False)
    for i in range(3):
        g.add_player(BotPlayer(f"p{i}", f"P{i}", 1000, SimpleStrategy(aggressiveness=0.3)))
    g.start_game()

    for viewer in ("p0", "p1", "p2"):
        events = g.events_for(viewer)
        dealt = [e for e in events if e["type"] == "hole_cards_dealt"]
        assert all(e["data"]["player_id"] == viewer for e in dealt)

    spectator = g.events_for(None)
    assert not any(e["type"] == "hole_cards_dealt" for e in spectator)


# ── view_for correctness spot-checks ───────────────────────────────────────────

def test_view_pot_and_bets_consistent():
    g = _agent_table()
    g.start_hand()
    view = g.view_for("h1")

    assert view["pot"] == g.pot_manager.total_pot()
    for pd in view["players"]:
        assert pd["bet_this_round"] == \
            g.bet_manager.player_bets_this_round.get(pd["player_id"], 0)
        assert pd["invested_this_hand"] == \
            g.pot_manager.contributions.get(pd["player_id"], 0)

    # to_act consistent with pending_request
    assert view["you"]["to_act"] == (g.pending_request.player_id == "h1")
    assert view["you"]["action_request"]["legal_actions"] == \
        g.pending_request.legal_actions


# ── v1.2 Tier 3: hand strength, bot style tags, blind countdown ───────────────

def test_hand_name_none_preflop_present_postflop():
    random.seed(0)
    g = Game(big_blind=20, live_output=False, seed=5)
    g.add_player(AgentPlayer("h1", "Human", 1000))
    g.add_player(CallingPlayer("b1", "B1", 1000))
    g.add_player(CallingPlayer("b2", "B2", 1000))

    g.start_hand()  # paused for h1 preflop
    assert g.view_for("h1")["you"]["hand_name"] is None

    # Check/call through to the flop; the calling bots never raise, so each
    # street pauses for h1 exactly once.
    guard = 0
    while g.pending_request is not None and len(g.community_cards) < 3:
        guard += 1
        assert guard < 10, "did not reach the flop"
        legal = g.pending_request.legal_actions
        act = PlayerAction.CHECK if "check" in legal else PlayerAction.CALL
        g.submit_action("h1", act, 0)

    assert len(g.community_cards) >= 3
    name = g.view_for("h1")["you"]["hand_name"]
    assert isinstance(name, str) and name

    # Spectators have no `you` at all — nothing to leak.
    assert g.view_for(None)["you"] is None


def test_bot_style_tags_in_view():
    from strategies.profile import StyleProfile
    from strategies.engine import DesignedBotStrategy

    g = Game(big_blind=20, live_output=False)
    g.add_player(AgentPlayer("h1", "Human", 1000))
    profile = StyleProfile(name="TestStyle", play_range=0.5, aggression=0.5,
                           bluff_freq=0.2, call_freq=0.5)
    g.add_player(BotPlayer("b1", "B1", 1000, DesignedBotStrategy(profile, 0.6)))
    g.add_player(BotPlayer("b2", "B2", 1000, SimpleStrategy(aggressiveness=0.4)))

    styles = {p["player_id"]: p["style"] for p in g.view_for("h1")["players"]}
    assert styles["h1"] is None            # humans have no strategy
    assert styles["b1"] == "TestStyle"     # designed bot exposes its archetype
    assert styles["b2"] is None            # simple strategy has no profile


def test_hands_to_level_countdown_and_cash_mode():
    g = Game(big_blind=20, hands_per_level=5, live_output=False)
    g.add_player(CallingPlayer("p0", "P0", 1000))
    g.add_player(CallingPlayer("p1", "P1", 1000))

    assert g.view_for(None)["blinds"]["hands_to_level"] == 5  # fresh table
    g.start_game()
    assert g.view_for(None)["blinds"]["hands_to_level"] == 4  # one hand played

    g_cash = Game(big_blind=20, live_output=False, game_mode='cash')
    g_cash.add_player(CallingPlayer("p0", "P0", 1000))
    g_cash.add_player(CallingPlayer("p1", "P1", 1000))
    assert g_cash.view_for(None)["blinds"]["hands_to_level"] is None


# ── Seedable deck determinism ─────────────────────────────────────────────────

def _play_seeded(seed, n=20):
    random.seed(0)  # global RNG is irrelevant (deck is seeded, players deterministic)
    g = Game(big_blind=20, live_output=False, seed=seed)
    for i in range(3):
        g.add_player(CallingPlayer(f"p{i}", f"P{i}", 1000))
    collected = []
    for _ in range(n):
        if len([p for p in g.players if p.chips > 0]) <= 1:
            break
        g.start_game()
        collected.append([e.to_dict() for e in g.events])
    return collected


def test_seed_produces_identical_deals():
    run_a = _play_seeded(42)
    run_b = _play_seeded(42)
    assert run_a == run_b
    assert len(run_a) > 0


def test_different_seeds_differ():
    run_a = _play_seeded(42)
    run_b = _play_seeded(43)
    assert run_a != run_b
