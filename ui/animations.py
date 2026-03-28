"""
Terminal animations for dealing and actions.
"""
import time
from typing import List, Optional
from ui.colors import Colors, ColorScheme, StyledText


class Animations:
    """Terminal animations for enhanced visual presentation."""
    
    def __init__(self, scheme: Optional[ColorScheme] = None, enabled: bool = True):
        self.scheme = scheme or ColorScheme.default()
        self.enabled = enabled
        self.delay = 0.05  # Base delay between frames
    
    def clear_screen(self):
        """Clear the terminal screen."""
        if self.enabled:
            print(Colors.clear_screen(), end='')
    
    def hide_cursor(self):
        """Hide the cursor during animation."""
        if self.enabled:
            print(Colors.hide_cursor(), end='')
    
    def show_cursor(self):
        """Show the cursor after animation."""
        if self.enabled:
            print(Colors.show_cursor(), end='')
    
    def deal_card_animation(self, from_pos: tuple, to_pos: tuple, card_display: str):
        """
        Animate a card being dealt from one position to another.
        
        Args:
            from_pos: (row, col) starting position
            to_pos: (row, col) ending position
            card_display: ASCII card representation
        """
        if not self.enabled:
            return
        
        self.hide_cursor()
        
        start_row, start_col = from_pos
        end_row, end_col = to_pos
        
        # Calculate steps
        steps = 5
        row_step = (end_row - start_row) / steps
        col_step = (end_col - start_col) / steps
        
        # Animate movement
        for i in range(steps):
            row = int(start_row + row_step * i)
            col = int(start_col + col_step * i)
            
            # Clear previous and draw new
            Colors.move_cursor(row, col)
            print("░░░", end='')
            
            Colors.move_cursor(int(row + row_step), int(col + col_step))
            print("▓▓▓", end='', flush=True)
            time.sleep(self.delay)
        
        # Show final card
        Colors.move_cursor(end_row, end_col)
        print(card_display[:3], end='')
        
        self.show_cursor()
    
    def deal_all_cards_animation(self, player_positions: List[tuple], 
                                  community_pos: tuple, delay: float = 0.1):
        """
        Animate dealing cards to all players and community.
        
        Args:
            player_positions: List of (row, col) for each player's card position
            community_pos: (row, col) for community cards
            delay: Delay between each card
        """
        if not self.enabled:
            return
        
        self.hide_cursor()
        
        # Deal to each player
        for i, pos in enumerate(player_positions):
            row, col = pos
            Colors.move_cursor(row, col)
            print("┌───┐", end='', flush=True)
            Colors.move_cursor(row + 1, col)
            print("│░░░│", end='', flush=True)
            Colors.move_cursor(row + 2, col)
            print("└───┘", end='', flush=True)
            time.sleep(delay)
        
        # Flip cards
        for i, pos in enumerate(player_positions):
            row, col = pos
            Colors.move_cursor(row + 1, col)
            print("│??│", end='', flush=True)
            time.sleep(delay * 0.5)
        
        self.show_cursor()
    
    def reveal_community_animation(self, community_pos: tuple, cards: List[str],
                                    delay: float = 0.3):
        """
        Animate revealing community cards (flop, turn, river).
        
        Args:
            community_pos: (row, col) starting position
            cards: List of card ASCII representations
            delay: Delay between each card reveal
        """
        if not self.enabled:
            return
        
        self.hide_cursor()
        
        row, col = community_pos
        
        for i, card in enumerate(cards):
            # Show card back first
            Colors.move_cursor(row, col + i * 12)
            print("┌─────────┐", end='', flush=True)
            Colors.move_cursor(row + 1, col + i * 12)
            print("│░░░░░░░░░│", end='', flush=True)
            Colors.move_cursor(row + 2, col + i * 12)
            print("│░░░░░░░░░│", end='', flush=True)
            Colors.move_cursor(row + 3, col + i * 12)
            print("│░░░░░░░░░│", end='', flush=True)
            Colors.move_cursor(row + 4, col + i * 12)
            print("│░░░░░░░░░│", end='', flush=True)
            Colors.move_cursor(row + 5, col + i * 12)
            print("└─────────┘", end='', flush=True)
            time.sleep(delay * 0.5)
            
            # Flip to reveal
            Colors.move_cursor(row, col + i * 12)
            print(card[:11], end='', flush=True)
            time.sleep(delay)
        
        self.show_cursor()
    
    def chip_stack_animation(self, from_pos: tuple, to_pos: tuple, amount: int):
        """
        Animate chips moving to the pot.
        
        Args:
            from_pos: (row, col) player position
            to_pos: (row, col) pot position
            amount: Chip amount
        """
        if not self.enabled:
            return
        
        self.hide_cursor()
        
        start_row, start_col = from_pos
        end_row, end_col = to_pos
        
        # Animate chip movement
        steps = 3
        for i in range(steps):
            progress = i / steps
            row = int(start_row + (end_row - start_row) * progress)
            col = int(start_col + (end_col - start_col) * progress)
            
            Colors.move_cursor(row, col)
            print("●", end='', flush=True)
            time.sleep(self.delay * 2)
        
        # Show amount added to pot
        Colors.move_cursor(end_row, end_col)
        print(f"+{amount}", end='', flush=True)
        time.sleep(0.2)
        
        self.show_cursor()
    
    def action_highlight(self, position: tuple, action: str, player_name: str):
        """
        Highlight a player's action with animation.
        
        Args:
            position: (row, col) position to highlight
            action: Action taken (BET, RAISE, FOLD, etc.)
            player_name: Name of the player
        """
        if not self.enabled:
            return
        
        self.hide_cursor()
        
        row, col = position
        
        # Flash effect
        for _ in range(2):
            Colors.move_cursor(row, col)
            print(f"► {player_name}: {action}", end='', flush=True)
            time.sleep(0.1)
            Colors.move_cursor(row, col)
            print(f"  {player_name}: {action}", end='', flush=True)
            time.sleep(0.1)
        
        self.show_cursor()
    
    def winner_celebration(self, position: tuple, winner_name: str, amount: int):
        """
        Celebrate the winner with animation.
        
        Args:
            position: (row, col) position to display
            winner_name: Name of the winner
            amount: Amount won
        """
        if not self.enabled:
            return
        
        self.hide_cursor()
        
        row, col = position
        
        # Celebration frames
        frames = [
            f"🎉 {winner_name} wins {amount}! 🎉",
            f"✨ {winner_name} wins {amount}! ✨",
            f"🏆 {winner_name} wins {amount}! 🏆",
        ]
        
        for frame in frames:
            Colors.move_cursor(row, col)
            print(frame, end='', flush=True)
            time.sleep(0.3)
        
        # Final display
        Colors.move_cursor(row, col)
        print(f"★★★ {winner_name} wins {amount}! ★★★", end='', flush=True)
        
        self.show_cursor()
    
    def loading_spinner(self, message: str = "Loading", duration: float = 1.0):
        """
        Show a loading spinner animation.
        
        Args:
            message: Message to display
            duration: How long to show spinner
        """
        if not self.enabled:
            print(f"{message}...")
            return
        
        self.hide_cursor()
        
        spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        end_time = time.time() + duration
        
        while time.time() < end_time:
            for frame in spinner:
                print(f"\r{frame} {message}...", end='', flush=True)
                time.sleep(0.08)
        
        print(f"\r✓ {message}... Done!    ")
        self.show_cursor()
    
    def progress_bar(self, current: int, total: int, width: int = 30,
                     message: str = ""):
        """
        Display a progress bar.
        
        Args:
            current: Current progress
            total: Total amount
            width: Width of the bar
            message: Optional message
        """
        if not self.enabled:
            return
        
        self.hide_cursor()
        
        filled = int(width * current / total)
        bar = '█' * filled + '░' * (width - filled)
        percent = current / total * 100
        
        print(f"\r{message} [{bar}] {percent:.0f}%", end='', flush=True)
        
        if current >= total:
            print()  # New line when complete
        
        self.show_cursor()
    
    def shuffle_animation(self, rows: int = 5):
        """
        Show a card shuffle animation.
        
        Args:
            rows: Number of rows to animate
        """
        if not self.enabled:
            return
        
        self.hide_cursor()
        
        shuffle_chars = ['▓', '░', '█', '▒', '▀', '▄']
        
        for _ in range(5):
            for row in range(rows):
                Colors.move_cursor(row + 5, 20)
                line = ''.join(shuffle_chars[i % len(shuffle_chars)] 
                              for i in range(row * 3, row * 3 + 20))
                print(line, end='', flush=True)
            time.sleep(0.1)
        
        self.show_cursor()
    
    def fade_in_text(self, text: str, position: tuple, delay: float = 0.05):
        """
        Fade in text character by character.
        
        Args:
            text: Text to display
            position: (row, col) position
            delay: Delay between characters
        """
        if not self.enabled:
            Colors.move_cursor(*position)
            print(text, end='')
            return
        
        self.hide_cursor()
        
        row, col = position
        for i, char in enumerate(text):
            Colors.move_cursor(row, col + i)
            print(char, end='', flush=True)
            time.sleep(delay)
        
        self.show_cursor()
    
    def blink_text(self, text: str, position: tuple, times: int = 3):
        """
        Make text blink several times.
        
        Args:
            text: Text to blink
            position: (row, col) position
            times: Number of blinks
        """
        if not self.enabled:
            Colors.move_cursor(*position)
            print(text, end='')
            return
        
        self.hide_cursor()
        
        row, col = position
        
        for _ in range(times):
            Colors.move_cursor(row, col)
            print(text, end='', flush=True)
            time.sleep(0.15)
            Colors.move_cursor(row, col)
            print(' ' * len(text), end='', flush=True)
            time.sleep(0.15)
        
        Colors.move_cursor(row, col)
        print(text, end='', flush=True)
        
        self.show_cursor()
