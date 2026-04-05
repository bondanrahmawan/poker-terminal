"""
Tests for UX improvements - input validation, opponent action feed, bet cancellation.
Run with: pytest tests/test_ux_improvements.py -v
"""
import pytest
from unittest.mock import patch, MagicMock
from players.terminal import TerminalPlayer
from core.player import PlayerAction
from core.card import Card, Suit, Rank


class TestInputValidation:
    """Tests for improved input validation in main.py."""

    @patch('builtins.input')
    def test_prompt_int_valid_input(self, mock_input):
        """Test _prompt_int with valid numeric input."""
        from main import _prompt_int
        
        mock_input.return_value = '5'
        result = _prompt_int("Enter number: ", 3)
        assert result == 5

    @patch('builtins.input')
    def test_prompt_int_empty_uses_default(self, mock_input):
        """Test _prompt_int uses default on empty input."""
        from main import _prompt_int
        
        mock_input.return_value = ''
        result = _prompt_int("Enter number: ", 3)
        assert result == 3

    @patch('builtins.input', side_effect=['abc', '5'])
    @patch('builtins.print')
    def test_prompt_int_invalid_then_valid(self, mock_print, mock_input):
        """Test _prompt_int rejects invalid then accepts valid."""
        from main import _prompt_int
        
        result = _prompt_int("Enter number: ", 3)
        assert result == 5
        # Should have printed error message
        assert any('Invalid input' in str(call) for call in mock_print.call_args_list)

    @patch('builtins.input', side_effect=['-5', '5'])
    @patch('builtins.print')
    def test_prompt_int_below_min_rejected(self, mock_print, mock_input):
        """Test _prompt_int rejects values below minimum."""
        from main import _prompt_int
        
        result = _prompt_int("Enter number: ", 3, min_val=1)
        assert result == 5
        assert any('too low' in str(call).lower() for call in mock_print.call_args_list)

    @patch('builtins.input', side_effect=['15', '10'])
    @patch('builtins.print')
    def test_prompt_int_above_max_rejected(self, mock_print, mock_input):
        """Test _prompt_int rejects values above maximum."""
        from main import _prompt_int
        
        result = _prompt_int("Enter number: ", 5, min_val=1, max_val=12)
        assert result == 10
        assert any('too high' in str(call).lower() for call in mock_print.call_args_list)

    @patch('builtins.input')
    def test_prompt_player_name_valid(self, mock_input):
        """Test _prompt_player_name with valid input."""
        from main import _prompt_player_name
        
        mock_input.return_value = 'Alice'
        result = _prompt_player_name()
        assert result == 'Alice'

    @patch('builtins.input')
    def test_prompt_player_name_empty_uses_default(self, mock_input):
        """Test _prompt_player_name uses default on empty input."""
        from main import _prompt_player_name
        
        mock_input.return_value = ''
        result = _prompt_player_name(default='Bob')
        assert result == 'Bob'

    @patch('builtins.input', side_effect=['Name with space', 'Test'])
    def test_prompt_player_name_spaces_allowed(self, mock_input):
        """Test _prompt_player_name allows spaces."""
        from main import _prompt_player_name
        
        result = _prompt_player_name()
        assert result == 'Name with space'  # 15 chars, within limit

    @patch('builtins.input', side_effect=['a' * 20, 'Short'])
    @patch('builtins.print')
    def test_prompt_player_name_too_long_rejected(self, mock_print, mock_input):
        """Test _prompt_player_name rejects names exceeding max length."""
        from main import _prompt_player_name
        
        result = _prompt_player_name(max_length=15)
        assert result == 'Short'
        assert any('too long' in str(call).lower() for call in mock_print.call_args_list)

    @patch('builtins.input', side_effect=['Bad@Name!', 'GoodName'])
    @patch('builtins.print')
    def test_prompt_player_name_special_chars_rejected(self, mock_print, mock_input):
        """Test _prompt_player_name rejects special characters."""
        from main import _prompt_player_name
        
        result = _prompt_player_name()
        assert result == 'GoodName'
        assert any('invalid characters' in str(call).lower() for call in mock_print.call_args_list)


class TestOpponentActionFeed:
    """Tests for real-time opponent action feed in TerminalPlayer."""

    def test_terminal_player_has_log_counter(self):
        """Test TerminalPlayer tracks log count."""
        player = TerminalPlayer("h1", "Human", 1000)
        assert hasattr(player, '_last_log_count')
        assert player._last_log_count == 0

    def test_show_recent_actions_filters_relevant(self):
        """Test action feed filters for relevant poker actions."""
        player = TerminalPlayer("h1", "Human", 1000)
        
        hand_log = [
            "Alice          fold                        0    Pot: 30",
            "Dealing cards to players",
            "Bob            raise                      60    Pot: 90",
            "--- FLOP ---",
            "Some irrelevant message",
        ]
        
        import io
        import sys
        captured = io.StringIO()
        sys.stdout = captured
        
        player._show_recent_actions(hand_log)
        
        sys.stdout = sys.__stdout__
        output = captured.getvalue()
        
        # Should show fold, raise, and FLOP
        assert 'fold' in output
        assert 'raise' in output
        assert 'FLOP' in output
        # Should NOT show irrelevant message
        assert 'irrelevant' not in output
        # Counter should update
        assert player._last_log_count == len(hand_log)

    def test_show_recent_actions_empty(self):
        """Test action feed handles empty log."""
        player = TerminalPlayer("h1", "Human", 1000)
        
        import io
        import sys
        captured = io.StringIO()
        sys.stdout = captured
        
        player._show_recent_actions([])
        
        sys.stdout = sys.__stdout__
        output = captured.getvalue()
        
        # Should not print anything
        assert output.strip() == ''


class TestBetCancellation:
    """Tests for bet sub-loop cancellation."""

    @patch('builtins.print')
    def test_bet_cancel_returns_to_main(self, mock_print):
        """Test 'cancel' input exits bet sub-loop."""
        player = TerminalPlayer("h1", "Human", 1000)
        player.hole_cards = [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.SPADES)]
        
        game_state = {
            'min_call': 20,
            'min_raise': 20,
            'pot_size': 60,
            'community_cards': [],
            'hand_log': [],
            'player_role': 'BTN',
            'players_info': [('Human', 1000, True), ('Bot', 1000, True)],
        }
        
        # Mock input to: choose 'raise', then cancel, then fold (to exit main loop)
        with patch.object(player, '_show_recent_actions'):
            with patch('builtins.input', side_effect=['r', 'cancel', 'f']):
                action, amt = player.get_action(game_state)
        
        # After cancel, user chose fold
        assert action == PlayerAction.FOLD
        assert amt == 0
        # Verify the cancel message was printed
        assert any('cancelled' in str(call).lower() for call in mock_print.call_args_list)


class TestPotOddsDisplay:
    """Tests for pot odds visibility."""

    def test_pot_odds_shown_when_calling(self):
        """Test pot odds are displayed when facing a bet."""
        player = TerminalPlayer("h1", "Human", 1000)
        player.hole_cards = [Card(Rank.ACE, Suit.SPADES), Card(Rank.KING, Suit.SPADES)]
        
        game_state = {
            'min_call': 40,
            'min_raise': 20,
            'pot_size': 100,
            'community_cards': [Card(Rank.QUEEN, Suit.HEARTS)],
            'hand_log': [],
            'player_role': 'BTN',
            'players_info': [('Human', 1000, True), ('Bot', 1000, True)],
        }
        
        import io
        import sys
        captured = io.StringIO()
        sys.stdout = captured
        
        with patch.object(player, '_show_recent_actions'):
            with patch('builtins.input', side_effect=['f']):
                try:
                    player.get_action(game_state)
                except:
                    pass
        
        sys.stdout = sys.__stdout__
        output = captured.getvalue()
        
        # Should show pot odds
        assert 'Pot odds' in output
        # Should show the ratio
        assert '2.5:1' in output or '40.0%' in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
