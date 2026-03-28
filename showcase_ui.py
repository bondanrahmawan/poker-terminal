#!/usr/bin/env python
"""
Non-interactive UI showcase - displays everything without waiting for input.
"""
import sys
from ui.colors import Colors, ColorScheme, StyledText
from ui.cards import CardRenderer
from ui.table import PokerTableRenderer
from ui.menu import MenuRenderer
from core.card import Card, Suit, Rank


def main():
    scheme = ColorScheme.default()
    card_renderer = CardRenderer()
    table_renderer = PokerTableRenderer(scheme)
    menu_renderer = MenuRenderer(scheme)
    
    # Clear screen
    Colors.clear_screen()
    
    # Logo
    print("\n".join(menu_renderer.render_logo()))
    
    print("\n" + "=" * 70)
    print("  UI COMPONENT SHOWCASE")
    print("=" * 70)
    
    # Card rendering
    print("\n\n1. CARD RENDERING")
    print("-" * 70)
    
    # Show one card
    card = Card(14, Suit.SPADES)
    print("\n  Ace of Spades:")
    for line in card_renderer.render_card(card, scheme):
        print(f"    {line}")
    
    # Show hand
    print("\n  Pocket Aces:")
    hand = [Card(14, Suit.SPADES), Card(14, Suit.HEARTS)]
    for line in card_renderer.render_hand(hand, scheme):
        print(f"    {line}")
    
    # Show card back
    print("\n  Card Back:")
    for line in card_renderer.render_card(None, scheme, style='back'):
        print(f"    {line}")
    
    # Color schemes
    print("\n\n2. COLOR SCHEMES (Ace of Hearts)")
    print("-" * 70)
    
    for name, color_scheme in [
        ("Default", ColorScheme.default()),
        ("Colorblind Friendly", ColorScheme.colorblind_friendly()),
        ("Monochrome", ColorScheme.monochrome()),
    ]:
        print(f"\n  {name}:")
        card = Card(14, Suit.HEARTS)
        lines = card_renderer.render_card(card, color_scheme)
        for line in lines[:3]:  # Show first 3 lines only
            print(f"    {line}")
        print("    ...")
    
    # Community cards
    print("\n\n3. COMMUNITY CARDS")
    print("-" * 70)
    
    print("\n  Flop:")
    flop = [Card(10, Suit.DIAMONDS), Card(11, Suit.CLUBS), Card(12, Suit.SPADES)]
    print(f"    {card_renderer.render_community(flop, scheme)}")
    
    print("\n  Turn:")
    turn = flop + [Card(5, Suit.HEARTS)]
    print(f"    {card_renderer.render_community(turn, scheme)}")
    
    print("\n  River:")
    river = turn + [Card(14, Suit.DIAMONDS)]
    print(f"    {card_renderer.render_community(river, scheme)}")
    
    # Table rendering
    print("\n\n4. TABLE RENDERING (3 players)")
    print("-" * 70)
    
    from core.player import Player
    
    players = [
        Player("alice", "Alice", 1000),
        Player("bob", "Bob", 1500),
        Player("charlie", "Charlie", 800),
    ]
    
    for i, p in enumerate(players):
        p.receive_cards([Card(14 - i, Suit.SPADES), Card(10 + i, Suit.HEARTS)])
    
    community = [Card(10, Suit.DIAMONDS), Card(11, Suit.CLUBS), Card(12, Suit.SPADES)]
    
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
    
    print()
    print(table)
    
    # Menu
    print("\n\n5. MAIN MENU")
    print("-" * 70)
    print()
    for line in menu_renderer.render_main_menu():
        print(line)
    
    # Footer
    print("\n\n" + "=" * 70)
    print("  SHOWCASE COMPLETE")
    print("=" * 70)
    print("\n  To run the interactive demo with animations, run:")
    print("    python demo_ui.py")
    print()
    print("  Or integrate the UI into your game by importing:")
    print("    from ui import ColorScheme, PokerTableRenderer, CardRenderer")
    print()


if __name__ == "__main__":
    main()
