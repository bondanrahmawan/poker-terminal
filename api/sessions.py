"""GameSession + in-memory SessionManager.

One GameSession owns a single-table Game with one AgentPlayer seat ("h1") plus
bots. All engine access is serialized by a per-session threading.Lock.
"""
import threading
import time
import uuid
from typing import Optional

from core.game import Game
from core.player import PlayerAction
from core.state import GameState
from core.stats_persistent import PersistentStatsManager
from players.agent import AgentPlayer
from players.roster import create_bots
from strategies.difficulty import EASY, NORMAL, HARD, EXPERT

HUMAN_ID = "h1"
_DIFFICULTY = {"easy": EASY, "normal": NORMAL, "hard": HARD, "expert": EXPERT}


class BustedError(Exception):
    """Human is out of chips and did not request a rebuy."""


class GameOverError(Exception):
    """Only one funded player remains."""

    def __init__(self, winner: Optional[str]):
        self.winner = winner


class HandInProgressError(Exception):
    """A hand is already awaiting the human's action."""


class GameSession:
    """One table. Owns a Game, a threading.Lock, and WebSocket connections."""

    def __init__(self, session_id: str, settings: dict):
        self.session_id = session_id
        self.settings = settings
        self.lock = threading.Lock()
        self.last_touched = time.time()
        self.ws_connections = []          # active WebSocket connections
        self._broadcast_cursor = -1       # last event seq pushed to WS clients
        self._persisted = False           # tournament-history write done (once)

        difficulty = _DIFFICULTY.get(settings.get("difficulty", "normal"), NORMAL)
        self.game = Game(
            big_blind=settings["big_blind"],
            hands_per_level=settings.get("hands_per_level", 10),
            ante=settings.get("enable_ante", False),
            live_output=False,
            game_mode=settings.get("game_mode", "tournament"),
            short_deck=settings.get("short_deck", False),
            seed=settings.get("seed"),
        )
        self.game.add_player(
            AgentPlayer(HUMAN_ID, settings.get("player_name", "Player"),
                        settings["starting_chips"]))
        for bot in create_bots(
            settings.get("num_bots", 3), settings["starting_chips"],
            difficulty=difficulty, shuffled=settings.get("shuffle_bots", False),
        ):
            self.game.add_player(bot)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _human(self):
        return next(p for p in self.game.players if p.player_id == HUMAN_ID)

    def touch(self):
        self.last_touched = time.time()

    def view(self) -> dict:
        return self.game.view_for(HUMAN_ID)

    def events(self, since: int = -1) -> list:
        return self.game.events_for(HUMAN_ID, since)

    def drain_new_events(self) -> list:
        """Events emitted since the last WS broadcast; advances the cursor."""
        evs = self.game.events_for(HUMAN_ID, self._broadcast_cursor)
        if evs:
            self._broadcast_cursor = evs[-1]["seq"]
        return evs

    def stats(self) -> dict:
        # Drop cumulative_net: it only accumulates across simulation session
        # resets (always 0 in single-session play) and the client never shows it.
        projected = {
            pid: {k: v for k, v in s.items() if k != "cumulative_net"}
            for pid, s in self.game.stats.items()
        }
        return {"stats": projected, "hand_count": self.game.hand_count}

    # ── engine operations (call under self.lock) ──────────────────────────────

    def start_next_hand(self, rebuy: bool = False) -> None:
        human = self._human()
        starting = self.settings["starting_chips"]
        if human.chips == 0:
            if not rebuy:
                raise BustedError()
            human.chips = starting
            self.game.stats[human.player_id]["total_invested"] += starting
            self.game.stats[human.player_id]["rebuys"] += 1

        active = [p for p in self.game.players if p.chips > 0]
        if len(active) <= 1:
            self.persist()
            raise GameOverError(active[0].name if active else None)

        if self.game.pending_request is not None:
            raise HandInProgressError()

        self.game.start_hand()

    def topup(self) -> None:
        """Add starting_chips to the human stack. Only between hands."""
        if self.game.pending_request is not None or self.game.state != GameState.WAITING:
            raise HandInProgressError()
        human = self._human()
        amount = self.settings["starting_chips"]
        human.chips += amount
        # Counts as invested money (so net stays honest) but is NOT a rebuy —
        # rebuys mean "busted and bought back in", which top-ups are not.
        self.game.stats[human.player_id]["total_invested"] += amount
        self.game.stats[human.player_id]["topups"] += 1

    def submit(self, action_str: str, amount: int = 0) -> None:
        action = PlayerAction(action_str)   # ValueError on unknown action string
        self.game.submit_action(HUMAN_ID, action, amount)

    def persist(self) -> None:
        """Append this table's final stats to the persistent tournament history,
        matching main.py's save_session shape. Runs at most once, and never for a
        game that dealt no hands. Call under self.lock."""
        if self._persisted or self.game.hand_count == 0:
            return
        self._persisted = True

        difficulty = _DIFFICULTY.get(self.settings.get("difficulty", "normal"), NORMAL)
        game_stats = {"hand_count": self.game.hand_count}
        for p in self.game.players:
            game_stats[p.player_id] = self.game.stats[p.player_id]

        pm = PersistentStatsManager()
        session_id = len(pm.get_session_history()) + 1
        pm.save_session(
            session_id=session_id,
            difficulty=difficulty,
            players=self.game.players,
            game_stats=game_stats,
            game_mode=self.settings.get("game_mode", "tournament"),
        )


class CapacityError(Exception):
    """The server is holding the maximum number of concurrent sessions."""


class SessionManager:
    """In-memory registry of GameSessions with an idle-TTL sweep."""

    def __init__(self, ttl_seconds: int = 2 * 3600, max_sessions: int = 100):
        self._sessions = {}
        self._ttl = ttl_seconds
        self._max = max_sessions
        self._lock = threading.Lock()

    def create(self, settings: dict) -> GameSession:
        # Bound memory: since the launcher can expose this publicly, refuse to let
        # unbounded /games calls spin up unlimited in-memory games.
        self._sweep()
        with self._lock:
            if len(self._sessions) >= self._max:
                raise CapacityError()
        sid = uuid.uuid4().hex
        session = GameSession(sid, settings)
        with self._lock:
            self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> Optional[GameSession]:
        self._sweep()
        return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _sweep(self) -> None:
        now = time.time()
        with self._lock:
            stale = [sid for sid, s in self._sessions.items()
                     if now - s.last_touched > self._ttl]
            for sid in stale:
                self._sessions.pop(sid, None)
