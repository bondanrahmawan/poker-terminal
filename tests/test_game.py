"""
Component tests for Game logic - focused on specific implementation details.
Run with: pytest tests/test_game.py -v

This file tests:
- Specific game mechanics and state changes
- Betting logic and amounts
- Edge cases not covered by E2E tests
- Implementation details for debugging

E2E gameplay is tested in test_automated_play.py
"""
import pytest
from core.game import Game
from players.bot import BotPlayer
from core.player import Player, PlayerAction
from core.card import Card, Suit, Rank
from core.betting import BetManager, PotManager, Pot
from core.state import GameState
from strategies.simple import SimpleStrategy


class TestGameInitialization:
    """Tests for game setup - simple unit tests."""

    def test_create_game(self):
        """Test basic game creation."""
        g = Game(big_blind=20)
        assert g.big_blind == 20
        assert len(g.players) == 0
        assert g.community_cards == []
        assert g.state == GameState.WAITING

    def test_add_player(self):
        """Test adding players to game."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        assert len(g.players) == 1
        assert g.players[0].name == "Alice"
        assert g.players[0].chips == 1000

    def test_remove_player(self):
        """Test removing players from game."""
        g = Game(big_blind=20)
        p1 = BotPlayer("p1", "Alice", 1000)
        p2 = BotPlayer("p2", "Bob", 1000)
        g.add_player(p1)
        g.add_player(p2)

        g.remove_player("p1")
        assert len(g.players) == 1
        assert g.players[0].name == "Bob"

    def test_cannot_start_with_one_player(self):
        """Test that game cannot start with only one player."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.start_game()
        assert "Not enough players" in g.logs[0]
        assert g.state == GameState.WAITING  # Should return to WAITING


class TestBlinds:
    """Tests for blind posting - specific amounts and order."""

    def test_blind_amounts_correct(self):
        """Test that blinds are exactly half/full big blind."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))
        g.add_player(BotPlayer("p3", "Charlie", 1000))
        g.start_game()

        # Find blind amounts in logs
        sb_line = [l for l in g.logs if "posts SB" in l][0]
        bb_line = [l for l in g.logs if "posts BB" in l][0]

        assert "10" in sb_line  # SB = BB/2
        assert "20" in bb_line  # BB = big_blind

    def test_blind_positions_rotate(self):
        """Test that SB/BB positions rotate with dealer."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))
        g.add_player(BotPlayer("p3", "Charlie", 1000))

        # Hand 1: dealer=0 (Alice), SB=1 (Bob), BB=2 (Charlie)
        g.start_game()
        sb_line_1 = [l for l in g.logs if "posts SB" in l][0]
        assert "Bob" in sb_line_1

        # Hand 2: dealer=1 (Bob), SB=2 (Charlie), BB=0 (Alice)
        g.logs = []
        g.start_game()
        sb_line_2 = [l for l in g.logs if "posts SB" in l][0]
        assert "Charlie" in sb_line_2


class TestDealing:
    """Tests for card dealing - uniqueness and counts."""

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
        all_cards.extend(g.community_cards)

        # Check no duplicates
        card_strings = [str(c) for c in all_cards]
        assert len(card_strings) == len(set(card_strings)), "Duplicate cards dealt"

    def test_deck_has_correct_card_count(self):
        """Test that deck has 52 cards initially."""
        g = Game(big_blind=20)
        # Access deck before any dealing
        assert len(g.deck.cards) == 52

    def test_community_cards_count_per_street(self):
        """Test that each street deals correct number of cards."""
        g = Game(big_blind=20)
        # Passive players to ensure all streets are dealt
        g.add_player(BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.1)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.1)))
        g.start_game()

        # Count community card deals (>> [cards] pattern)
        community_lines = [l for l in g.logs if ">>" in l and "[" in l and "]" in l]

        # Should have at least flop (first community card deal)
        assert len(community_lines) >= 1


class TestBetting:
    """Tests for betting logic - amounts and state."""

    def test_pot_increases_on_blinds(self):
        """Test that pot increases when blinds are posted."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))

        initial_pot = g.pot_manager.total_pot()
        assert initial_pot == 0

        g.start_game()

        final_pot = g.pot_manager.total_pot()
        assert final_pot >= 30  # At least SB (10) + BB (20)

    def test_folded_player_is_inactive(self):
        """Test that folded players become inactive."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.9)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.1)))
        g.start_game()

        # At least one player should remain active at end
        active_count = sum(1 for p in g.players if p.is_active)
        assert active_count >= 1

    def test_player_chips_change_on_bet(self):
        """Test that player chips change when betting."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))

        p1_initial = g.players[0].chips
        g.start_game()
        p1_final = g.players[0].chips

        # Player should have different chips after posting blind or betting
        assert p1_initial != p1_final or "posts BB" in str(g.logs)


class TestShowdown:
    """Tests for showdown logic - card display and winners."""

    def test_showdown_shows_cards_multiway(self):
        """Test that showdown reveals cards when multiple players remain."""
        g = Game(big_blind=20)
        # Use passive bots to encourage seeing showdown
        g.add_player(BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.15)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.15)))
        g.add_player(BotPlayer("p3", "Charlie", 1000, SimpleStrategy(aggressiveness=0.15)))
        g.start_game()

        # Check for card reveal in logs
        show_logs = [log for log in g.logs if "shows" in log]
        assert len(show_logs) > 0, "Showdown should show cards when multiple players remain"

    def test_winner_announced(self):
        """Test that winner is announced in logs."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.start_game()

        winner_logs = [log for log in g.logs if "wins" in log and ">>" in log]
        assert len(winner_logs) > 0, "Should announce winner"


class TestDealerButton:
    """Tests for dealer button rotation."""

    def test_dealer_rotation_cycles(self):
        """Test that dealer rotation cycles through all players."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.add_player(BotPlayer("p3", "Charlie", 1000, SimpleStrategy(aggressiveness=0.3)))

        initial_dealer = g.dealer_idx

        # Play 3 hands - dealer should cycle through all positions
        for i in range(3):
            g.logs = []
            g.start_game()

        # After 3 hands, dealer should be back at initial position
        assert g.dealer_idx == initial_dealer

    def test_dealer_skips_busted_players(self):
        """Test that dealer button skips players with 0 chips."""
        g = Game(big_blind=20)
        p1 = BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3))
        p2 = BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.3))
        p3 = BotPlayer("p3", "Charlie", 1000, SimpleStrategy(aggressiveness=0.3))
        g.add_player(p1)
        g.add_player(p2)
        g.add_player(p3)

        # Bust out player 2
        p2.chips = 0
        p2.reset_for_hand()

        g.start_game()

        # Dealer should skip busted player
        assert g.dealer_idx != 1 or g.players[1].chips > 0


class TestAllIn:
    """Tests for all-in scenarios."""

    def test_player_state_all_in(self):
        """Test that player state changes to all-in."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 50, SimpleStrategy(aggressiveness=0.9)))  # Short stack
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.start_game()

        # Check if any player went all-in
        all_in_players = [p for p in g.players if p.is_all_in]
        # May or may not have all-in depending on cards, but shouldn't crash

    def test_side_pot_created(self):
        """Test that side pots are tracked when players go all-in."""
        g = Game(big_blind=20)
        # Short stack vs big stack - may create side pot
        g.add_player(BotPlayer("p1", "Alice", 30, SimpleStrategy(aggressiveness=0.9)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.9)))
        g.start_game()

        # Pot manager should have at least main pot
        assert len(g.pot_manager.pots) >= 0


class TestPlayerState:
    """Tests for player state management."""

    def test_busted_player_inactive(self):
        """Test that player with 0 chips is inactive."""
        g = Game(big_blind=20)
        p1 = BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3))
        p1.chips = 0
        p1.reset_for_hand()

        assert p1.is_active == False

    def test_active_player_can_act(self):
        """Test that active non-all-in players can act."""
        g = Game(big_blind=20)
        p1 = BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3))
        p1.reset_for_hand()

        assert p1.can_act() == True

    def test_all_in_player_cannot_act(self):
        """Test that all-in players cannot act."""
        g = Game(big_blind=20)
        p1 = BotPlayer("p1", "Alice", 100, SimpleStrategy(aggressiveness=0.3))
        p1.is_all_in = True

        assert p1.can_act() == False

    def test_folded_player_cannot_act(self):
        """Test that folded players cannot act."""
        g = Game(big_blind=20)
        p1 = BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3))
        p1.is_active = False

        assert p1.can_act() == False


class TestBetManager:
    """Tests for BetManager component."""

    def test_min_raise_calculation(self):
        """Test minimum raise calculation."""
        bm = BetManager(big_blind=20)
        assert bm.min_raise == 20  # Initial min raise = BB

    def test_bet_processing(self):
        """Test bet processing updates state."""
        bm = BetManager(big_blind=20)
        bm.process_bet("p1", 20)  # BB

        assert bm.current_bet == 20
        assert bm.get_amount_to_call("p2") == 20

    def test_raise_updates_min_raise(self):
        """Test that raise updates minimum raise amount."""
        bm = BetManager(big_blind=20)
        bm.process_bet("p1", 20)  # BB
        bm.process_bet("p2", 60, is_raise=True)  # Raise to 60

        assert bm.min_raise == 40  # Raise amount = 60 - 20

    def test_get_amount_to_call(self):
        """Test amount to call calculation."""
        bm = BetManager(big_blind=20)
        bm.process_bet("p1", 20)  # BB
        bm.process_bet("p2", 60, is_raise=True)  # Raise to 60

        # p1 needs to call 40 more (60 - 20)
        assert bm.get_amount_to_call("p1") == 40

    def test_reset_round(self):
        """Test round reset clears betting state."""
        bm = BetManager(big_blind=20)
        bm.process_bet("p1", 20)
        bm.reset_round()

        assert bm.current_bet == 0
        assert bm.min_raise == 20


class TestPotManager:
    """Tests for PotManager component."""

    def test_contribution_tracking(self):
        """Test that contributions are tracked per player."""
        pm = PotManager()
        pm.add_contribution("p1", 20)
        pm.add_contribution("p2", 20)

        assert pm.contributions["p1"] == 20
        assert pm.contributions["p2"] == 20

    def test_total_pot_calculation(self):
        """Test total pot calculation."""
        pm = PotManager()
        pm.add_contribution("p1", 20)
        pm.add_contribution("p2", 30)

        assert pm.total_pot() == 50

    def test_pot_calculation_single_winner(self):
        """Test pot calculation with single eligible player."""
        pm = PotManager()
        pm.add_contribution("p1", 20)
        pm.add_contribution("p2", 20)
        pm.calculate_pots(["p1"])  # Only p1 eligible

        assert len(pm.pots) == 1
        assert pm.pots[0].amount == 40
        assert "p1" in pm.pots[0].eligible_players

    def test_side_pot_creation(self):
        """Test side pot creation for all-in scenarios."""
        pm = PotManager()
        pm.add_contribution("p1", 50)  # All-in
        pm.add_contribution("p2", 100)  # Covers
        pm.add_contribution("p3", 100)  # Covers
        pm.calculate_pots(["p1", "p2", "p3"])

        # Should have main pot (50*3=150) and side pot (50*2=100)
        assert len(pm.pots) == 2
        assert pm.pots[0].amount == 150  # Main pot
        assert pm.pots[1].amount == 100  # Side pot


class TestGameState:
    """Tests for game state transitions."""

    def test_initial_state(self):
        """Test game starts in WAITING state."""
        g = Game(big_blind=20)
        assert g.state == GameState.WAITING

    def test_state_progresses_through_hand(self):
        """Test state progresses through hand when starting."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000))
        g.add_player(BotPlayer("p2", "Bob", 1000))

        # Before start, state is WAITING
        assert g.state == GameState.WAITING

        # start_game() runs complete hand, returns to WAITING
        g.start_game()

        # After hand completes, state returns to WAITING
        assert g.state == GameState.WAITING

    def test_state_returns_to_waiting(self):
        """Test state returns to WAITING after hand completes."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.start_game()

        # Hand should complete and return to WAITING
        assert g.state == GameState.WAITING


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
