"""
Tests for the Phase 4 FastAPI transport (api/).
Run with: pytest tests/test_api.py -v
"""
import functools
import threading
import time

import pytest
from fastapi.testclient import TestClient

from api.server import app
from api.sessions import SessionManager, CapacityError
from core.stats_persistent import PersistentStatsManager
from core.simulation_stats import SimulationStatsManager

client = TestClient(app)

SETTINGS = {
    "player_name": "Tester",
    "num_bots": 2,
    "difficulty": "normal",
    "starting_chips": 1000,
    "big_blind": 20,
    "seed": 42,
}
TOTAL_CHIPS = (1 + SETTINGS["num_bots"]) * SETTINGS["starting_chips"]


def _create():
    r = client.post("/games", json=SETTINGS)
    assert r.status_code == 201
    return r.json()


def _assert_no_foreign_hole_cards(obj):
    """Recursively assert no hole cards belong to anyone but h1."""
    if isinstance(obj, dict):
        if "hole_cards" in obj and obj.get("player_id") not in (None, "h1"):
            raise AssertionError(f"hole_cards leaked for {obj.get('player_id')}")
        if obj.get("type") == "hole_cards_dealt":
            assert obj["data"]["player_id"] == "h1"
        for v in obj.values():
            _assert_no_foreign_hole_cards(v)
    elif isinstance(obj, list):
        for v in obj:
            _assert_no_foreign_hole_cards(v)


def _play_hand_always_call(game_id):
    """Start a hand and respond to every request with check/call."""
    r = client.post(f"/games/{game_id}/hands")
    assert r.status_code == 200, r.text
    view = r.json()["view"]
    guard = 0
    while view["you"] and view["you"]["to_act"]:
        guard += 1
        assert guard < 50, "runaway action loop"
        legal = view["you"]["action_request"]["legal_actions"]
        action = "check" if "check" in legal else "call"
        r = client.post(f"/games/{game_id}/action", json={"action": action})
        assert r.status_code == 200, r.text
        view = r.json()["view"]
    return view


def test_create_game_does_not_start_hand():
    data = _create()
    assert "game_id" in data
    assert data["view"]["state"] == "WAITING"
    assert data["view"]["hand_number"] == 0


def test_full_hand_to_completion_conserves_chips():
    game_id = _create()["game_id"]
    view = _play_hand_always_call(game_id)

    # Hand resolved.
    assert view["state"] == "WAITING"

    # hand_ended event arrived.
    events = client.get(f"/games/{game_id}/events", params={"since": -1}).json()["events"]
    assert any(e["type"] == "hand_ended" for e in events)

    # Chip conservation.
    state = client.get(f"/games/{game_id}/state").json()
    assert sum(p["chips"] for p in state["players"]) == TOTAL_CHIPS


def test_no_hole_card_leakage():
    game_id = _create()["game_id"]
    client.post(f"/games/{game_id}/hands")

    state = client.get(f"/games/{game_id}/state").json()
    _assert_no_foreign_hole_cards(state)
    # The human should see exactly their own two cards.
    me = next(p for p in state["players"] if p["player_id"] == "h1")
    assert len(me["hole_cards"]) == 2

    events = client.get(f"/games/{game_id}/events").json()
    _assert_no_foreign_hole_cards(events)


def test_illegal_action_returns_422():
    game_id = _create()["game_id"]
    client.post(f"/games/{game_id}/hands")
    state = client.get(f"/games/{game_id}/state").json()
    assert state["you"]["to_act"]
    max_raise = state["you"]["action_request"]["max_raise_total"]

    r = client.post(f"/games/{game_id}/action",
                    json={"action": "raise", "amount": max_raise + 5000})
    assert r.status_code == 422


def test_unknown_action_string_returns_422():
    game_id = _create()["game_id"]
    client.post(f"/games/{game_id}/hands")
    r = client.post(f"/games/{game_id}/action", json={"action": "teleport"})
    assert r.status_code == 422


def test_action_with_no_pending_returns_409():
    game_id = _create()["game_id"]
    # No hand started yet -> nothing pending.
    r = client.post(f"/games/{game_id}/action", json={"action": "call"})
    assert r.status_code == 409
    assert r.json()["reason"] == "no_pending_action"


def test_unknown_game_returns_404():
    assert client.get("/games/does-not-exist/state").status_code == 404
    assert client.post("/games/does-not-exist/hands").status_code == 404


def test_hand_in_progress_returns_409():
    game_id = _create()["game_id"]
    assert client.post(f"/games/{game_id}/hands").status_code == 200
    # A second start while paused for the human is a conflict.
    r = client.post(f"/games/{game_id}/hands")
    assert r.status_code == 409
    assert r.json()["reason"] == "hand_in_progress"


def test_delete_game():
    game_id = _create()["game_id"]
    assert client.delete(f"/games/{game_id}").status_code == 204
    assert client.get(f"/games/{game_id}/state").status_code == 404


def _patch_stats_file(monkeypatch, tmp_path):
    """Redirect persistence to a throwaway stats file so tests never touch the
    real player_stats.json. Patches both the writer (api.sessions) and the
    read-only viewer endpoints (api.server). Returns the file path."""
    stats_file = tmp_path / "player_stats.json"
    patched = functools.partial(PersistentStatsManager, stats_file=stats_file)
    monkeypatch.setattr("api.sessions.PersistentStatsManager", patched)
    monkeypatch.setattr("api.server.PersistentStatsManager", patched)
    return stats_file


def test_delete_persists_played_session(monkeypatch, tmp_path):
    stats_file = _patch_stats_file(monkeypatch, tmp_path)
    game_id = _create()["game_id"]
    _play_hand_always_call(game_id)
    assert client.delete(f"/games/{game_id}").status_code == 204

    history = PersistentStatsManager(stats_file=stats_file).get_session_history()
    assert len(history) == 1


def test_delete_zero_hands_persists_nothing(monkeypatch, tmp_path):
    stats_file = _patch_stats_file(monkeypatch, tmp_path)
    game_id = _create()["game_id"]
    assert client.delete(f"/games/{game_id}").status_code == 204

    history = PersistentStatsManager(stats_file=stats_file).get_session_history()
    assert history == []


def test_tournament_stats_endpoints_reflect_played_session(monkeypatch, tmp_path):
    _patch_stats_file(monkeypatch, tmp_path)
    game_id = _create()["game_id"]  # SETTINGS difficulty is "normal" -> "Normal"
    _play_hand_always_call(game_id)
    assert client.delete(f"/games/{game_id}").status_code == 204

    sessions = client.get("/stats/tournament/sessions").json()
    assert len(sessions) == 1
    assert sessions[0]["difficulty"] == "Normal"

    # Difficulty filter passes through to the getter.
    assert client.get("/stats/tournament/sessions", params={"difficulty": "Normal"}).json()
    assert client.get("/stats/tournament/sessions", params={"difficulty": "Hard"}).json() == []

    players = client.get("/stats/tournament/players").json()
    assert "Normal" in players
    assert any(p["player_id"] == "h1" for p in players["Normal"])

    history = client.get("/stats/tournament/players/h1").json()
    assert history["player_id"] == "h1"
    assert history["all_time"]["total_sessions"] == 1


def test_tournament_stats_endpoints_empty(monkeypatch, tmp_path):
    _patch_stats_file(monkeypatch, tmp_path)
    assert client.get("/stats/tournament/sessions").json() == []
    assert client.get("/stats/tournament/players").json() == {}
    assert client.get("/stats/tournament/players/nobody").json() == {}


def test_stats_endpoint():
    game_id = _create()["game_id"]
    _play_hand_always_call(game_id)
    data = client.get(f"/games/{game_id}/stats").json()
    assert data["hand_count"] == 1
    assert "h1" in data["stats"]


def _h1(view):
    return next(p for p in view["players"] if p["player_id"] == "h1")


def test_session_manager_caps_concurrent_sessions():
    mgr = SessionManager(max_sessions=2)
    mgr.create(SETTINGS)
    mgr.create(SETTINGS)
    with pytest.raises(CapacityError):
        mgr.create(SETTINGS)


def test_stats_api_omits_cumulative_net():
    game_id = _create()["game_id"]
    s = client.get(f"/games/{game_id}/stats").json()["stats"]["h1"]
    assert "cumulative_net" not in s          # engine-internal, always 0 here
    assert "total_invested" in s and "topups" in s   # real fields still present


def test_topup_before_hand_doubles_chips_and_invested():
    game_id = _create()["game_id"]
    r = client.post(f"/games/{game_id}/topup")
    assert r.status_code == 200, r.text
    assert _h1(r.json()["view"])["chips"] == 2 * SETTINGS["starting_chips"]
    stats = client.get(f"/games/{game_id}/stats").json()["stats"]["h1"]
    assert stats["total_invested"] == 2 * SETTINGS["starting_chips"]
    # A top-up counts as invested money but is NOT a rebuy (which means busting
    # and buying back in) — they are tracked separately.
    assert stats["topups"] == 1
    assert stats["rebuys"] == 0


def test_topup_mid_hand_returns_409_chips_unchanged():
    game_id = _create()["game_id"]
    client.post(f"/games/{game_id}/hands")  # now awaiting the human's action
    state = client.get(f"/games/{game_id}/state").json()
    assert state["you"]["to_act"]
    chips_before = _h1(state)["chips"]

    r = client.post(f"/games/{game_id}/topup")
    assert r.status_code == 409
    assert r.json()["reason"] == "hand_in_progress"
    assert _h1(client.get(f"/games/{game_id}/state").json())["chips"] == chips_before


def test_invalid_game_mode_rejected():
    r = client.post("/games", json=dict(SETTINGS, game_mode="turbo"))
    assert r.status_code == 422


def test_expert_difficulty_is_rejected():
    # Expert was retired as a user-selectable difficulty (it was statistically
    # co-equal with Hard); only easy/normal/hard are accepted now.
    r = client.post("/games", json=dict(SETTINGS, difficulty="expert"))
    assert r.status_code == 422


def test_cash_mode_no_blind_escalation():
    # hands_per_level=1 would escalate every hand in tournament mode; cash must not.
    settings = dict(SETTINGS, game_mode="cash", hands_per_level=1)
    r = client.post("/games", json=settings)
    assert r.status_code == 201
    body = r.json()
    game_id = body["game_id"]
    assert body["view"]["game_mode"] == "cash"
    assert body["view"]["blinds"]["hands_to_level"] is None

    hands = 0
    while hands < 3:
        r = client.post(f"/games/{game_id}/hands")
        if r.status_code == 409:
            reason = r.json().get("reason")
            if reason == "busted":
                assert client.post(f"/games/{game_id}/topup").status_code == 200
                continue
            break  # game_over: blinds assertion below still holds
        assert r.status_code == 200, r.text
        view = r.json()["view"]
        guard = 0
        while view["you"] and view["you"]["to_act"]:
            guard += 1
            assert guard < 50, "runaway action loop"
            legal = view["you"]["action_request"]["legal_actions"]
            action = "check" if "check" in legal else "call"
            view = client.post(f"/games/{game_id}/action",
                               json={"action": action}).json()["view"]
        hands += 1

    assert hands >= 1
    state = client.get(f"/games/{game_id}/state").json()
    assert state["blinds"]["big"] == SETTINGS["big_blind"]
    assert state["blinds"]["small"] == SETTINGS["big_blind"] // 2


def test_cash_mode_busted_bot_rebuys():
    # Cash keeps the table full: a busted bot buys back in on the next hand.
    game_id = client.post("/games", json=dict(SETTINGS, game_mode="cash", num_bots=3))\
        .json()["game_id"]
    session = client.app.state.manager.get(game_id)
    bot = next(p for p in session.game.players if p.player_id != "h1")
    bot.chips = 0
    session.start_next_hand()
    # Rebought and back in play (chips may be down a blind from the new hand).
    assert bot.chips > 0
    assert session.game.stats[bot.player_id]["rebuys"] == 1


def test_tournament_mode_busted_bot_stays_out():
    # Tournament eliminates: a busted bot is not rebought.
    game_id = client.post("/games", json=dict(SETTINGS, game_mode="tournament", num_bots=3))\
        .json()["game_id"]
    session = client.app.state.manager.get(game_id)
    bot = next(p for p in session.game.players if p.player_id != "h1")
    bot.chips = 0
    session.start_next_hand()
    assert bot.chips == 0


# ── Simulation jobs (M4) ──────────────────────────────────────────────────────

_STOPPED_RESULT = {
    "ranked": [], "per_table_nets": {}, "convergence_snapshots": {},
    "street_totals": {}, "street_hands": {}, "elapsed": 0.0, "stopped": True,
}


def _patch_sim_stats_file(monkeypatch, tmp_path):
    sim_file = tmp_path / "simulation_stats.json"
    monkeypatch.setattr("api.simulations.SimulationStatsManager",
                        functools.partial(SimulationStatsManager, stats_file=sim_file))
    return sim_file


def _wait_until_idle(timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get("/simulations/current").json()
        if job["status"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("simulation job did not settle in time")


def test_simulation_runs_to_completion(monkeypatch, tmp_path):
    sim_file = _patch_sim_stats_file(monkeypatch, tmp_path)
    r = client.post("/simulations",
                    json={"type": "all_vs_all", "num_tables": 2, "hands_per_table": 20})
    assert r.status_code == 201
    assert r.json()["status"] == "running"

    job = _wait_until_idle()
    assert job["status"] == "done"
    assert job["done"] == job["total"] == 2

    res = client.get("/simulations/current/result").json()
    assert res["status"] == "done"
    assert len(res["result"]["ranked"]) == 8
    # JSON-safe: the (name, data) tuples came back as arrays.
    assert isinstance(res["result"]["ranked"][0], list)

    saved = SimulationStatsManager(stats_file=sim_file).get_data()
    assert len(saved["sessions"]) == 1


def test_simulation_second_post_returns_409_busy(monkeypatch):
    gate = threading.Event()

    def blocked(*a, progress=None, should_stop=None, **k):
        if progress:
            progress(0, 1)
        gate.wait(10)
        return dict(_STOPPED_RESULT)

    monkeypatch.setattr("api.simulations.benchmark.run_all_vs_all", blocked)

    r = client.post("/simulations",
                    json={"type": "all_vs_all", "num_tables": 2, "hands_per_table": 20})
    assert r.status_code == 201
    try:
        r2 = client.post("/simulations",
                         json={"type": "all_vs_all", "num_tables": 2, "hands_per_table": 20})
        assert r2.status_code == 409
        assert r2.json()["reason"] == "busy"
    finally:
        gate.set()
        _wait_until_idle()


def test_simulation_cancel_yields_partial(monkeypatch):
    def cancellable(*a, progress=None, should_stop=None, **k):
        if progress:
            progress(0, 5)
        while not (should_stop and should_stop()):
            time.sleep(0.01)
        return dict(_STOPPED_RESULT)

    monkeypatch.setattr("api.simulations.benchmark.run_all_vs_all", cancellable)

    assert client.post("/simulations",
                       json={"type": "all_vs_all", "num_tables": 5, "hands_per_table": 20}
                       ).status_code == 201
    assert client.post("/simulations/current/cancel").status_code == 200

    job = _wait_until_idle()
    assert job["status"] == "cancelled"
    res = client.get("/simulations/current/result").json()
    assert res["status"] == "cancelled"
    assert res["result"]["stopped"] is True


def test_simulation_rejects_bad_difficulty():
    r = client.post("/simulations",
                    json={"type": "all_vs_all", "num_tables": 2, "hands_per_table": 20,
                          "difficulty": 0.5})
    assert r.status_code == 422


def test_simulation_rejects_expert_label():
    # Expert (0.9) is no longer a selectable benchmark difficulty.
    r = client.post("/simulations",
                    json={"type": "all_vs_all", "num_tables": 2, "hands_per_table": 20,
                          "difficulty": "expert"})
    assert r.status_code == 422


def test_simulation_param_sweep_requires_param_name():
    r = client.post("/simulations",
                    json={"type": "param_sweep", "num_tables": 2, "hands_per_table": 20})
    assert r.status_code == 422


def test_topup_then_hand_conserves_chips():
    game_id = _create()["game_id"]
    assert client.post(f"/games/{game_id}/topup").status_code == 200
    view = _play_hand_always_call(game_id)
    assert view["state"] == "WAITING"
    state = client.get(f"/games/{game_id}/state").json()
    # One top-up added starting_chips to the table's total.
    assert sum(p["chips"] for p in state["players"]) == TOTAL_CHIPS + SETTINGS["starting_chips"]
