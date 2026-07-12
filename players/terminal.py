from typing import Tuple
from core.player import Player, PlayerAction
from core.card import Suit

_RED   = '\033[91m'
_RESET = '\033[0m'


def _fmt_cards(cards) -> str:
    parts = []
    for c in cards:
        s = repr(c)
        if c.suit in (Suit.HEARTS, Suit.DIAMONDS):
            parts.append(f"{_RED}{s}{_RESET}")
        else:
            parts.append(s)
    return '[' + ', '.join(parts) + ']'


class TerminalPlayer(Player):
    def __init__(self, player_id: str, name: str, starting_chips: int):
        super().__init__(player_id, name, starting_chips)
        self._last_event_seq = -1  # Cursor into game.events

    def _format_event(self, e) -> str:
        """Render a single event as a one-line summary, or '' to skip it."""
        d = e.data
        if e.type == 'hand_started':
            return f"  --- NEW HAND #{d['hand_number']} ---"
        if e.type == 'blind_posted':
            return f"  {d['name']} posts {d['kind']} blind: {d['amount']}    Pot: {d['pot']}"
        if e.type == 'street_started':
            cards = ' '.join(c['display'] for c in d.get('cards_dealt', []))
            return f"  --- {d['street'].upper()} ---  {cards}".rstrip()
        if e.type == 'action_taken':
            tag = "  (ALL-IN)" if d.get('all_in') else ""
            return f"  {d['name']} {d['action']} {d['amount']}    Pot: {d['pot']}{tag}"
        if e.type == 'hole_cards_shown':
            cards = ' '.join(c['display'] for c in d['cards'])
            return f"  {d['name']} shows {cards}  ({d['hand_name']})"
        if e.type == 'pot_awarded':
            return f"  {d['name']} wins {d['amount']}"
        return ""

    def _show_recent_events(self, events: list):
        """Show what happened since this player's last prompt, from the event stream."""
        new_events = [e for e in events if e.seq > self._last_event_seq]
        if new_events:
            lines = [line for line in (self._format_event(e) for e in new_events) if line]
            if lines:
                print(f"\n{'─' * 50}")
                for line in lines:
                    print(line)
                print(f"{'─' * 50}")
            self._last_event_seq = events[-1].seq

    def get_action(self, game_state: dict) -> Tuple[PlayerAction, int]:
        min_call        = game_state.get('min_call', 0)
        min_raise       = game_state.get('min_raise', 0)
        pot_size        = game_state.get('pot_size', 0)
        community_cards = game_state.get('community_cards', [])
        hand_log        = game_state.get('hand_log', [])
        player_role     = game_state.get('player_role', '')

        # Show opponent actions since last turn
        self._show_recent_events(game_state.get('events', []))

        # ── Info header ──────────────────────────────────────────────────────
        print("\n" + "=" * 50)
        pos_str = f"  Position : {player_role}" if player_role else ""
        print(f"Player: {self.name} | Chips: {self.chips}{pos_str}")
        print(f"Hole Cards: {_fmt_cards(self.hole_cards)}")
        if community_cards:
            print(f"Community:  {_fmt_cards(community_cards)}")
        print(f"Pot Size:   {pot_size}")
        if min_call > 0:
            total = pot_size + min_call
            pct   = (min_call / total * 100) if total > 0 else 0
            ratio = round(pot_size / min_call, 1)
            print(f"To Call:    {min_call}  (Pot odds: {ratio}:1 = {pct:.1f}%)")
        else:
            print(f"To Call:    0")
        # Always show min raise so player can plan
        min_total = min_raise + min_call
        print(f"Min Raise:  {min(self.chips, min_total)}")
        print("=" * 50)

        # Pre-compute bet shortcuts
        min_raise_total = min(self.chips, min_raise + min_call)
        # A pot-sized raise = call the outstanding bet, then raise by the
        # resulting pot; a half-pot raise by half of it.
        half_pot  = max(min_raise_total, min_call + (pot_size + min_call) // 2)
        full_pot  = max(min_raise_total, min_call + (pot_size + min_call))
        shortcuts = {
            'min':  min_raise_total,
            'half': min(self.chips, half_pot),
            'pot':  min(self.chips, full_pot),
        }

        while True:
            if min_call == 0:
                print("Options: (c)heck, (b)et, (f)old, (a)ll-in, (s)tatus, (h)istory")
            else:
                print(f"Options: (c)all {min_call}, (r)aise, (f)old, (a)ll-in, (s)tatus, (h)istory")

            choice = input(f"{self.name}, your action: ").strip().lower()

            if choice in ['s', 'status']:
                print("\n--- Player Status ---")
                players_info = game_state.get('players_info', [])
                for p_name, p_chips, p_active in sorted(players_info, key=lambda p: p[1], reverse=True):
                    if p_chips == 0 and p_active:
                        status_str = "All-In"
                    elif p_chips == 0:
                        status_str = "Out"
                    elif not p_active:
                        status_str = "Folded"
                    else:
                        status_str = "Active"
                    print(f"  {p_name:<15} | Chips: {p_chips:<6} | {status_str}")
                print("---------------------\n")
                continue

            if choice in ['h', 'history']:
                print("\n--- Hand History ---")
                for line in hand_log:
                    print(line)
                print("--------------------\n")
                continue

            if choice in ['f', 'fold']:
                return PlayerAction.FOLD, 0

            elif choice in ['c', 'check', 'call']:
                if min_call == 0:
                    return PlayerAction.CHECK, 0
                call_amt = min(self.chips, min_call)
                if call_amt == self.chips:
                    return PlayerAction.ALL_IN, call_amt
                return PlayerAction.CALL, call_amt

            elif choice in ['b', 'r', 'bet', 'raise']:
                print(f"  Shortcuts: min={shortcuts['min']}, half={shortcuts['half']}, pot={shortcuts['pot']}")
                print(f"  (Type 'cancel' to go back)")
                while True:
                    raw = input(f"  Amount (min {min_raise_total}, or min/half/pot, cancel): ").strip().lower()
                    
                    # Allow cancel to return to main menu
                    if raw in ['cancel', 'esc', 'x']:
                        print("  Raise cancelled.")
                        break
                    
                    if raw in shortcuts:
                        amt = shortcuts[raw]
                    elif raw.isdigit():
                        amt = int(raw)
                    else:
                        print("  Enter a number, min/half/pot, or 'cancel' to go back.")
                        continue
                    if amt >= min_raise_total and amt <= self.chips:
                        if amt == self.chips:
                            return PlayerAction.ALL_IN, amt
                        return PlayerAction.RAISE, amt
                    else:
                        print(f"  Must be between {min_raise_total} and {self.chips}.")

            elif choice in ['a', 'all-in', 'allin']:
                confirm = input(f"  All-in for {self.chips} chips? (y/n): ").strip().lower()
                if confirm in ['y', 'yes']:
                    return PlayerAction.ALL_IN, self.chips
                print("  All-in cancelled.")

            else:
                print("Invalid choice. Try again.")
