"""FastAPI app for the poker engine. Run with: python -m api.server

Nothing in core/ or players/ is imported for mutation here — the transport is a
thin shell around the Phase 2/3 engine API (start_hand / submit_action / view_for).
"""
import asyncio
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from core.errors import IllegalActionError
from core.stats_persistent import PersistentStatsManager
from core.simulation_stats import SimulationStatsManager
from api.schemas import CreateGameRequest, StartHandRequest, ActionRequestBody
from api.sessions import (
    SessionManager, GameSession, CapacityError,
    BustedError, GameOverError, HandInProgressError,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Poker Terminal API")
    manager = SessionManager()
    app.state.manager = manager

    def _get(session_id: str) -> GameSession:
        session = manager.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Game not found")
        return session

    async def _broadcast(session: GameSession) -> None:
        """Push new events + the fresh view to this session's WS connections."""
        with session.lock:
            events = session.drain_new_events()
            view = session.view()
        dead = []
        for ws in list(session.ws_connections):
            try:
                if events:
                    await ws.send_json({"type": "events", "events": events})
                await ws.send_json({"type": "view", "view": view})
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in session.ws_connections:
                session.ws_connections.remove(ws)

    # ── REST ──────────────────────────────────────────────────────────────────

    @app.post("/games", status_code=201)
    async def create_game(body: CreateGameRequest):
        try:
            session = manager.create(body.model_dump())
        except CapacityError:
            raise HTTPException(status_code=503, detail="Server at capacity")
        return {"game_id": session.session_id, "view": session.view()}

    @app.post("/games/{game_id}/hands")
    async def start_hand(game_id: str, body: Optional[StartHandRequest] = None):
        session = _get(game_id)
        rebuy = body.rebuy if body else False

        def op():
            with session.lock:
                session.touch()
                try:
                    session.start_next_hand(rebuy=rebuy)
                except BustedError:
                    return ("busted", None)
                except GameOverError as e:
                    return ("game_over", e.winner)
                except HandInProgressError:
                    return ("in_progress", None)
                return ("ok", session.view())

        status, payload = await asyncio.to_thread(op)
        if status == "busted":
            return JSONResponse(status_code=409, content={"reason": "busted"})
        if status == "game_over":
            return JSONResponse(status_code=409,
                                content={"reason": "game_over", "winner": payload})
        if status == "in_progress":
            return JSONResponse(status_code=409,
                                content={"reason": "hand_in_progress"})
        await _broadcast(session)
        return {"view": payload}

    @app.get("/games/{game_id}/state")
    async def get_state(game_id: str):
        session = _get(game_id)
        with session.lock:
            session.touch()
            return session.view()

    @app.get("/games/{game_id}/events")
    async def get_events(game_id: str, since: int = Query(-1)):
        session = _get(game_id)
        with session.lock:
            session.touch()
            return {"events": session.events(since)}

    @app.post("/games/{game_id}/action")
    async def post_action(game_id: str, body: ActionRequestBody):
        session = _get(game_id)

        def op():
            with session.lock:
                session.touch()
                if session.game.pending_request is None:
                    return ("no_pending", None)
                try:
                    session.submit(body.action, body.amount)
                except ValueError as e:
                    return ("bad_action", str(e))
                except IllegalActionError as e:
                    return ("illegal", str(e))
                return ("ok", session.view())

        status, payload = await asyncio.to_thread(op)
        if status == "no_pending":
            return JSONResponse(status_code=409,
                                content={"reason": "no_pending_action"})
        if status in ("bad_action", "illegal"):
            raise HTTPException(status_code=422, detail=payload)
        await _broadcast(session)
        return {"view": payload}

    @app.post("/games/{game_id}/topup")
    async def topup(game_id: str):
        session = _get(game_id)

        def op():
            with session.lock:
                session.touch()
                try:
                    session.topup()
                except HandInProgressError:
                    return ("in_progress", None)
                return ("ok", session.view())

        status, payload = await asyncio.to_thread(op)
        if status == "in_progress":
            return JSONResponse(status_code=409,
                                content={"reason": "hand_in_progress"})
        await _broadcast(session)
        return {"view": payload}

    @app.get("/games/{game_id}/stats")
    async def get_stats(game_id: str):
        session = _get(game_id)
        with session.lock:
            session.touch()
            return session.stats()

    @app.delete("/games/{game_id}", status_code=204)
    async def delete_game(game_id: str):
        session = _get(game_id)
        with session.lock:
            session.persist()  # preserve the session in tournament history before it's gone
        manager.remove(game_id)
        return Response(status_code=204)

    # ── Tournament stats (read-only) ──────────────────────────────────────────
    # Thin wrappers over PersistentStatsManager getters. The manager is a cheap
    # file read, so construct one per request (no caching). Static paths, so they
    # sit above the "/" mount like every other route and never collide with
    # /games/{id}.

    @app.get("/stats/tournament/players")
    async def stats_players(difficulty: Optional[str] = Query(None)):
        return PersistentStatsManager().get_all_players_by_difficulty(difficulty)

    @app.get("/stats/tournament/players/{player_id}")
    async def stats_player_history(player_id: str, difficulty: Optional[str] = Query(None)):
        return PersistentStatsManager().get_player_history(player_id, difficulty)

    @app.get("/stats/tournament/sessions")
    async def stats_sessions(difficulty: Optional[str] = Query(None)):
        return PersistentStatsManager().get_session_history(difficulty)

    @app.get("/stats/simulation")
    async def stats_simulation():
        return SimulationStatsManager().get_data()

    # ── WebSocket ─────────────────────────────────────────────────────────────

    @app.websocket("/games/{game_id}/ws")
    async def ws_endpoint(ws: WebSocket, game_id: str):
        session = manager.get(game_id)
        if session is None:
            await ws.close(code=1008)
            return
        await ws.accept()
        session.ws_connections.append(ws)
        with session.lock:
            view = session.view()
        await ws.send_json({"type": "view", "view": view})
        try:
            while True:
                msg = await ws.receive_json()

                def op():
                    with session.lock:
                        session.touch()
                        if session.game.pending_request is None:
                            return ("no_pending", None)
                        try:
                            session.submit(msg.get("action"), msg.get("amount", 0))
                        except ValueError as e:
                            return ("bad_action", str(e))
                        except IllegalActionError as e:
                            return ("illegal", str(e))
                        return ("ok", None)

                status, payload = await asyncio.to_thread(op)
                if status == "ok":
                    await _broadcast(session)
                else:
                    await ws.send_json({"type": "error", "reason": status,
                                        "detail": payload})
        except WebSocketDisconnect:
            if ws in session.ws_connections:
                session.ws_connections.remove(ws)

    # ── Static web client ─────────────────────────────────────────────────────
    # Mounted last so the API routes above take precedence; everything else
    # falls through to web/ (html=True serves index.html at "/").
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory="web", html=True), name="web")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
