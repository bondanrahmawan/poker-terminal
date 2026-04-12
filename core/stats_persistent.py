"""PersistentStatsManager - Handles persistent storage of player statistics across sessions."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Stats file location (in the project root)
STATS_FILE = Path(__file__).parent.parent / "player_stats.json"


class SessionStats:
    """Represents statistics for a single game session."""
    
    def __init__(self, session_id: int, difficulty: str, date: str, 
                 hands_played: int, players: List[Dict], game_mode: str = 'tournament'):
        self.session_id = session_id
        self.difficulty = difficulty
        self.date = date
        self.hands_played = hands_played
        self.game_mode = game_mode
        self.players = players  # List of player stats dicts


class PersistentStatsManager:
    """Manages persistent storage and retrieval of player statistics by difficulty."""
    
    def __init__(self, stats_file: Path = STATS_FILE):
        self.stats_file = stats_file
        self._data = self._load_stats()
    
    def _load_stats(self) -> Dict:
        """Load stats from JSON file."""
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                print("Warning: Could not load stats file, starting fresh")
                return {'sessions': [], 'players': {}}
        return {'sessions': [], 'players': {}}
    
    def _save_stats(self):
        """Save stats to JSON file."""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"Error saving stats: {e}")
    
    def save_session(self, session_id: int, difficulty: float, players: List, 
                    game_stats: Dict, game_mode: str = 'tournament'):
        """
        Save a completed session's statistics.
        
        Args:
            session_id: Session number
            difficulty: Difficulty level (0.2-1.0)
            players: List of Player objects from the game
            game_stats: Dict containing game-level stats
            game_mode: 'tournament' or 'cash'
        """
        # Map difficulty to label
        difficulty_label = self._difficulty_to_label(difficulty)
        
        # Build player stats for this session
        player_stats = []
        for p in players:
            p_id = p.player_id
            s = game_stats.get(p_id, {})
            
            player_data = {
                'player_id': p_id,
                'name': p.name,
                'is_human': not hasattr(p, 'strategy') or p.strategy is None,
                'starting_chips': s.get('starting_chips', 0),
                'final_chips': p.chips,
                'hands_played': s.get('hands_played', 0),
                'hands_won': s.get('hands_won', 0),
                'chips_won': s.get('chips_won', 0),
                'biggest_pot': s.get('biggest_pot', 0),
                'best_hand_rank': s.get('best_hand_rank', 0),
                'best_hand_name': s.get('best_hand_name', '-'),
                'bust_hand': s.get('bust_hand'),
                'rebuys': s.get('rebuys', 0),
                'net_profit': p.chips - s.get('starting_chips', 0),
            }
            
            # Add strategy info for bots
            if hasattr(p, 'strategy') and p.strategy is not None:
                strategy = p.strategy
                profile = getattr(strategy, 'profile', None)
                if profile:
                    player_data['strategy'] = profile.name
                else:
                    player_data['strategy'] = 'simple'
            
            player_stats.append(player_data)
        
        # Create session record
        session_record = {
            'session_id': session_id,
            'difficulty': difficulty_label,
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'hands_played': game_stats.get('hand_count', 0),
            'game_mode': game_mode,
            'players': player_stats,
        }
        
        # Add to sessions list
        self._data['sessions'].append(session_record)
        
        # Update per-player persistent stats
        for ps in player_stats:
            p_id = ps['player_id']
            if p_id not in self._data['players']:
                self._data['players'][p_id] = {
                    'name': ps['name'],
                    'is_human': ps['is_human'],
                    'sessions_by_difficulty': {}
                }
            
            # Initialize difficulty bucket if needed
            if difficulty_label not in self._data['players'][p_id]['sessions_by_difficulty']:
                self._data['players'][p_id]['sessions_by_difficulty'][difficulty_label] = []
            
            # Add this session to the difficulty bucket
            self._data['players'][p_id]['sessions_by_difficulty'][difficulty_label].append({
                'session_id': session_id,
                'date': ps.get('date', session_record['date']),
                'hands_played': ps['hands_played'],
                'hands_won': ps['hands_won'],
                'starting_chips': ps['starting_chips'],
                'final_chips': ps['final_chips'],
                'net_profit': ps['net_profit'],
                'biggest_pot': ps['biggest_pot'],
                'best_hand_name': ps['best_hand_name'],
                'rebuys': ps['rebuys'],
                'strategy': ps.get('strategy', 'human'),
            })
        
        self._save_stats()
    
    def get_player_history(self, player_id: str, difficulty: Optional[str] = None) -> Dict:
        """
        Get a player's session history, optionally filtered by difficulty.
        
        Args:
            player_id: Player ID to look up
            difficulty: Optional difficulty filter ('Easy', 'Normal', 'Hard', etc.)
        
        Returns:
            Dict with player stats and session history
        """
        if player_id not in self._data['players']:
            return {}
        
        player_data = self._data['players'][player_id]
        result = {
            'player_id': player_id,
            'name': player_data['name'],
            'is_human': player_data['is_human'],
            'all_time': {},
            'by_difficulty': {},
        }
        
        # Calculate all-time stats
        all_sessions = []
        for diff, sessions in player_data['sessions_by_difficulty'].items():
            all_sessions.extend(sessions)
        
        if all_sessions:
            result['all_time'] = self._aggregate_sessions(all_sessions)
        
        # Calculate per-difficulty stats
        for diff, sessions in player_data['sessions_by_difficulty'].items():
            if difficulty is None or diff == difficulty:
                result['by_difficulty'][diff] = {
                    'sessions': sessions,
                    'stats': self._aggregate_sessions(sessions),
                }
        
        return result
    
    def get_all_players_by_difficulty(self, difficulty: Optional[str] = None) -> Dict[str, List[Dict]]:
        """
        Get all players grouped by difficulty level.
        
        Args:
            difficulty: Optional filter for specific difficulty
        
        Returns:
            Dict mapping difficulty labels to player stats
        """
        result = {}
        
        for p_id, p_data in self._data['players'].items():
            for diff, sessions in p_data['sessions_by_difficulty'].items():
                if difficulty is not None and diff != difficulty:
                    continue
                
                if diff not in result:
                    result[diff] = []
                
                aggregated = self._aggregate_sessions(sessions)
                aggregated['player_id'] = p_id
                aggregated['name'] = p_data['name']
                aggregated['is_human'] = p_data['is_human']
                aggregated['total_sessions'] = len(sessions)
                
                result[diff].append(aggregated)
        
        # Sort players by net profit within each difficulty
        for diff in result:
            result[diff].sort(key=lambda x: x.get('total_net', 0), reverse=True)
        
        return result
    
    def get_session_history(self, difficulty: Optional[str] = None) -> List[Dict]:
        """
        Get all session summaries, optionally filtered by difficulty.
        
        Args:
            difficulty: Optional difficulty filter
        
        Returns:
            List of session summary dicts
        """
        if difficulty is None:
            return self._data['sessions']
        
        return [s for s in self._data['sessions'] if s['difficulty'] == difficulty]
    
    def _aggregate_sessions(self, sessions: List[Dict]) -> Dict:
        """Aggregate statistics from multiple sessions."""
        if not sessions:
            return {}
        
        total_hands = sum(s['hands_played'] for s in sessions)
        total_won = sum(s['hands_won'] for s in sessions)
        total_net = sum(s['net_profit'] for s in sessions)
        total_rebuys = sum(s['rebuys'] for s in sessions)
        biggest_pot = max(s['biggest_pot'] for s in sessions)
        best_hands = [s['best_hand_name'] for s in sessions if s['best_hand_name'] != '-']
        
        return {
            'total_sessions': len(sessions),
            'total_hands_played': total_hands,
            'total_hands_won': total_won,
            'win_rate': (total_won / total_hands * 100) if total_hands > 0 else 0,
            'total_net': total_net,
            'avg_net_per_session': total_net / len(sessions),
            'total_rebuys': total_rebuys,
            'biggest_pot': biggest_pot,
            'best_hand': best_hands[0] if best_hands else '-',
        }
    
    @staticmethod
    def _difficulty_to_label(difficulty: float) -> str:
        """Convert difficulty float to human-readable label."""
        if difficulty <= 0.2:
            return 'Very Easy'
        elif difficulty <= 0.4:
            return 'Easy'
        elif difficulty <= 0.6:
            return 'Normal'
        elif difficulty <= 0.75:
            return 'Hard'
        elif difficulty <= 0.9:
            return 'Expert'
        else:
            return 'Perfect'
    
    @staticmethod
    def _label_to_difficulty(label: str) -> float:
        """Convert difficulty label to representative float value."""
        mapping = {
            'Very Easy': 0.2,
            'Easy': 0.4,
            'Normal': 0.6,
            'Hard': 0.75,
            'Expert': 0.9,
            'Perfect': 1.0,
        }
        return mapping.get(label, 0.6)
    
    def print_persistent_stats(self, difficulty: Optional[str] = None, 
                               player_id: Optional[str] = None):
        """
        Print persistent stats from all sessions.
        
        Args:
            difficulty: Optional filter for specific difficulty
            player_id: Optional filter for specific player
        """
        if player_id:
            # Show individual player history
            history = self.get_player_history(player_id, difficulty)
            if not history:
                print(f"\nNo history found for player: {player_id}")
                return
            
            self._print_player_history(history, difficulty)
        else:
            # Show all players by difficulty
            self._print_all_players_by_difficulty(difficulty)
    
    def _print_player_history(self, history: Dict, difficulty: Optional[str] = None):
        """Print detailed history for a single player."""
        print(f"\n{'=' * 80}")
        print(f"{'PLAYER HISTORY':^80}")
        print(f"{'=' * 80}")
        print(f"\nPlayer: {history['name']} ({history['player_id']})")
        print(f"Type: {'Human' if history['is_human'] else 'Bot'}")
        
        # All-time stats
        if history['all_time']:
            at = history['all_time']
            print(f"\n{'ALL-TIME STATS':^80}")
            print(f"{'─' * 80}")
            print(f"  Sessions: {at['total_sessions']:<10} Hands Played: {at['total_hands_played']:<10}")
            print(f"  Hands Won: {at['total_hands_won']:<10} Win Rate: {at['win_rate']:.1f}%")
            print(f"  Net Profit: {at['total_net']:+,}")
            print(f"  Avg Net/Session: {at['avg_net_per_session']:+,.0f}")
            print(f"  Total Rebuys: {at['total_rebuys']:<10} Biggest Pot: {at['biggest_pot']:,}")
            print(f"  Best Hand: {at['best_hand']}")
        
        # Per-difficulty breakdown
        if history['by_difficulty']:
            print(f"\n{'BY DIFFICULTY':^80}")
            print(f"{'─' * 80}")
            print(f"  {'Difficulty':<12} | {'Sessions':>8} | {'Hands':>8} | {'Win%':>7} | {'Net':>10} | {'Avg Net':>10}")
            print(f"  {'─' * 12}-+-{'─' * 8}-+-{'─' * 8}-+-{'─' * 7}-+-{'─' * 10}-+-{'─' * 10}")
            
            for diff, data in sorted(history['by_difficulty'].items()):
                stats = data['stats']
                net_str = f"+{stats['total_net']:,}" if stats['total_net'] > 0 else f"{stats['total_net']:,}"
                avg_str = f"+{stats['avg_net_per_session']:,.0f}" if stats['avg_net_per_session'] > 0 else f"{stats['avg_net_per_session']:,.0f}"
                print(f"  {diff:<12} | {stats['total_sessions']:>8} | {stats['total_hands_played']:>8} | {stats['win_rate']:>6.1f}% | {net_str:>10} | {avg_str:>10}")
    
    def _print_all_players_by_difficulty(self, difficulty: Optional[str] = None):
        """Print all players grouped by difficulty."""
        players_by_diff = self.get_all_players_by_difficulty(difficulty)
        
        if not players_by_diff:
            print(f"\nNo persistent stats found{' for ' + difficulty if difficulty else ''}")
            return
        
        print(f"\n{'=' * 128}")
        print(f"{'PERSISTENT PLAYER STATISTICS':^128}")
        if difficulty:
            print(f"{'Filtered by Difficulty: ' + difficulty:^128}")
        print(f"{'=' * 128}")
        
        for diff, players in sorted(players_by_diff.items()):
            print(f"\n{'─' * 128}")
            print(f"  DIFFICULTY: {diff} ({len(players)} players)")
            print(f"{'─' * 128}")
            print(f"  {'Rank':>4} | {'Name':<15} | {'Type':<6} | {'Sessions':>8} | {'Hands':>8} | {'Win%':>7} | {'Total Net':>11} | {'Avg Net':>10} | {'Rebuys':>7} | {'Best Hand':<15}")
            print(f"  {'─' * 4}-+-{'─' * 15}-+-{'─' * 6}-+-{'─' * 8}-+-{'─' * 8}-+-{'─' * 7}-+-{'─' * 11}-+-{'─' * 10}-+-{'─' * 7}-+-{'─' * 15}")
            
            for rank, p in enumerate(players, 1):
                net_str = f"+{p['total_net']:,}" if p['total_net'] > 0 else f"{p['total_net']:,}"
                avg_str = f"+{p['avg_net_per_session']:,.0f}" if p['avg_net_per_session'] > 0 else f"{p['avg_net_per_session']:,.0f}"
                type_str = 'Human' if p['is_human'] else 'Bot'
                
                print(f"  {rank:>4} | {p['name']:<15} | {type_str:<6} | {p['total_sessions']:>8} | {p['total_hands_played']:>8} | {p['win_rate']:>6.1f}% | {net_str:>11} | {avg_str:>10} | {p['total_rebuys']:>7} | {p['best_hand']:<15}")
