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
        self._last_log_count = 0  # Track how many log entries we've seen

    def _show_recent_actions(self, hand_log: list):
        """Show opponent actions since last prompt."""
        new_entries = hand_log[self._last_log_count:]
        if new_entries:
            print(f"\n{'─' * 50}")
            for entry in new_entries:
                # Skip dealing messages and focus on actions
                entry_stripped = entry.strip()
                if any(keyword in entry_stripped.lower() for keyword in [
                    'fold', 'call', 'raise', 'check', 'all-in', 'bets',
                    'posts sb', 'posts bb', 'ante', 'wins',
                    '--- flop ---', '--- turn ---', '--- river ---',
                    '--- showdown ---', '--- new hand ---'
                ]):
                    print(f"  {entry_stripped}")
            print(f"{'─' * 50}")
            self._last_log_count = len(hand_log)

    def get_action(self, game_state: dict) -> Tuple[str, int]:
        min_call        = game_state.get('min_call', 0)
        min_raise       = game_state.get('min_raise', 0)
        pot_size        = game_state.get('pot_size', 0)
        community_cards = game_state.get('community_cards', [])
        hand_log        = game_state.get('hand_log', [])
        player_role     = game_state.get('player_role', '')

        # Show opponent actions since last turn
        self._show_recent_actions(hand_log)

        # Reset counter at start of new hand
        if any('--- NEW HAND ---' in entry for entry in hand_log[-5:]):
            self._last_log_count = 0
            self._show_recent_actions(hand_log)

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
        half_pot  = max(min_raise_total, (pot_size // 2) + min_call)
        full_pot  = max(min_raise_total, pot_size + min_call)
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
