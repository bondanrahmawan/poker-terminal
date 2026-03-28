"""
Menu rendering for game setup and options.
Simplified version without StyledText accumulation issues.
"""
from typing import List, Dict, Optional
from ui.colors import Colors, ColorScheme


class MenuRenderer:
    """Renders interactive menus for game setup."""
    
    def __init__(self, scheme: Optional[ColorScheme] = None):
        self.scheme = scheme or ColorScheme.default()
    
    def _color(self, text: str, color: str) -> str:
        """Apply color to text."""
        return f"{color}{text}{Colors.RESET}"
    
    def render_logo(self) -> List[str]:
        """Render the game logo as ASCII art."""
        s = self.scheme
        
        return [
            "",
            self._color("  ██████╗  ██████╗  ██████╗ ████████╗███████╗ ██████╗ ", s.primary),
            self._color("  ██╔══██╗██╔═══██╗██╔════╝ ╚══██╔══╝██╔════╝██╔═══██╗", s.secondary),
            self._color("  ██████╔╝██║   ██║██║  ███╗   ██║   █████╗  ██║   ██║", s.accent),
            self._color("  ██╔══██╗██║   ██║██║   ██║   ██║   ██╔══╝  ██║   ██║", s.info),
            self._color("  ██████╔╝╚██████╔╝╚██████╔╝   ██║   ███████╗╚██████╔╝", s.success),
            self._color("  ╚═════╝  ╚═════╝  ╚═════╝    ╚═╝   ╚══════╝ ╚═════╝ ", s.highlight),
            "",
            self._color("       ♠  Terminal-Based Texas Hold'em Poker  ♥", s.dim_text),
            self._color("              ♦  Enhanced Edition  ♣", s.dim_text),
            "",
        ]
    
    def render_main_menu(self) -> List[str]:
        """Render the main menu options."""
        s = self.scheme
        tb = s.table_border
        
        return [
            "",
            self._color("  ╔══════════════════════════════════════════╗", tb),
            self._color("  ║           M A I N   M E N U              ║", s.highlight),
            self._color("  ╠══════════════════════════════════════════╣", tb),
            self._color("  ║                                          ║", tb),
            self._color("  ║    ", tb) + self._color("[1] Quick Start", s.primary) + self._color("                    ║", tb),
            self._color("  ║    ", tb) + self._color("[2] Custom Game", s.primary) + self._color("                      ║", tb),
            self._color("  ║    ", tb) + self._color("[3] Load Saved Game", s.primary) + self._color("              ║", tb),
            self._color("  ║    ", tb) + self._color("[4] Settings", s.primary) + self._color("                       ║", tb),
            self._color("  ║    ", tb) + self._color("[5] How to Play", s.primary) + self._color("                  ║", tb),
            self._color("  ║    ", tb) + self._color("[Q] Quit", s.error) + self._color("                            ║", tb),
            self._color("  ║                                          ║", tb),
            self._color("  ╚══════════════════════════════════════════╝", tb),
            "",
        ]
    
    def render_settings_menu(self, settings: Dict) -> List[str]:
        """Render the settings menu with current values."""
        s = self.scheme
        tb = s.table_border
        
        lines = [
            "",
            self._color("  ╔══════════════════════════════════════════╗", tb),
            self._color("  ║            S E T T I N G S               ║", s.highlight),
            self._color("  ╠══════════════════════════════════════════╣", tb),
            "",
        ]
        
        settings_list = [
            ("1", "Game Mode", settings.get('game_mode', 'tournament')),
            ("2", "Blind Level", str(settings.get('big_blind', 20))),
            ("3", "Hands Per Level", str(settings.get('hands_per_level', 5))),
            ("4", "Ante Enabled", "Yes" if settings.get('ante', False) else "No"),
            ("5", "Short Deck", "Yes" if settings.get('short_deck', False) else "No"),
            ("6", "Color Scheme", settings.get('color_scheme', 'default')),
            ("7", "Animations", "On" if settings.get('animations', True) else "Off"),
        ]
        
        for key, label, value in settings_list:
            line = self._color(f"  ", tb)
            line += self._color(f"[{key}] ", s.secondary)
            line += self._color(f"{label:<20}", s.info)
            line += self._color(f": ", s.dim_text)
            line += self._color(f"{value}", s.success)
            lines.append(line)
        
        lines.append("")
        lines.append(self._color("  ╠══════════════════════════════════════════╣", tb))
        lines.append(self._color("  ║    ", tb) + self._color("[S] Save Settings", s.primary) + self._color("              ║", tb))
        lines.append(self._color("  ║    ", tb) + self._color("[B] Back", s.warning) + self._color("                        ║", tb))
        lines.append(self._color("  ╚══════════════════════════════════════════╝", tb))
        lines.append("")
        
        return lines
    
    def render_game_mode_select(self) -> List[str]:
        """Render game mode selection."""
        s = self.scheme
        tb = s.table_border
        
        return [
            "",
            self._color("  ╔══════════════════════════════════════════╗", tb),
            self._color("  ║         S E L E C T   G A M E   M O D E  ║", s.highlight),
            self._color("  ╠══════════════════════════════════════════╣", tb),
            "",
            self._color("  ║    ", tb) + self._color("[1] Tournament", s.primary) + self._color("                                     ║", tb),
            self._color("  ║        Escalating blinds, last player wins", s.dim_text) + self._color("   ║", tb),
            "",
            self._color("  ║    ", tb) + self._color("[2] Cash Game", s.primary) + self._color("                                      ║", tb),
            self._color("  ║        Fixed blinds, rebuy anytime", s.dim_text) + self._color("          ║", tb),
            "",
            self._color("  ║    ", tb) + self._color("[3] Spectator Mode", s.primary) + self._color("                           ║", tb),
            self._color("  ║        Watch bots play each other", s.dim_text) + self._color("            ║", tb),
            "",
            self._color("  ╠══════════════════════════════════════════╣", tb),
            self._color("  ║    ", tb) + self._color("[B] Back", s.warning) + self._color("                        ║", tb),
            self._color("  ╚══════════════════════════════════════════╝", tb),
            "",
        ]
    
    def render_bot_selection(self, available_bots: List[Dict]) -> List[str]:
        """Render bot selection for adding AI players."""
        s = self.scheme
        tb = s.table_border
        
        lines = [
            "",
            self._color("  ╔══════════════════════════════════════════╗", tb),
            self._color("  ║       S E L E C T   B O T   P L A Y E R  ║", s.highlight),
            self._color("  ╠══════════════════════════════════════════╣", tb),
            "",
        ]
        
        for i, bot in enumerate(available_bots[:7]):
            name = bot.get('name', 'Unknown')
            style = bot.get('style', 'balanced')
            diff = bot.get('difficulty', 'medium')
            
            line = self._color(f"  ║    ", tb)
            line += self._color(f"[{i+1}] ", s.secondary)
            line += self._color(f"{name:<15}", s.primary)
            line += self._color(f" [{style}, {diff}]", s.dim_text)
            line += self._color(" ║", tb)
            lines.append(line)
        
        lines.append("")
        lines.append(self._color("  ╠══════════════════════════════════════════╣", tb))
        lines.append(self._color("  ║    ", tb) + self._color("[A] Add All Bots", s.primary) + self._color("                  ║", tb))
        lines.append(self._color("  ║    ", tb) + self._color("[B] Back", s.warning) + self._color("                        ║", tb))
        lines.append(self._color("  ╚══════════════════════════════════════════╝", tb))
        lines.append("")
        
        return lines
    
    def render_help(self) -> List[str]:
        """Render help/how to play screen."""
        s = self.scheme
        tb = s.table_border
        
        lines = [
            "",
            self._color("  ╔══════════════════════════════════════════╗", tb),
            self._color("  ║          H O W   T O   P L A Y           ║", s.highlight),
            self._color("  ╠══════════════════════════════════════════╣", tb),
            "",
            self._color("  ║  POKER HAND RANKINGS (best to worst):   ║", s.info),
            self._color("  ║                                          ║", tb),
            self._color("  ║    1. Royal Flush    - A K Q J T same suit", s.secondary) + self._color("  ║", tb),
            self._color("  ║    2. Straight Flush - 5 consecutive same suit", s.secondary) + self._color("  ║", tb),
            self._color("  ║    3. Four of a Kind - 4 cards same rank", s.secondary) + self._color("  ║", tb),
            self._color("  ║    4. Full House     - 3 of a kind + pair", s.secondary) + self._color("  ║", tb),
            self._color("  ║    5. Flush          - 5 cards same suit", s.secondary) + self._color("  ║", tb),
            self._color("  ║    6. Straight       - 5 consecutive cards", s.secondary) + self._color("  ║", tb),
            self._color("  ║    7. Three of a Kind - 3 cards same rank", s.secondary) + self._color("  ║", tb),
            self._color("  ║    8. Two Pair       - 2 different pairs", s.secondary) + self._color("  ║", tb),
            self._color("  ║    9. One Pair       - 2 cards same rank", s.secondary) + self._color("  ║", tb),
            self._color("  ║    10. High Card     - Highest card wins", s.secondary) + self._color("  ║", tb),
            "",
            self._color("  ║  GAME ACTIONS:                            ║", s.info),
            self._color("  ║    - Check: Pass action (if no bet)       ║", s.dim_text),
            self._color("  ║    - Call: Match current bet              ║", s.dim_text),
            self._color("  ║    - Bet/Raise: Put chips in              ║", s.dim_text),
            self._color("  ║    - Fold: Give up your hand              ║", s.dim_text),
            self._color("  ║    - All-in: Bet all your chips           ║", s.dim_text),
            "",
            self._color("  ╠══════════════════════════════════════════╣", tb),
            self._color("  ║    ", tb) + self._color("[B] Back", s.warning) + self._color("                        ║", tb),
            self._color("  ╚══════════════════════════════════════════╝", tb),
            "",
        ]
        
        return lines
    
    def render_prompt(self, message: str, default: str = "") -> str:
        """Render an input prompt."""
        s = self.scheme
        
        prompt = self._color("  → ", s.accent)
        prompt += self._color(message, s.info)
        if default:
            prompt += self._color(f" [{default}]: ", s.dim_text)
        else:
            prompt += self._color(": ", s.dim_text)
        
        return prompt
    
    def render_message(self, message: str, style: str = 'info') -> List[str]:
        """Render a message with styling."""
        s = self.scheme
        tb = s.table_border
        
        color_map = {
            'info': s.info,
            'success': s.success,
            'warning': s.warning,
            'error': s.error,
        }
        color = color_map.get(style, s.info)
        
        msg_width = 40
        padding = (msg_width - len(message)) // 2
        
        lines = [
            "",
            self._color("  ╔══════════════════════════════════════════╗", tb),
        ]
        
        msg_line = self._color("  ║", tb)
        msg_line += " " * padding
        msg_line += self._color(message, color)
        msg_line += " " * (msg_width - padding - len(message))
        msg_line += self._color("║", tb)
        lines.append(msg_line)
        
        lines.append(self._color("  ╚══════════════════════════════════════════╝", tb))
        lines.append("")
        
        return lines
