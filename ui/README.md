# Enhanced Terminal UI

A comprehensive visual enhancement module for Poker Terminal, featuring beautiful ASCII card rendering, multiple color schemes, and smooth animations.

## Features

### 🎨 Beautiful Card Rendering
- Detailed ASCII art playing cards
- Multiple rendering styles (default, minimal, large)
- Suit-specific coloring (hearts/diamonds in red, clubs/spades in green/cyan)
- Card back designs

### 🌈 Multiple Color Schemes
- **Default**: Vibrant colors with clear suit distinction
- **Colorblind Friendly**: Optimized for deuteranopia/protanopia
- **Dark Modern**: Purple accents with dark theme
- **Monochrome**: Maximum compatibility

### 🎯 Full Table Rendering
- Dynamic layout based on player count
- Heads-up (2 players), Short (3-4), Full (5+) table layouts
- Dealer button indicators
- Player role labels (SB, BB, BTN, CO, etc.)
- Pot and bet display

### 📋 Interactive Menus
- Main menu with box-drawn interface
- Settings menu with toggle options
- Game mode selection
- Bot selection screen
- Help/How to Play guide

### ✨ Animations
- Card dealing animations
- Chip movement to pot
- Action highlights
- Winner celebration
- Loading spinners
- Progress bars
- Text fade-in effects

## Quick Start

### Run the Demo
```bash
python demo_ui.py
```

This showcases all UI features interactively.

### Basic Usage

```python
from ui.colors import Colors, ColorScheme
from ui.cards import CardRenderer
from ui.table import PokerTableRenderer
from ui.menu import MenuRenderer
from core.card import Card, Suit, Rank

# Initialize with a color scheme
scheme = ColorScheme.default()

# Render a card
renderer = CardRenderer()
card = Card(Rank.ACE, Suit.SPADES)
card_lines = renderer.render_card(card, scheme)
for line in card_lines:
    print(line)

# Render a hand
hand = [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.HEARTS)]
hand_lines = renderer.render_hand(hand, scheme)
for line in hand_lines:
    print(line)

# Render community cards
community = [Card(10, Suit.DIAMONDS), Card(11, Suit.CLUBS), Card(12, Suit.SPADES)]
print(renderer.render_community(community, scheme))

# Render full table
table_renderer = PokerTableRenderer(scheme)
table = table_renderer.render_table(
    players=players,
    community_cards=community,
    pot_amount=500,
    dealer_idx=0,
    active_player_ids=[p.player_id for p in players],
    player_roles=roles_dict,
    current_bet=100
)
print(table)

# Render menu
menu = MenuRenderer(scheme)
print("\n".join(menu.render_main_menu()))
```

### Using Color Schemes

```python
# Default scheme
scheme = ColorScheme.default()

# Colorblind-friendly
scheme = ColorScheme.colorblind_friendly()

# Dark modern theme
scheme = ColorScheme.dark_modern()

# Monochrome (for terminals with limited color)
scheme = ColorScheme.monochrome()
```

### Using Animations

```python
from ui.animations import Animations

# Initialize animations
anim = Animations(enabled=True, scheme=scheme)

# Clear screen with animation
anim.clear_screen()

# Show loading spinner
anim.loading_spinner("Dealing cards", duration=1.0)

# Animate card reveal
anim.reveal_community_animation(
    community_pos=(10, 20),
    cards=card_ascii_list,
    delay=0.3
)

# Celebrate winner
anim.winner_celebration(
    position=(15, 30),
    winner_name="Alice",
    amount=1500
)
```

## Module Structure

```
ui/
├── __init__.py          # Package exports
├── colors.py            # Color schemes and ANSI utilities
├── cards.py             # Card rendering
├── table.py             # Full table layout
├── menu.py              # Menu screens
└── animations.py        # Visual animations
```

## API Reference

### Colors

ANSI color codes and terminal control:

```python
Colors.RESET      # Reset all formatting
Colors.BOLD       # Bold text
Colors.RED        # Red foreground
Colors.BRIGHT_CYAN  # Bright cyan
Colors.BG_BLUE    # Blue background
Colors.clear_screen()    # Clear terminal
Colors.move_cursor(r, c) # Move cursor
Colors.hide_cursor()     # Hide cursor
Colors.show_cursor()     # Show cursor
```

### ColorScheme

Configurable color themes:

```python
ColorScheme.default()           # Standard vibrant theme
ColorScheme.colorblind_friendly()  # Accessibility mode
ColorScheme.dark_modern()       # Purple accent theme
ColorScheme.monochrome()        # B&W compatibility
```

### CardRenderer

Card visualization:

```python
CardRenderer.render_card(card, scheme, style='default')
  # style: 'default', 'minimal', 'large', 'back'

CardRenderer.render_hand(cards, scheme, horizontal=True)
  # Render multiple cards

CardRenderer.render_community(cards, scheme)
  # Compact community cards display
```

### PokerTableRenderer

Full table layout:

```python
PokerTableRenderer.render_table(
    players,              # List[Player]
    community_cards,      # List[Card]
    pot_amount,           # int
    dealer_idx,           # int
    active_player_ids,    # List[str]
    player_roles,         # Dict[str, str]
    current_bet,          # int
    last_action           # Optional[str]
)
```

### MenuRenderer

Menu screens:

```python
MenuRenderer.render_logo()           # Game logo
MenuRenderer.render_main_menu()      # Main menu
MenuRenderer.render_settings_menu(settings_dict)
MenuRenderer.render_game_mode_select()
MenuRenderer.render_bot_selection(bots_list)
MenuRenderer.render_help()           # How to play
```

### Animations

Visual effects:

```python
Animations.clear_screen()
Animations.deal_card_animation(from_pos, to_pos, card_display)
Animations.reveal_community_animation(pos, cards, delay)
Animations.chip_stack_animation(from_pos, to_pos, amount)
Animations.winner_celebration(pos, name, amount)
Animations.loading_spinner(message, duration)
Animations.progress_bar(current, total, width, message)
Animations.fade_in_text(text, pos, delay)
Animations.blink_text(text, pos, times)
```

## Accessibility

### Colorblind Mode

The `colorblind_friendly()` scheme uses:
- Pink/magenta instead of red (hearts)
- Yellow instead of magenta (diamonds)
- Cyan instead of green (clubs)
- Blue for spades

This ensures distinguishable suits for deuteranopia and protanopia.

### Monochrome Mode

For terminals with limited color support or screen readers:
```python
scheme = ColorScheme.monochrome()
```

## Performance Tips

1. **Disable animations** for faster gameplay:
   ```python
   anim = Animations(enabled=False)
   ```

2. **Reuse renderers** instead of creating new ones:
   ```python
   renderer = CardRenderer()  # Create once
   # Use renderer.render_card() multiple times
   ```

3. **Batch screen updates** to reduce flicker:
   ```python
   lines = []
   lines.extend(header_lines)
   lines.extend(table_lines)
   lines.extend(footer_lines)
   print("\n".join(lines))  # Single print call
   ```

## Troubleshooting

### Colors not showing
- Ensure your terminal supports ANSI colors
- Try `ColorScheme.monochrome()` for compatibility
- On Windows, ensure VT100 support is enabled

### Garbled display
- Use a monospace font
- Ensure terminal encoding is UTF-8
- Try a different terminal emulator

### Animations stuttering
- Disable animations for better performance
- Reduce animation delay values
- Close other CPU-intensive applications

## Integration with Game

To integrate the enhanced UI with the existing game:

1. Import UI modules in `main.py`:
   ```python
   from ui import Colors, ColorScheme, PokerTableRenderer
   from ui.menu import MenuRenderer
   ```

2. Replace print statements with UI rendering:
   ```python
   # Instead of:
   print(f"Pot: {pot_amount}")
   
   # Use:
   table_renderer = PokerTableRenderer(scheme)
   print(table_renderer.render_table(...))
   ```

3. Add menu system before game starts:
   ```python
   menu = MenuRenderer()
   print("\n".join(menu.render_main_menu()))
   choice = input("Select option: ")
   ```

4. Enable animations for key moments:
   ```python
   anim = Animations(enabled=True)
   anim.reveal_community_animation(...)
   ```

## Future Enhancements

- [ ] Sound effects (terminal bells)
- [ ] Mouse support for menu selection
- [ ] Customizable card designs
- [ ] Tournament bracket visualization
- [ ] Hand history replay viewer
- [ ] Statistics dashboard with charts

## Credits

Enhanced UI module created for Poker Terminal as a portfolio showcase feature.
