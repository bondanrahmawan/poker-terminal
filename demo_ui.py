#!/usr/bin/env python
"""
Demo script to showcase the enhanced terminal UI.
Run this to see the visual improvements.
"""
import time
from ui.colors import Colors, ColorScheme, StyledText
from ui.cards import CardRenderer
from ui.table import PokerTableRenderer
from ui.menu import MenuRenderer
from ui.animations import Animations
from core.card import Card, Suit, Rank


def clear():
    Colors.clear_screen()
    print()


def demo_logo():
    """Demo the logo rendering."""
    clear()
    scheme = ColorScheme.default()
    menu = MenuRenderer(scheme)
    
    print("\n".join(menu.render_logo()))
    input("\nPress Enter to continue...")


def demo_cards():
    """Demo card rendering."""
    clear()
    scheme = ColorScheme.default()
    renderer = CardRenderer()
    
    print("  ╔══════════════════════════════════════════╗")
    print("  ║         C A R D   R E N D E R I N G      ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    
    # Render all suits
    print("  All Suits:")
    for suit in Suit:
        card = Card(14, suit)  # Ace
        lines = renderer.render_card(card, scheme)
        for line in lines:
            print(f"  {line}")
        print()
    
    input("\nPress Enter to continue...")


def demo_hand():
    """Demo hand rendering."""
    clear()
    scheme = ColorScheme.default()
    renderer = CardRenderer()
    
    print("  ╔══════════════════════════════════════════╗")
    print("  ║           H A N D   E X A M P L E S      ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    
    # Pocket Aces
    print("  Pocket Aces:")
    hand = [Card(14, Suit.SPADES), Card(14, Suit.HEARTS)]
    lines = renderer.render_hand(hand, scheme)
    for line in lines:
        print(f"    {line}")
    print()
    
    # Suited connectors
    print("  Suited Connectors (JTs):")
    hand = [Card(11, Suit.DIAMONDS), Card(10, Suit.DIAMONDS)]
    lines = renderer.render_hand(hand, scheme)
    for line in lines:
        print(f"    {line}")
    print()
    
    # Card back
    print("  Card Back:")
    lines = renderer.render_card(None, scheme, style='back')
    for line in lines:
        print(f"    {line}")
    print()
    
    input("\nPress Enter to continue...")


def demo_color_schemes():
    """Demo different color schemes."""
    clear()
    renderer = CardRenderer()
    
    print("  ╔══════════════════════════════════════════╗")
    print("  ║         C O L O R   S C H E M E S        ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    
    schemes = [
        ("Default", ColorScheme.default()),
        ("Colorblind Friendly", ColorScheme.colorblind_friendly()),
        ("Dark Modern", ColorScheme.dark_modern()),
        ("Monochrome", ColorScheme.monochrome()),
    ]
    
    for name, scheme in schemes:
        print(f"  {name}:")
        card = Card(14, Suit.HEARTS)
        lines = renderer.render_card(card, scheme)
        for line in lines:
            print(f"    {line}")
        print()
    
    input("\nPress Enter to continue...")


def demo_table():
    """Demo full table rendering."""
    clear()
    from core.player import Player
    from players.terminal import TerminalPlayer
    
    scheme = ColorScheme.default()
    table_renderer = PokerTableRenderer(scheme)
    
    print("  ╔══════════════════════════════════════════╗")
    print("  ║        T A B L E   R E N D E R I N G     ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    
    # Create some test players
    players = [
        TerminalPlayer("Alice", 1000),
        TerminalPlayer("Bob", 1500),
        TerminalPlayer("Charlie", 800),
    ]
    
    # Deal some cards
    for i, p in enumerate(players):
        p.receive_cards([Card(14 - i, Suit.SPADES), Card(10 + i, Suit.HEARTS)])
    
    # Community cards
    community = [Card(10, Suit.DIAMONDS), Card(11, Suit.CLUBS), Card(12, Suit.SPADES)]
    
    # Render table
    table = table_renderer.render_table(
        players=players,
        community_cards=community,
        pot_amount=450,
        dealer_idx=0,
        active_player_ids=[p.player_id for p in players],
        player_roles={p.player_id: 'SB' if i == 0 else 'BB' if i == 1 else 'BTN' 
                      for i, p in enumerate(players)},
        current_bet=100,
        last_action="Bob calls 100"
    )
    
    print(table)
    print()
    
    input("\nPress Enter to continue...")


def demo_community_cards():
    """Demo community card rendering."""
    clear()
    scheme = ColorScheme.default()
    renderer = CardRenderer()
    
    print("  ╔══════════════════════════════════════════╗")
    print("  ║      C O M M U N I T Y   C A R D S       ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    
    # Preflop
    print("  Preflop:")
    print(f"    {renderer.render_community([], scheme)}")
    print()
    
    # Flop
    print("  Flop:")
    flop = [Card(10, Suit.DIAMONDS), Card(11, Suit.CLUBS), Card(12, Suit.SPADES)]
    print(f"    {renderer.render_community(flop, scheme)}")
    print()
    
    # Turn
    print("  Turn:")
    turn = flop + [Card(5, Suit.HEARTS)]
    print(f"    {renderer.render_community(turn, scheme)}")
    print()
    
    # River
    print("  River:")
    river = turn + [Card(14, Suit.DIAMONDS)]
    print(f"    {renderer.render_community(river, scheme)}")
    print()
    
    input("\nPress Enter to continue...")


def demo_menu():
    """Demo menu rendering."""
    clear()
    scheme = ColorScheme.default()
    menu = MenuRenderer(scheme)
    
    print("  ╔══════════════════════════════════════════╗")
    print("  ║           M E N U   D E M O              ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    
    print("\n".join(menu.render_main_menu()))
    print()
    
    input("\nPress Enter to continue...")


def run_full_demo():
    """Run the complete demo."""
    Colors.clear_screen()
    
    scheme = ColorScheme.default()
    print("\n".join(MenuRenderer(scheme).render_logo()))
    print()
    print("  Welcome to the Poker Terminal UI Demo!")
    print()
    print("  This demo showcases the enhanced visual presentation")
    print("  features including:")
    print()
    print("    • Colorful ASCII card rendering")
    print("    • Multiple color schemes (including colorblind mode)")
    print("    • Full poker table layout")
    print("    • Interactive menus")
    print("    • Smooth animations")
    print()
    input("  Press Enter to start the demo...")
    
    demo_logo()
    demo_cards()
    demo_hand()
    demo_color_schemes()
    demo_community_cards()
    demo_table()
    demo_menu()
    
    clear()
    print("\n".join(MenuRenderer(scheme).render_logo()))
    print()
    print("  Demo complete!")
    print()
    print("  To use the enhanced UI in your game, import the ui module:")
    print()
    print("    from ui import Colors, ColorScheme, PokerTableRenderer")
    print("    from ui.cards import CardRenderer")
    print()
    print("  You can also enable animations:")
    print()
    print("    from ui.animations import Animations")
    print("    anim = Animations(enabled=True)")
    print()
    print("  Thanks for trying the enhanced UI!")
    print()


if __name__ == "__main__":
    run_full_demo()
