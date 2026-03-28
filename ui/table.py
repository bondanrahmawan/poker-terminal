"""
Poker table renderer with player positions and community cards.
Simplified version without StyledText accumulation issues.
"""
from typing import List, Dict, Optional
import re
from core.card import Card as GameCard
from core.player import Player
from ui.colors import Colors, ColorScheme
from ui.cards import CardRenderer


class PokerTableRenderer:
    """Renders the full poker table with players, cards, and pot information."""
    
    def __init__(self, scheme: Optional[ColorScheme] = None):
        self.scheme = scheme or ColorScheme.default()
        self.card_renderer = CardRenderer()
    
    def render_table(self, players: List[Player], community_cards: List[GameCard],
                     pot_amount: int, dealer_idx: int, active_player_ids: List[str],
                     player_roles: Dict[str, str], current_bet: int = 0,
                     last_action: Optional[str] = None) -> str:
        """Render the complete poker table."""
        lines = []
        
        lines.extend(self._render_header(pot_amount, current_bet))
        lines.append("")
        lines.extend(self._render_table_body(
            players, community_cards, dealer_idx, 
            active_player_ids, player_roles, last_action
        ))
        lines.append("")
        lines.extend(self._render_footer())
        
        return "\n".join(lines)
    
    def _color(self, text: str, color: str) -> str:
        """Apply color to text."""
        return f"{color}{text}{Colors.RESET}"
    
    def _render_header(self, pot_amount: int, current_bet: int) -> List[str]:
        """Render table header with pot info."""
        s = self.scheme
        lines = []
        
        lines.append(f"{s.table_border}╔{'═' * 70}╕{Colors.RESET}")
        
        title = f"{s.primary}  ♠ {Colors.RESET}{s.highlight}POKER TERMINAL{Colors.RESET}{s.primary} ♥{Colors.RESET}"
        lines.append(self._center_line(title, 70))
        
        pot_line = f"{s.info}  Pot: {Colors.RESET}{s.chip_stack}{pot_amount:>6}{Colors.RESET}{s.dim_text}  |  {Colors.RESET}{s.info}To Call: {Colors.RESET}{s.warning}{current_bet:>6}{Colors.RESET}"
        lines.append(self._center_line(pot_line, 70))
        
        lines.append(f"{s.table_border}╚{'═' * 70}╝{Colors.RESET}")
        
        return lines
    
    def _render_table_body(self, players: List[Player], community_cards: List[GameCard],
                           dealer_idx: int, active_player_ids: List[str],
                           player_roles: Dict[str, str], 
                           last_action: Optional[str]) -> List[str]:
        """Render the main table area with players."""
        s = self.scheme
        lines = []
        n = len(players)
        
        if n <= 2:
            lines.extend(self._render_heads_up(players, community_cards, dealer_idx,
                                               active_player_ids, player_roles))
        elif n <= 4:
            lines.extend(self._render_short_table(players, community_cards, dealer_idx,
                                                  active_player_ids, player_roles))
        else:
            lines.extend(self._render_full_table(players, community_cards, dealer_idx,
                                                 active_player_ids, player_roles))
        
        if last_action:
            lines.append("")
            lines.append(f"{s.dim_text}  → {last_action}{Colors.RESET}")
        
        return lines
    
    def _render_heads_up(self, players: List[Player], community_cards: List[GameCard],
                         dealer_idx: int, active_player_ids: List[str],
                         player_roles: Dict[str, str]) -> List[str]:
        """Render 2-player table layout."""
        s = self.scheme
        lines = []
        
        lines.append("  " + "─" * 35)
        lines.append("  " + self.card_renderer.render_community(community_cards, self.scheme))
        lines.append("  " + "─" * 35)
        lines.append("")
        
        p1 = players[0]
        p1_role = player_roles.get(p1.player_id, '')
        is_dealer = 0 == dealer_idx
        lines.extend(self._render_player_seat(p1, p1_role, is_dealer, 
                                               p1.player_id in active_player_ids))
        
        lines.append("")
        lines.append(f"  {s.dim_text}▼{Colors.RESET}")
        lines.append("")
        
        p2 = players[1]
        p2_role = player_roles.get(p2.player_id, '')
        is_dealer = 1 == dealer_idx
        lines.extend(self._render_player_seat(p2, p2_role, is_dealer,
                                               p2.player_id in active_player_ids))
        
        return lines
    
    def _render_short_table(self, players: List[Player], community_cards: List[GameCard],
                            dealer_idx: int, active_player_ids: List[str],
                            player_roles: Dict[str, str]) -> List[str]:
        """Render 3-4 player table layout."""
        lines = []
        
        top_players = players[:2]
        top_line = "  "
        for i, p in enumerate(top_players):
            role = player_roles.get(p.player_id, '')
            is_dealer = i == dealer_idx
            seat = self._render_player_compact(p, role, is_dealer,
                                                p.player_id in active_player_ids)
            top_line += seat + "  "
        lines.append(top_line)
        
        lines.append("")
        lines.append("  " + "─" * 35)
        lines.append("  " + self.card_renderer.render_community(community_cards, self.scheme))
        lines.append("  " + "─" * 35)
        
        lines.append("")
        
        bottom_players = players[2:] if len(players) > 2 else []
        if bottom_players:
            bottom_line = "  "
            for i, p in enumerate(bottom_players):
                idx = players.index(p)
                role = player_roles.get(p.player_id, '')
                is_dealer = idx == dealer_idx
                seat = self._render_player_compact(p, role, is_dealer,
                                                    p.player_id in active_player_ids)
                bottom_line += seat + "  "
            lines.append(bottom_line)
        else:
            p = players[2] if len(players) > 2 else players[0]
            role = player_roles.get(p.player_id, '')
            is_dealer = players.index(p) == dealer_idx
            lines.append("  " + self._render_player_compact(p, role, is_dealer,
                                                             p.player_id in active_player_ids))
        
        return lines
    
    def _render_full_table(self, players: List[Player], community_cards: List[GameCard],
                           dealer_idx: int, active_player_ids: List[str],
                           player_roles: Dict[str, str]) -> List[str]:
        """Render 5+ player oval table layout."""
        s = self.scheme
        lines = []
        
        lines.append(f"  {s.table_border}╔{'═' * 56}╗{Colors.RESET}")
        
        top_players = players[:2]
        top_line = f"  {s.table_border}║{Colors.RESET}"
        for i, p in enumerate(top_players):
            role = player_roles.get(p.player_id, '')
            is_dealer = i == dealer_idx
            seat = self._render_player_compact(p, role, is_dealer,
                                                p.player_id in active_player_ids)
            top_line += seat + " "
        top_line += " " * max(0, 56 - len(top_players) * 18)
        top_line += f"{s.table_border}║{Colors.RESET}"
        lines.append(top_line)
        
        mid_line = f"  {s.table_border}║{Colors.RESET}"
        mid_line += " " * 8
        mid_line += self.card_renderer.render_community(community_cards, self.scheme)
        mid_line += " " * 8
        mid_line += f"{s.table_border}║{Colors.RESET}"
        lines.append(mid_line)
        
        lines.append(f"  {s.table_border}╚{'═' * 56}╝{Colors.RESET}")
        
        bottom_players = players[2:]
        if bottom_players:
            lines.append("")
            bottom_line = "  "
            for i, p in enumerate(bottom_players):
                idx = 2 + i
                role = player_roles.get(p.player_id, '')
                is_dealer = idx == dealer_idx
                seat = self._render_player_compact(p, role, is_dealer,
                                                    p.player_id in active_player_ids)
                bottom_line += seat + " "
            lines.append(bottom_line)
        
        return lines
    
    def _render_player_seat(self, player: Player, role: str, is_dealer: bool,
                            is_active: bool) -> List[str]:
        """Render a full player seat with cards."""
        s = self.scheme
        lines = []
        
        info = "  "
        if is_dealer:
            info += f"{s.accent}[D] {Colors.RESET}"
        info += f"{s.primary}{player.name:<12}{Colors.RESET}"
        info += f"{s.dim_text} ({role:>3}){Colors.RESET}"
        lines.append(info)
        
        if player.hole_cards and is_active:
            card_lines = self.card_renderer.render_hand(player.hole_cards, self.scheme)
            for card_line in card_lines:
                lines.append("  " + card_line)
        else:
            lines.append("  [ folded ]")
        
        chips = f"{s.info}  Chips: {Colors.RESET}{s.chip_stack}{player.chips:>6}{Colors.RESET}"
        lines.append(chips)
        
        return lines
    
    def _render_player_compact(self, player: Player, role: str, is_dealer: bool,
                                is_active: bool) -> str:
        """Render a compact player seat."""
        s = self.scheme
        
        info = ""
        if is_dealer:
            info += f"{s.accent}♦ {Colors.RESET}"
        info += f"{s.primary}{player.name[:10]:<10}{Colors.RESET}"
        info += f"{s.dim_text} {role:>2}{Colors.RESET}"
        info += " "
        info += f"{s.chip_stack}${player.chips:>5}{Colors.RESET}"
        
        if not is_active:
            info += f"{s.error} [FOLDED]{Colors.RESET}"
        
        return info
    
    def _center_line(self, text: str, width: int) -> str:
        """Center text within given width."""
        visible_len = len(re.sub(r'\033\[[0-9;]*m', '', text))
        padding = (width - visible_len) // 2
        return " " * padding + text
    
    def _render_footer(self) -> List[str]:
        """Render table footer with legend."""
        s = self.scheme
        lines = []
        
        lines.append(f"{s.dim_text}  {'─' * 50}{Colors.RESET}")
        legend = f"{s.info}  Legend: {Colors.RESET}{s.accent}[D]/♦ = Dealer  {Colors.RESET}{s.secondary}SB = Small Blind  {Colors.RESET}{s.secondary}BB = Big Blind{Colors.RESET}"
        lines.append(legend)
        
        return lines
