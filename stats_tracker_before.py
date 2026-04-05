"""StatsTracker - Handles player statistics tracking and display."""

from typing import Dict, List, TYPE_CHECKING
import re

if TYPE_CHECKING:
    from core.player import Player


# Color codes for terminal output
_GREEN = '\033[92m'
_RED = '\033[91m'
_YELLOW = '\033[93m'
_CYAN = '\033[96m'
_MAGENTA = '\033[95m'
_BOLD = '\033[1m'
_DIM = '\033[2m'
_RESET = '\033[0m'


class StatsTracker:
    """Tracks and displays player statistics throughout the game session."""

    def __init__(self) -> None:
        self.stats: Dict[str, dict] = {}

    def register_player(self, player: 'Player') -> None:
        """Initialize stats tracking for a player."""
        self.stats[player.player_id] = {
            'hands_won': 0,
            'hands_played': 0,
            'chips_won': 0,
            'biggest_pot': 0,
            'best_hand_rank': 0,
            'best_hand_name': '-',
            'bust_hand': None,
            'rebuys': 0,
            'starting_chips': player.chips,
        }

    def increment_hands_played(self, player_id: str) -> None:
        """Increment hands played counter for a player."""
        if player_id in self.stats:
            self.stats[player_id]['hands_played'] += 1

    def record_win(self, player_id: str, amount: int) -> None:
        """Record a win for a player."""
        if player_id in self.stats:
            self.stats[player_id]['hands_won'] += 1
            self.stats[player_id]['chips_won'] += amount
            if amount > self.stats[player_id]['biggest_pot']:
                self.stats[player_id]['biggest_pot'] = amount

    def update_best_hand(self, player_id: str, rank: int, hand_name: str) -> None:
        """Update the best hand rank and name for a player."""
        if player_id in self.stats:
            if rank > self.stats[player_id]['best_hand_rank']:
                self.stats[player_id]['best_hand_rank'] = rank
                self.stats[player_id]['best_hand_name'] = hand_name

    def calculate_gini(self, players: List['Player']) -> float:
        """Calculate Gini Coefficient: 0 (equal) to 1 (one player has everything)."""
        chips = sorted([max(0, p.chips) for p in players])
        n = len(chips)
        if n == 0 or sum(chips) == 0:
            return 0.0
        
        # Simple Gini formula for discrete data
        # G = (2 * sum(i * x_i) / (n * sum(x_i))) - (n + 1) / n
        # where x is sorted non-decreasingly
        sum_chips = sum(chips)
        weighted_sum = sum((i + 1) * x for i, x in enumerate(chips))
        return (2.0 * weighted_sum) / (n * sum_chips) - (n + 1.0) / n

    def get_archetype_stats(self, players: List['Player']) -> Dict[str, dict]:
        """Aggregate stats by strategy profile name."""
        archetypes = {}
        for p in players:
            # Get the base strategy label (e.g., 'Balanced' from 'Balanced/0.8')
            full_label = self._strategy_label(p)
            label = full_label.split('/')[0] if '/' in full_label else full_label
            
            s = self.stats.get(p.player_id, {})
            
            if label not in archetypes:
                archetypes[label] = {'net': 0, 'count': 0, 'played': 0, 'won': 0, 'survival': 0}
            
            archetypes[label]['net'] += (p.chips - s.get('starting_chips', 0))
            archetypes[label]['count'] += 1
            archetypes[label]['played'] += s.get('hands_played', 0)
            archetypes[label]['won'] += s.get('hands_won', 0)
            if p.chips > 0:
                archetypes[label]['survival'] += 1
                
        # Calculate rates
        for label in archetypes:
            archetypes[label]['survival_rate'] = (archetypes[label]['survival'] / archetypes[label]['count']) * 100
            
        return archetypes

    def record_bust(self, player_id: str, hand_number: int) -> None:
        """Record the hand number when a player busts."""
        if player_id in self.stats:
            if self.stats[player_id]['bust_hand'] is None:
                self.stats[player_id]['bust_hand'] = hand_number

    @staticmethod
    def _strategy_label(player: 'Player') -> str:
        """Return a short strategy description for display in stats."""
        strategy = getattr(player, 'strategy', None)
        if strategy is None:
            return 'human'
        profile = getattr(strategy, 'profile', None)
        diff = getattr(strategy, 'difficulty', None)
        if profile:
            diff_str = f"{diff:.1f}" if diff is not None else '?'
            return f"{profile.name}/{diff_str}"
        agg = getattr(strategy, 'aggressiveness', None)
        if agg is not None:
            return f"simple/{agg:.1f}"
        return strategy.__class__.__name__

    @staticmethod
    def _visual_len(s: str) -> int:
        """Get visual length of a string (strip ANSI codes)."""
        return len(re.sub(r'\033\[[0-9;]*m', '', s))

    @staticmethod
    def _visual_ljust(s: str, width: int) -> str:
        """Pad string to visual width (left-justified)."""
        vlen = len(re.sub(r'\033\[[0-9;]*m', '', s))
        return s + ' ' * max(0, width - vlen)

    @staticmethod
    def _visual_rjust(s: str, width: int) -> str:
        """Pad string to visual width (right-justified)."""
        vlen = len(re.sub(r'\033\[[0-9;]*m', '', s))
        return ' ' * max(0, width - vlen) + s

    def print_stats(self, players: List['Player']) -> None:
        """Print enhanced session statistics with visual formatting."""
        players_with_stats = [p for p in players if p.player_id in self.stats]

        # Header
        print()
        print(f"{_BOLD}{_CYAN}╔{'═' * 126}╗{_RESET}")
        print(f"{_BOLD}{_CYAN}║{_RESET}{_BOLD}{'SESSION STATISTICS':^126}{_RESET}{_BOLD}{_CYAN}║{_RESET}")
        print(f"{_BOLD}{_CYAN}╠{'═' * 126}╣{_RESET}")

        # Summary stats
        total_hands = sum(s['hands_played'] for s in self.stats.values())
        total_rebuys = sum(s.get('rebuys', 0) for s in self.stats.values())
        biggest_pot = max((s['biggest_pot'] for s in self.stats.values()), default=0)
        best_hand = max(self.stats.values(), key=lambda x: x['best_hand_rank']) if self.stats else {'best_hand_name': '-'}

        summary_line = (
            f"{_DIM}Total Hands:{_RESET} {_BOLD}{total_hands:>7}{_RESET}  "
            f"{_DIM}|{_RESET} {_DIM}Total Rebuys:{_RESET} {_YELLOW}{total_rebuys:>6}{_RESET}  "
            f"{_DIM}|{_RESET} {_DIM}Biggest Pot:{_RESET} {_GREEN}{biggest_pot:>9}{_RESET}  "
            f"{_DIM}|{_RESET} {_DIM}Best Hand:{_RESET} {_MAGENTA}{best_hand['best_hand_name']:<15}{_RESET}"
        )
        print(f"{_BOLD}{_CYAN}║{_RESET} {self._visual_ljust(summary_line, 124)} {_BOLD}{_CYAN}║{_RESET}")
        print(f"{_BOLD}{_CYAN}╠{'═' * 126}╣{_RESET}")

        # Table header
        header = (
            f" {self._visual_rjust(f'{_BOLD}#{_RESET}', 3)} "
            f"{self._visual_ljust(f'{_BOLD}Name{_RESET}', 12)} "
            f"{self._visual_ljust(f'{_BOLD}Strategy{_RESET}', 22)} "
            f"{self._visual_rjust(f'{_BOLD}Chips{_RESET}', 8)} "
            f"{self._visual_rjust(f'{_BOLD}Net{_RESET}', 8)} "
            f"{self._visual_rjust(f'{_BOLD}Played{_RESET}', 7)} "
            f"{self._visual_rjust(f'{_BOLD}Won{_RESET}', 6)} "
            f"{self._visual_rjust(f'{_BOLD}Win%{_RESET}', 7)} "
            f"{self._visual_rjust(f'{_BOLD}Rebuys{_RESET}', 6)} "
            f"{self._visual_rjust(f'{_BOLD}Big Pot{_RESET}', 9)} "
            f"{self._visual_ljust(f'{_BOLD}Best Hand{_RESET}', 15)} "
            f"{self._visual_ljust(f'{_BOLD}Status{_RESET}', 11)}"
        )
        print(f"{_BOLD}{_CYAN}║{_RESET}{header}{_BOLD}{_CYAN}║{_RESET}")
        print(f"{_BOLD}{_CYAN}╠{'═' * 126}╣{_RESET}")

        # Player rows - sorted by net profit
        sorted_players = sorted(
            players_with_stats,
            key=lambda p: p.chips - self.stats[p.player_id]['starting_chips'],
            reverse=True,
        )

        for rank, p in enumerate(sorted_players, 1):
            s = self.stats[p.player_id]
            net = p.chips - s['starting_chips']

            # Color coding for net
            if net > 0:
                net_str = f"{_GREEN}{net:>8}{_RESET}"
            elif net < 0:
                net_str = f"{_RED}{net:>8}{_RESET}"
            else:
                net_str = f"{_DIM}{0:>8}{_RESET}"

            # Win percentage
            played = s['hands_played']
            won = s['hands_won']
            if played > 0:
                win_pct = won / played * 100
                if win_pct >= 50:
                    win_pct_str = f"{_GREEN}{win_pct:>6.0f}%{_RESET}"
                elif win_pct >= 25:
                    win_pct_str = f"{_YELLOW}{win_pct:>6.0f}%{_RESET}"
                else:
                    win_pct_str = f"{_RED}{win_pct:>6.0f}%{_RESET}"
            else:
                win_pct_str = f"{_DIM}{'-':>7}{_RESET}"

            # Status with icon
            if p.chips > 0:
                status = f"{_GREEN}● Active{_RESET}"
            elif s['bust_hand']:
                status = f"{_RED}✕ Bust #{s['bust_hand']}{_RESET}"
            else:
                status = f"{_DIM}○ Out{_RESET}"

            # Rebuys highlight
            rebuys = s.get('rebuys', 0)
            if rebuys > 3:
                rebuys_str = f"{_RED}{rebuys:>6}{_RESET}"
            elif rebuys > 0:
                rebuys_str = f"{_YELLOW}{rebuys:>6}{_RESET}"
            else:
                rebuys_str = f"{_DIM}{rebuys:>6}{_RESET}"

            # Rank indicator
            if rank == 1:
                rank_str = f"{_YELLOW}{rank:>3}{_RESET}"
            elif rank == 2:
                rank_str = f"{_DIM}{rank:>3}{_RESET}"
            elif rank == 3:
                rank_str = f"{_MAGENTA}{rank:>3}{_RESET}"
            else:
                rank_str = f"{_DIM}{rank:>3}{_RESET}"

            strategy_str = self._strategy_label(p)

            # Build row with visual width alignment
            row = (
                f" {self._visual_rjust(rank_str, 3)} "
                f"{self._visual_ljust(p.name, 12)} "
                f"{self._visual_ljust(f'{_DIM}{strategy_str}{_RESET}', 22)} "
                f"{self._visual_rjust(f'{_BOLD}{p.chips}{_RESET}', 8)} "
                f"{self._visual_rjust(net_str, 8)} "
                f"{self._visual_rjust(f'{_DIM}{played}{_RESET}', 7)} "
                f"{self._visual_rjust(f'{_DIM}{won}{_RESET}', 6)} "
                f"{self._visual_rjust(win_pct_str, 7)} "
                f"{self._visual_rjust(rebuys_str, 6)} "
                f"{self._visual_rjust(f'{_DIM}{s["biggest_pot"]}{_RESET}', 9)} "
                f"{self._visual_ljust(f'{_MAGENTA}{s["best_hand_name"]}{_RESET}', 15)} "
                f"{self._visual_ljust(status, 11)}"
            )
            print(f"{_BOLD}{_CYAN}║{_RESET}{row}{_BOLD}{_CYAN}║{_RESET}")

        # Footer
        print(f"{_BOLD}{_CYAN}╚{'═' * 126}╝{_RESET}")

        # Top performers section
        print()
        print(f"{_BOLD}{_DIM}  ─── TOP PERFORMERS ───{_RESET}")

        # Best win rate (min 5 hands)
        eligible = [p for p in players_with_stats if self.stats[p.player_id]['hands_played'] >= 5]
        if eligible:
            best_wr = max(eligible, key=lambda p: self.stats[p.player_id]['hands_won'] / max(1, self.stats[p.player_id]['hands_played']))
            best_wr_pct = self.stats[best_wr.player_id]['hands_won'] / self.stats[best_wr.player_id]['hands_played'] * 100
            print(f"  {_DIM}Best Win Rate:{_RESET}  {_BOLD}{_GREEN}{best_wr.name}{_RESET} ({_YELLOW}{best_wr_pct:.0f}%{_RESET})")

        # Biggest pot winner
        if players_with_stats:
            biggest_winner = max(players_with_stats, key=lambda p: self.stats[p.player_id]['biggest_pot'])
            print(f"  {_DIM}Biggest Pot:{_RESET}  {_BOLD}{_GREEN}{biggest_winner.name}{_RESET} ({_YELLOW}{self.stats[biggest_winner.player_id]['biggest_pot']}{_RESET})")

            # Best hand
            best_hand_player = max(players_with_stats, key=lambda p: self.stats[p.player_id]['best_hand_rank'])
            print(f"  {_DIM}Best Hand:{_RESET}  {_BOLD}{_MAGENTA}{best_hand_player.name}{_RESET} ({_YELLOW}{self.stats[best_hand_player.player_id]['best_hand_name']}{_RESET})")

            # Most aggressive (most hands played)
            if eligible:
                most_active = max(eligible, key=lambda p: self.stats[p.player_id]['hands_played'])
                print(f"  {_DIM}Most Active:{_RESET}  {_BOLD}{_CYAN}{most_active.name}{_RESET} ({_YELLOW}{self.stats[most_active.player_id]['hands_played']} hands{_RESET})")

        print()
