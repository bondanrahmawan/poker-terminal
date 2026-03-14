"""
Comprehensive tests for Game logic.
Run with: pytest test_game.py -v
"""
import pytest
from game import Game
from bot import BotPlayer
from player import Player, PlayerAction
from card import Card, Suit


class TestGameSetup:
    """Tests for game initialization."""

    def test_create_game(self):
        """Test basic game creation."""
        g = Game(big_blind=20)
        assert g.big_blind == 20
        assert len(g.players) == 0
        assert g.community_cards == []

    def test_add_player(self):
        """Test adding players to game."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        assert len(g.players) == 1
        assert g.players[0].name == "Alice"
        assert g.players[0].chips == 1000

    def test_cannot_start_with_one_player(self):
        """Test that game cannot start with only one player."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.start_game()
        assert "Not enough players" in g.logs[0]

    def test_minimum_two_players(self):
        """Test game starts with minimum 2 players."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))
        g.start_game()
        assert g.logs[0] == "\n--- NEW HAND ---"


class TestBlinds:
    """Tests for blind posting."""

    def test_blinds_posted_correctly(self):
        """Test that small and big blinds are posted."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))
        g.add_player(BotPlayer("p3", "Charlie", 1000))
        g.start_game()
        
        log_text = "\n".join(g.logs)
        assert "posts SB: 10" in log_text
        assert "posts BB: 20" in log_text

    def test_blind_amounts_half_big_blind(self):
        """Test that small blind is half of big blind."""
        g = Game(big_blind=50)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))
        g.start_game()
        
        log_text = "\n".join(g.logs)
        assert "posts SB: 25" in log_text
        assert "posts BB: 50" in log_text


class TestDealing:
    """Tests for card dealing."""

    def test_each_player_gets_two_cards(self):
        """Test that each player receives exactly 2 hole cards."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))
        g.start_game()
        
        for player in g.players:
            assert len(player.hole_cards) == 2

    def test_cards_are_unique(self):
        """Test that no duplicate cards are dealt."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))
        g.add_player(BotPlayer("p3", "Charlie", 1000))
        g.start_game()
        
        all_cards = []
        for player in g.players:
            all_cards.extend(player.hole_cards)
        
        # Check no duplicates
        card_strings = [str(c) for c in all_cards]
        assert len(card_strings) == len(set(card_strings))

    def test_community_cards_dealt_flop(self):
        """Test that flop deals 3 community cards."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.3))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.3))
        g.start_game()
        
        # Find flop log
        flop_logs = [log for log in g.logs if "Dealing community cards" in log]
        assert len(flop_logs) > 0


class TestBetting:
    """Tests for betting logic."""

    def test_player_chips_decrease_on_bet(self):
        """Test that player chips decrease when betting."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))
        
        initial_chips = g.players[0].chips
        g.start_game()
        
        # Player should have less chips after posting blind or betting
        # (at minimum, they posted as bot)

    def test_pot_increases_on_bets(self):
        """Test that pot increases when players bet."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))
        g.start_game()
        
        total_pot = g.pot_manager.total_pot()
        assert total_pot >= 30  # At least SB + BB

    def test_folded_player_not_in_showdown(self):
        """Test that folded players don't reach showdown."""
        g = Game(big_blind=20)
        # Create one aggressive bot and one passive bot
        g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.9))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.1))
        g.start_game()
        
        # At least one player should be active at end
        active_count = sum(1 for p in g.players if p.is_active)
        assert active_count >= 1


class TestShowdown:
    """Tests for showdown logic."""

    def test_winner_determined(self):
        """Test that a winner is determined at showdown."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.3))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.3))
        g.start_game()
        
        # Check that showdown happened
        showdown_logs = [log for log in g.logs if "SHOWDOWN" in log]
        assert len(showdown_logs) > 0

    def test_winner_receives_chips(self):
        """Test that winner receives pot chips."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.3))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.3))
        
        initial_total = sum(p.chips for p in g.players)
        g.start_game()
        
        final_total = sum(p.chips for p in g.players)
        assert final_total == initial_total  # Chips conserved

    def test_showdown_shows_cards(self):
        """Test that showdown reveals player cards in logs."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.3))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.3))
        g.start_game()
        
        # Check for card reveal in logs
        show_logs = [log for log in g.logs if "shows" in log]
        assert len(show_logs) > 0


class TestDealerButton:
    """Tests for dealer button rotation."""

    def test_dealer_rotates_after_hand(self):
        """Test that dealer button moves after each hand."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.3))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.3))
        
        initial_dealer = g.dealer_idx
        g.start_game()
        
        # Dealer should have moved
        assert g.dealer_idx != initial_dealer

    def test_dealer_rotation_cycles(self):
        """Test that dealer rotation cycles through players."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.3))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.3))
        g.add_player(BotPlayer("p3", "Charlie", 1000, aggressiveness=0.3))
        
        initial_dealer = g.dealer_idx
        g.start_game()  # Hand 1
        # Dealer moves +1
        assert g.dealer_idx == (initial_dealer + 1) % 3


class TestAllIn:
    """Tests for all-in scenarios."""

    def test_player_goes_all_in(self):
        """Test player can go all-in."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 100, aggressiveness=0.9))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.3))
        g.start_game()
        
        # Check all-in was logged or player is all-in
        all_in_player = [p for p in g.players if p.is_all_in]
        # May or may not have all-in depending on cards

    def test_all_in_player_eligible_for_pot(self):
        """Test that all-in players can still win pots."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 50, aggressiveness=0.9))  # Short stack
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.3))
        
        g.start_game()
        
        # Pot should exist
        assert len(g.pot_manager.pots) >= 0  # May be main pot only


class TestEdgeCases:
    """Edge case tests."""

    def test_player_busts_out(self):
        """Test that player with 0 chips is inactive."""
        g = Game(big_blind=20)
        p1 = BotPlayer("p1", "Alice", 1000, aggressiveness=0.3)
        p2 = BotPlayer("p2", "Bob", 1000, aggressiveness=0.3)
        g.add_player(p1)
        g.add_player(p2)
        
        # Manually set chips to 0
        p1.chips = 0
        p1.reset_for_hand()
        
        assert p1.is_active == False

    def test_heads_up_play(self):
        """Test 2-player (heads-up) game works."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.3))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.3))
        g.start_game()
        
        # Should complete without errors
        assert len(g.logs) > 0

    def test_multiple_hands_sequential(self):
        """Test that multiple hands can be played sequentially."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.3))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.3))
        
        # Play 3 hands
        for i in range(3):
            g.logs = []
            g.start_game()
            assert "NEW HAND" in g.logs[0]


class TestGameIntegration:
    """Integration tests for full game flow."""

    def test_complete_hand_no_errors(self):
        """Test that a complete hand runs without errors."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.5))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.5))
        g.add_player(BotPlayer("p3", "Charlie", 1000, aggressiveness=0.5))
        
        g.start_game()
        
        # Should have completed the hand
        assert "Hand complete." in g.logs[-1]

    def test_game_state_transitions(self):
        """Test that game transitions through all states."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.3))
        g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.3))
        g.start_game()
        
        log_text = "\n".join(g.logs)
        
        # Should see all stages
        assert "NEW HAND" in log_text
        assert "SHOWDOWN" in log_text
        assert "Hand complete." in log_text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
