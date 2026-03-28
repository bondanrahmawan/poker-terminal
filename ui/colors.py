"""
Color schemes and ANSI color utilities for terminal rendering.
Supports normal and color-blind friendly modes.
"""
from typing import Dict, Optional
from dataclasses import dataclass


class Colors:
    """ANSI color codes for terminal output."""
    
    # Basic colors
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    ITALIC = '\033[3m'
    UNDERLINE = '\033[4m'
    BLINK = '\033[5m'
    
    # Foreground colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright foreground
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    # Background colors
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'
    
    # 256 color support (for gradients)
    @staticmethod
    def color256(fg: int) -> str:
        """Return 256-color foreground code (0-255)."""
        return f'\033[38;5;{fg}m'
    
    @staticmethod
    def bg256(bg: int) -> str:
        """Return 256-color background code (0-255)."""
        return f'\033[48;5;{bg}m'
    
    @staticmethod
    def clear_screen():
        """Clear terminal screen."""
        print('\033[2J\033[H', end='')
    
    @staticmethod
    def move_cursor(row: int, col: int):
        """Move cursor to specific position."""
        print(f'\033[{row};{col}H', end='')
    
    @staticmethod
    def hide_cursor():
        """Hide cursor."""
        print('\033[?25l', end='')
    
    @staticmethod
    def show_cursor():
        """Show cursor."""
        print('\033[?25h', end='')


@dataclass
class ColorScheme:
    """Configurable color scheme for the game."""
    # Card colors
    suit_hearts: str = Colors.BRIGHT_RED
    suit_diamonds: str = Colors.BRIGHT_MAGENTA
    suit_clubs: str = Colors.GREEN
    suit_spades: str = Colors.CYAN
    
    # UI elements
    primary: str = Colors.BRIGHT_CYAN
    secondary: str = Colors.BRIGHT_YELLOW
    accent: str = Colors.BRIGHT_MAGENTA
    success: str = Colors.BRIGHT_GREEN
    warning: str = Colors.BRIGHT_YELLOW
    error: str = Colors.BRIGHT_RED
    info: str = Colors.WHITE
    
    # Table and background
    table_border: str = Colors.BRIGHT_YELLOW
    table_fill: str = Colors.DIM
    card_back: str = Colors.BRIGHT_BLUE
    chip_stack: str = Colors.BRIGHT_GREEN
    
    # Text styles
    highlight: str = Colors.BOLD + Colors.BRIGHT_WHITE
    dim_text: str = Colors.DIM + Colors.WHITE
    
    @classmethod
    def default(cls) -> 'ColorScheme':
        """Default vibrant color scheme."""
        return cls()
    
    @classmethod
    def colorblind_friendly(cls) -> 'ColorScheme':
        """
        Colorblind-friendly scheme (deuteranopia/protanopia).
        Uses blue/orange instead of red/green.
        """
        return cls(
            suit_hearts=Colors.BRIGHT_MAGENTA,      # Pink instead of red
            suit_diamonds=Colors.BRIGHT_YELLOW,      # Yellow instead of magenta
            suit_clubs=Colors.BRIGHT_CYAN,           # Cyan instead of green
            suit_spades=Colors.BRIGHT_BLUE,          # Blue
            primary=Colors.BRIGHT_CYAN,
            secondary=Colors.BRIGHT_YELLOW,
            accent=Colors.BRIGHT_MAGENTA,
            success=Colors.BRIGHT_CYAN,              # Cyan instead of green
            warning=Colors.BRIGHT_YELLOW,
            error=Colors.BRIGHT_RED,
            info=Colors.WHITE,
            table_border=Colors.BRIGHT_YELLOW,
            table_fill=Colors.DIM,
            card_back=Colors.BRIGHT_BLUE,
            chip_stack=Colors.BRIGHT_CYAN,
            highlight=Colors.BOLD + Colors.BRIGHT_WHITE,
            dim_text=Colors.DIM + Colors.WHITE,
        )
    
    @classmethod
    def monochrome(cls) -> 'ColorScheme':
        """Monochrome scheme for maximum compatibility."""
        return cls(
            suit_hearts=Colors.WHITE,
            suit_diamonds=Colors.WHITE,
            suit_clubs=Colors.WHITE,
            suit_spades=Colors.WHITE,
            primary=Colors.BOLD,
            secondary=Colors.WHITE,
            accent=Colors.BOLD,
            success=Colors.BOLD,
            warning=Colors.WHITE,
            error=Colors.WHITE,
            info=Colors.WHITE,
            table_border=Colors.WHITE,
            table_fill=Colors.DIM,
            card_back=Colors.DIM,
            chip_stack=Colors.BOLD,
            highlight=Colors.BOLD,
            dim_text=Colors.DIM,
        )
    
    @classmethod
    def dark_modern(cls) -> 'ColorScheme':
        """Modern dark theme with purple accents."""
        return cls(
            suit_hearts=Colors.BRIGHT_RED,
            suit_diamonds=Colors.BRIGHT_MAGENTA,
            suit_clubs=Colors.BRIGHT_GREEN,
            suit_spades=Colors.BRIGHT_CYAN,
            primary=Colors.BRIGHT_MAGENTA,
            secondary=Colors.BRIGHT_CYAN,
            accent=Colors.BRIGHT_PURPLE if hasattr(Colors, 'BRIGHT_PURPLE') else Colors.BRIGHT_MAGENTA,
            success=Colors.BRIGHT_GREEN,
            warning=Colors.BRIGHT_YELLOW,
            error=Colors.BRIGHT_RED,
            info=Colors.WHITE,
            table_border=Colors.BRIGHT_MAGENTA,
            table_fill=Colors.DIM,
            card_back=Colors.BG_BLUE + Colors.WHITE,
            chip_stack=Colors.BRIGHT_GREEN,
            highlight=Colors.BOLD + Colors.BRIGHT_MAGENTA,
            dim_text=Colors.DIM + Colors.WHITE,
        )


class StyledText:
    """Helper for building styled text strings."""
    
    def __init__(self, scheme: Optional[ColorScheme] = None):
        self.scheme = scheme or ColorScheme.default()
        self._buffer = ""
    
    def append(self, text: str, style: str = "") -> 'StyledText':
        """Append styled text."""
        if style:
            self._buffer += f"{style}{text}{Colors.RESET}"
        else:
            self._buffer += text
        return self
    
    def primary(self, text: str) -> 'StyledText':
        self._buffer += f"{self.scheme.primary}{text}{Colors.RESET}"
        return self
    
    def secondary(self, text: str) -> 'StyledText':
        self._buffer += f"{self.scheme.secondary}{text}{Colors.RESET}"
        return self
    
    def success(self, text: str) -> 'StyledText':
        self._buffer += f"{self.scheme.success}{text}{Colors.RESET}"
        return self
    
    def warning(self, text: str) -> 'StyledText':
        self._buffer += f"{self.scheme.warning}{text}{Colors.RESET}"
        return self
    
    def error(self, text: str) -> 'StyledText':
        self._buffer += f"{self.scheme.error}{text}{Colors.RESET}"
        return self
    
    def highlight(self, text: str) -> 'StyledText':
        self._buffer += f"{self.scheme.highlight}{text}{Colors.RESET}"
        return self
    
    def dim(self, text: str) -> 'StyledText':
        self._buffer += f"{self.scheme.dim_text}{text}{Colors.RESET}"
        return self
    
    def suit(self, text: str, suit: str) -> 'StyledText':
        """Style text by suit symbol."""
        if suit in '♥❤':
            self._buffer += f"{self.scheme.suit_hearts}{text}{Colors.RESET}"
        elif suit in '♦◆':
            self._buffer += f"{self.scheme.suit_diamonds}{text}{Colors.RESET}"
        elif suit in '♣♧':
            self._buffer += f"{self.scheme.suit_clubs}{text}{Colors.RESET}"
        elif suit in '♠♤':
            self._buffer += f"{self.scheme.suit_spades}{text}{Colors.RESET}"
        else:
            self._buffer += text
        return self
    
    def __str__(self) -> str:
        return self._buffer
    
    def __len__(self) -> int:
        """Return visible length (excluding ANSI codes)."""
        import re
        return len(re.sub(r'\033\[[0-9;]*m', '', self._buffer))
