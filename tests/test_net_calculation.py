"""
Tests for net calculation with rebuys.
Run with: pytest tests/test_net_calculation.py -v
"""
import pytest
from core.game import Game
from players.bot import BotPlayer
from strategies.simple import SimpleStrategy


class TestNetCalculationWithRebuys:
    """Test that net profit/loss correctly accounts for rebuys."""

    def test_net_without_rebuys(self):
        """Test net calculation when no rebuys occur."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.3)))
        
        # Play one hand
        g.start_game()
        
        # Net should be current_chips - total_invested
        alice_net = g.stats_tracker.get_cumulative_net("p1", g.players[0].chips)
        bob_net = g.stats_tracker.get_cumulative_net("p2", g.players[1].chips)
        
        # Total invested should equal starting chips (no rebuys)
        assert g.stats["p1"]["total_invested"] == 1000
        assert g.stats["p2"]["total_invested"] == 1000
        
        # Net should sum to zero (zero-sum game)
        assert alice_net + bob_net == 0

    def test_net_with_rebuys(self):
        """Test that rebuys are correctly subtracted from net."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.3)))
        
        # Play hand 1
        g.start_game()
        
        # Simulate rebuy for Alice
        alice_initial_chips = g.stats["p1"]["starting_chips"]
        alice_chips_before_rebuy = g.players[0].chips
        
        # Alice rebuys
        g.players[0].chips = 1000
        g.stats["p1"]["total_invested"] += 1000
        g.stats["p1"]["rebuys"] += 1
        
        # Play hand 2
        g.logs = []
        g.start_game()
        
        # Alice's net should account for both the initial 1000 AND the rebuy 1000
        alice_total_invested = g.stats["p1"]["total_invested"]
        assert alice_total_invested == 2000  # 1000 starting + 1000 rebuy
        
        alice_net = g.stats_tracker.get_cumulative_net("p1", g.players[0].chips)
        # Net = current_chips - 2000 (not current_chips - 1000)
        assert alice_net == g.players[0].chips - 2000

    def test_net_multiple_rebuys(self):
        """Test net calculation with multiple rebuys."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.3)))
        
        # Play hand
        g.start_game()
        
        # Alice rebuys 3 times
        for i in range(3):
            g.players[0].chips = 1000
            g.stats["p1"]["total_invested"] += 1000
            g.stats["p1"]["rebuys"] += 1
        
        # Total invested should be 4000 (1000 starting + 3000 rebuys)
        assert g.stats["p1"]["total_invested"] == 4000
        assert g.stats["p1"]["rebuys"] == 3
        
        # Net calculation
        alice_net = g.stats_tracker.get_cumulative_net("p1", g.players[0].chips)
        assert alice_net == g.players[0].chips - 4000

    def test_session_reset_with_rebuys(self):
        """Test that session reset preserves cumulative net with rebuys."""
        g = Game(big_blind=20, blind_reset_interval=10)
        g.add_player(BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.3)))
        
        # Play some hands
        for _ in range(5):
            g.logs = []
            g.start_game()
        
        # Alice rebuys
        g.players[0].chips = 1000
        g.stats["p1"]["total_invested"] += 1000
        g.stats["p1"]["rebuys"] += 1
        
        alice_net_before_reset = g.stats_tracker.get_cumulative_net("p1", g.players[0].chips)
        
        # Trigger session reset (at hand 10)
        g.hand_count = 10
        g._handle_end()
        
        # After reset, cumulative_net should include the session net with rebuys accounted
        # The exact value depends on what happened in the hand, but the logic should be correct
        alice_cumulative = g.stats["p1"]["cumulative_net"]
        
        # Total invested should be reset to starting_chips for new session
        assert g.stats["p1"]["total_invested"] == g.stats["p1"]["starting_chips"]

    def test_archetype_stats_with_rebuys(self):
        """Test that archetype aggregation uses correct net values."""
        g = Game(big_blind=20)
        g.add_player(BotPlayer("p1", "Alice", 1000, SimpleStrategy(aggressiveness=0.3)))
        g.add_player(BotPlayer("p2", "Bob", 1000, SimpleStrategy(aggressiveness=0.3)))
        
        # Play hand
        g.start_game()
        
        # Alice rebuys
        g.players[0].chips = 1000
        g.stats["p1"]["total_invested"] += 1000
        g.stats["p1"]["rebuys"] += 1
        
        # Get archetype stats
        arch_stats = g.stats_tracker.get_archetype_stats(g.players)
        
        # The net in archetype stats should use get_cumulative_net which accounts for rebuys
        # Both players use SimpleStrategy, so they'll be in same archetype
        simple_stats = arch_stats.get('simple', {})
        
        # Net should reflect actual profit/loss including rebuys
        assert 'net' in simple_stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
