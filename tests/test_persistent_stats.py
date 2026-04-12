"""Test persistent stats functionality."""

import json
import tempfile
from pathlib import Path
from core.stats_persistent import PersistentStatsManager
from core.player import Player
from strategies.simple import SimpleStrategy


class MockPlayer(Player):
    """Mock player for testing."""
    
    def __init__(self, player_id: str, name: str, chips: int, is_bot: bool = False):
        super().__init__(player_id, name, chips)
        if is_bot:
            self.strategy = SimpleStrategy(aggressiveness=0.5)


def test_save_and_load_session():
    """Test saving and loading a session."""
    # Use a temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_file = Path(f.name)
    
    try:
        # Create persistent stats manager
        psm = PersistentStatsManager(stats_file=temp_file)
        
        # Create mock players
        players = [
            MockPlayer("h1", "Human Player", 1000, is_bot=False),
            MockPlayer("b1", "Bot 1", 1000, is_bot=True),
            MockPlayer("b2", "Bot 2", 1000, is_bot=True),
        ]
        
        # Simulate game stats
        game_stats = {
            'hand_count': 50,
            'h1': {
                'hands_played': 50,
                'hands_won': 20,
                'chips_won': 5000,
                'biggest_pot': 300,
                'best_hand_rank': 7,
                'best_hand_name': 'Flush',
                'bust_hand': None,
                'rebuys': 0,
                'starting_chips': 1000,
            },
            'b1': {
                'hands_played': 50,
                'hands_won': 15,
                'chips_won': 3000,
                'biggest_pot': 250,
                'best_hand_rank': 6,
                'best_hand_name': 'Full House',
                'bust_hand': None,
                'rebuys': 1,
                'starting_chips': 1000,
            },
            'b2': {
                'hands_played': 50,
                'hands_won': 15,
                'chips_won': 2000,
                'biggest_pot': 200,
                'best_hand_rank': 5,
                'best_hand_name': 'Straight',
                'bust_hand': 45,
                'rebuys': 2,
                'starting_chips': 1000,
            },
        }
        
        # Simulate some chip changes
        players[0].chips = 1500  # Human won 500
        players[1].chips = 800   # Bot 1 lost 200
        players[2].chips = 0     # Bot 2 busted
        
        # Save session
        psm.save_session(
            session_id=1,
            difficulty=0.6,  # Normal
            players=players,
            game_stats=game_stats,
            game_mode='tournament'
        )
        
        # Verify file was created
        assert temp_file.exists()
        
        # Load and verify data
        with open(temp_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert 'sessions' in data
        assert 'players' in data
        assert len(data['sessions']) == 1
        assert len(data['players']) == 3
        
        # Verify session data
        session = data['sessions'][0]
        assert session['session_id'] == 1
        assert session['difficulty'] == 'Normal'
        assert session['hands_played'] == 50
        assert len(session['players']) == 3
        
        # Verify player data
        assert 'h1' in data['players']
        assert data['players']['h1']['name'] == 'Human Player'
        assert 'Normal' in data['players']['h1']['sessions_by_difficulty']
        
        # Test retrieval
        history = psm.get_player_history('h1')
        assert history['player_id'] == 'h1'
        assert history['name'] == 'Human Player'
        assert 'Normal' in history['by_difficulty']
        
        # Test all players by difficulty
        all_by_diff = psm.get_all_players_by_difficulty()
        assert 'Normal' in all_by_diff
        assert len(all_by_diff['Normal']) == 3
        
        # Test session history
        sessions = psm.get_session_history()
        assert len(sessions) == 1
        
        # Test filtering by difficulty
        sessions_normal = psm.get_session_history(difficulty='Normal')
        assert len(sessions_normal) == 1
        
        sessions_hard = psm.get_session_history(difficulty='Hard')
        assert len(sessions_hard) == 0
        
        print("✓ All persistent stats tests passed!")
        
    finally:
        # Cleanup
        if temp_file.exists():
            temp_file.unlink()


def test_multiple_sessions():
    """Test multiple sessions accumulate correctly."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_file = Path(f.name)
    
    try:
        psm = PersistentStatsManager(stats_file=temp_file)
        
        # Create players for session 1
        players1 = [
            MockPlayer("h1", "Human Player", 1000, is_bot=False),
            MockPlayer("b1", "Bot 1", 1000, is_bot=True),
        ]
        
        game_stats1 = {
            'hand_count': 30,
            'h1': {
                'hands_played': 30,
                'hands_won': 15,
                'chips_won': 2000,
                'biggest_pot': 200,
                'best_hand_rank': 6,
                'best_hand_name': 'Full House',
                'bust_hand': None,
                'rebuys': 0,
                'starting_chips': 1000,
            },
            'b1': {
                'hands_played': 30,
                'hands_won': 15,
                'chips_won': 1000,
                'biggest_pot': 150,
                'best_hand_rank': 5,
                'best_hand_name': 'Straight',
                'bust_hand': None,
                'rebuys': 0,
                'starting_chips': 1000,
            },
        }
        
        players1[0].chips = 1200
        players1[1].chips = 800
        
        # Save session 1 (Normal difficulty)
        psm.save_session(
            session_id=1,
            difficulty=0.6,  # Normal
            players=players1,
            game_stats=game_stats1,
            game_mode='tournament'
        )
        
        # Create players for session 2
        players2 = [
            MockPlayer("h1", "Human Player", 1000, is_bot=False),
            MockPlayer("b1", "Bot 1", 1000, is_bot=True),
        ]
        
        game_stats2 = {
            'hand_count': 40,
            'h1': {
                'hands_played': 40,
                'hands_won': 18,
                'chips_won': 3000,
                'biggest_pot': 250,
                'best_hand_rank': 7,
                'best_hand_name': 'Flush',
                'bust_hand': None,
                'rebuys': 1,
                'starting_chips': 1000,
            },
            'b1': {
                'hands_played': 40,
                'hands_won': 22,
                'chips_won': 2500,
                'biggest_pot': 300,
                'best_hand_rank': 8,
                'best_hand_name': 'Four of a Kind',
                'bust_hand': None,
                'rebuys': 0,
                'starting_chips': 1000,
            },
        }
        
        players2[0].chips = 900
        players2[1].chips = 1100
        
        # Save session 2 (Hard difficulty)
        psm.save_session(
            session_id=2,
            difficulty=0.75,  # Hard
            players=players2,
            game_stats=game_stats2,
            game_mode='tournament'
        )
        
        # Verify both sessions saved
        with open(temp_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert len(data['sessions']) == 2
        
        # Verify player has data in both difficulties
        h1_data = data['players']['h1']
        assert 'Normal' in h1_data['sessions_by_difficulty']
        assert 'Hard' in h1_data['sessions_by_difficulty']
        assert len(h1_data['sessions_by_difficulty']['Normal']) == 1
        assert len(h1_data['sessions_by_difficulty']['Hard']) == 1
        
        # Test aggregation
        history = psm.get_player_history('h1')
        assert history['all_time']['total_sessions'] == 2
        assert history['all_time']['total_hands_played'] == 70
        assert 'Normal' in history['by_difficulty']
        assert 'Hard' in history['by_difficulty']
        
        # Test filtering
        history_normal = psm.get_player_history('h1', difficulty='Normal')
        assert len(history_normal['by_difficulty']) == 1
        assert 'Normal' in history_normal['by_difficulty']
        
        # Test all players by difficulty
        all_by_diff = psm.get_all_players_by_difficulty()
        assert len(all_by_diff) == 2  # Normal and Hard
        assert len(all_by_diff['Normal']) == 2  # h1 and b1
        assert len(all_by_diff['Hard']) == 2  # h1 and b1
        
        print("✓ Multiple sessions test passed!")
        
    finally:
        if temp_file.exists():
            temp_file.unlink()


if __name__ == '__main__':
    test_save_and_load_session()
    test_multiple_sessions()
    print("\n✅ All persistent stats tests completed successfully!")
