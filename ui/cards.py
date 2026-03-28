"""
ASCII card rendering with multiple styles.
"""
from typing import List, Optional
from core.card import Card as GameCard
from ui.colors import Colors, ColorScheme, StyledText


class CardRenderer:
    """Renders playing cards as ASCII art."""
    
    # Card dimensions
    CARD_WIDTH = 11
    CARD_HEIGHT = 7
    
    # Card templates
    CARD_TOP = "┌─────────┐"
    CARD_BOTTOM = "└─────────┘"
    CARD_SIDE = "│"
    
    # Suit symbols - map from Suit class constants
    SUITS = {
        'Spades': '♠',
        'Hearts': '♥',
        'Diamonds': '♦',
        'Clubs': '♣',
    }
    
    # Rank symbols
    RANK_SYMBOLS = {
        14: 'A', 13: 'K', 12: 'Q', 11: 'J',
        10: 'T', 9: '9', 8: '8', 7: '7',
        6: '6', 5: '5', 4: '4', 3: '3', 2: '2'
    }
    
    @classmethod
    def render_card(cls, card: GameCard, scheme: Optional[ColorScheme] = None,
                    style: str = 'default') -> List[str]:
        """
        Render a single card as ASCII art.
        
        Styles:
            - 'default': Standard card with suit in corners
            - 'minimal': Simplified card
            - 'large': Larger card with center suit
            - 'back': Card back design
        """
        scheme = scheme or ColorScheme.default()
        
        if card is None:
            return cls._render_empty(scheme)
        
        if style == 'back':
            return cls._render_back(scheme)
        
        rank_sym = cls.RANK_SYMBOLS.get(card.rank, str(card.rank))
        suit_sym = cls.SUITS.get(card.suit, '♥')
        suit_name = card.suit  # Already a string like 'Hearts', 'Spades'
        
        if style == 'minimal':
            return cls._render_minimal(rank_sym, suit_sym, scheme, suit_name)
        elif style == 'large':
            return cls._render_large(rank_sym, suit_sym, scheme, suit_name)
        else:
            return cls._render_default(rank_sym, suit_sym, scheme, suit_name)
    
    @classmethod
    def _render_default(cls, rank: str, suit: str, scheme: ColorScheme,
                        suit_name: str) -> List[str]:
        """Standard card rendering."""
        # Determine color based on suit
        is_red = suit_name.lower() in ['hearts', 'diamonds']
        color = scheme.suit_hearts if is_red else scheme.suit_clubs

        # Build each line independently to avoid accumulation
        lines = [
            f"{cls.CARD_TOP}",
            f"{color}│{rank}{suit}       │{Colors.RESET}",
            f"{color}│    {suit}    │{Colors.RESET}",
            f"│         │",
            f"│         │",
            f"{color}│       {suit}{rank}│{Colors.RESET}",
            f"{cls.CARD_BOTTOM}",
        ]

        return lines
    
    @classmethod
    def _render_minimal(cls, rank: str, suit: str, scheme: ColorScheme,
                        suit_name: str) -> List[str]:
        """Minimalist card rendering."""
        is_red = suit_name.lower() in ['hearts', 'diamonds']
        color = scheme.suit_hearts if is_red else scheme.suit_clubs

        return [
            f"┌───┐",
            f"{color}│{rank}{suit}│{Colors.RESET}",
            f"└───┘",
        ]
    
    @classmethod
    def _render_large(cls, rank: str, suit: str, scheme: ColorScheme,
                      suit_name: str) -> List[str]:
        """Large card with decorative center."""
        is_red = suit_name.lower() in ['hearts', 'diamonds']
        color = scheme.suit_hearts if is_red else scheme.suit_clubs

        # Large suit pattern
        large_suit = {
            '♥': [" ♥ ", "♥♥♥", " ♥ "],
            '♦': ["  ♥ ", " ♥♥ ", "  ♥ "],
            '♣': ["  ♣  ", " ♣♣♣ ", "  ♣  "],
            '♠': ["  ♠  ", " ♠♠♠ ", "  ♠  "],
        }.get(suit, [" * ", "***", " * "])

        return [
            f"┌───────────┐",
            f"{color}│ {rank:<2} {suit}       │{Colors.RESET}",
            f"{color}│   {large_suit[0]}     │{Colors.RESET}",
            f"{color}│   {large_suit[1]}     │{Colors.RESET}",
            f"{color}│   {large_suit[2]}     │{Colors.RESET}",
            f"{color}│       {suit} {rank:>2}│{Colors.RESET}",
            f"└───────────┘",
        ]
    
    @classmethod
    def _render_back(cls, scheme: ColorScheme) -> List[str]:
        """Card back design."""
        color = scheme.card_back

        return [
            f"┌─────────┐",
            f"{color}│░░░░░░░░░│{Colors.RESET}",
            f"{color}│░╔═════╗░│{Colors.RESET}",
            f"{color}│░║ POKER ║░│{Colors.RESET}",
            f"{color}│░╚═════╝░│{Colors.RESET}",
            f"{color}│░░░░░░░░░│{Colors.RESET}",
            f"└─────────┘",
        ]
    
    @classmethod
    def _render_empty(cls, scheme: ColorScheme) -> List[str]:
        """Empty placeholder (for folded player's cards)."""
        color = scheme.dim_text

        return [
            f"┌─────────┐",
            f"{color}│         │{Colors.RESET}",
            f"{color}│         │{Colors.RESET}",
            f"{color}│         │{Colors.RESET}",
            f"{color}│         │{Colors.RESET}",
            f"{color}│         │{Colors.RESET}",
            f"└─────────┘",
        ]
    
    @classmethod
    def render_hand(cls, cards: List[GameCard], scheme: Optional[ColorScheme] = None,
                    horizontal: bool = True) -> List[str]:
        """Render multiple cards (a hand)."""
        if not cards:
            return []
        
        rendered = [cls.render_card(c, scheme) for c in cards]
        
        if horizontal:
            # Combine side by side
            height = len(rendered[0])
            lines = []
            for i in range(height):
                line = "  ".join(card[i] for card in rendered)
                lines.append(line)
            return lines
        else:
            # Stack vertically
            lines = []
            for card in rendered:
                lines.extend(card)
            return lines
    
    @classmethod
    def render_community(cls, cards: List[GameCard], scheme: Optional[ColorScheme] = None) -> str:
        """Render community cards in a compact format."""
        if not cards:
            return "[ No community cards ]"

        scheme = scheme or ColorScheme.default()

        parts = []
        for card in cards:
            rank_sym = cls.RANK_SYMBOLS.get(card.rank, str(card.rank))
            suit_sym = cls.SUITS.get(card.suit, '♥')
            is_red = card.suit.lower() in ['hearts', 'diamonds']
            color = scheme.suit_hearts if is_red else scheme.suit_clubs

            parts.append(f"{color}[{rank_sym}{suit_sym}]{Colors.RESET}")

        return "  ".join(parts)
