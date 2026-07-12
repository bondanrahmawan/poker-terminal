"""
Tests for the Phase 4 FastAPI transport (api/).
Run with: pytest tests/test_api.py -v
"""
import pytest
from fastapi.testclient import TestClient

from api.server import app
from api.sessions import SessionManager, CapacityError

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


def test_topup_then_hand_conserves_chips():
    game_id = _create()["game_id"]
    assert client.post(f"/games/{game_id}/topup").status_code == 200
    view = _play_hand_always_call(game_id)
    assert view["state"] == "WAITING"
    state = client.get(f"/games/{game_id}/state").json()
    # One top-up added starting_chips to the table's total.
    assert sum(p["chips"] for p in state["players"]) == TOTAL_CHIPS + SETTINGS["starting_chips"]
