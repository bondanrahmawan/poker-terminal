"""Per-viewer, JSON-safe snapshots of the game (Phase 3).

`build_view` filters hidden information per viewer: only the viewer's own hole
cards are ever included. Opponents' cards are revealed exclusively through
`hole_cards_shown` events at showdown, never in a view.
"""
from typing import Optional


def build_view(game, viewer_id: Optional[str]) -> dict:
    """Return a JSON-safe dict describing the game from `viewer_id`'s perspective.

    viewer_id=None is a spectator: no hole cards at all, `you` is null.
    """
    bs = game.blind_scheduler
    pending = game.pending_request

    # pot_manager.pots is empty mid-hand and only populated at showdown.
    pots = [{"amount": pot.amount, "eligible": sorted(pot.eligible_players)}
            for pot in game.pot_manager.pots]

    players = []
    for p in game.players:
        is_you = viewer_id is not None and p.player_id == viewer_id
        pd = {
            "player_id": p.player_id,
            "name": p.name,
            "chips": p.chips,
            "is_active": p.is_active,
            "is_all_in": p.is_all_in,
            "role": game.player_roles.get(p.player_id, ''),
            "bet_this_round": game.bet_manager.player_bets_this_round.get(p.player_id, 0),
            "invested_this_hand": game.pot_manager.contributions.get(p.player_id, 0),
            "is_you": is_you,
        }
        if is_you:
            # Never include another player's hole_cards — key omitted entirely so
            # leaks are grep-able in tests.
            pd["hole_cards"] = [c.to_dict() for c in p.hole_cards]
        players.append(pd)

    you = None
    if viewer_id is not None:
        to_act = pending is not None and pending.player_id == viewer_id
        you = {
            "player_id": viewer_id,
            "to_act": to_act,
            "action_request": pending.to_dict() if to_act else None,
        }

    return {
        "hand_number": game.hand_count,
        "state": game.state.value,
        "street": game.current_street,
        "community_cards": [c.to_dict() for c in game.community_cards],
        "pot": game.pot_manager.total_pot(),
        "pots": pots,
        "blinds": {"small": bs.small_blind, "big": game.big_blind,
                   "ante": bs.ante, "level": bs.current_level + 1},
        "dealer_player_id": (game.players[game.dealer_idx].player_id
                             if game.players else None),
        "game_mode": game.game_mode,
        "short_deck": game.short_deck,
        "players": players,
        "you": you,
        "last_event_seq": game._event_seq - 1,
    }


def events_for(game, viewer_id: Optional[str], since_seq: int = -1) -> list:
    """Serialized events after since_seq, with `hole_cards_dealt` filtered:
    included only when data['player_id'] == viewer_id."""
    out = []
    for e in game.events:
        if e.seq <= since_seq:
            continue
        if e.type == 'hole_cards_dealt' and e.data.get('player_id') != viewer_id:
            continue
        out.append(e.to_dict())
    return out
