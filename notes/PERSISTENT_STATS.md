# Persistent Stats Feature

## Overview
The poker terminal now automatically saves statistics for all tournament sessions, separated by difficulty level. Stats persist across program restarts and can be viewed at any time.

## What's Tracked

### Per Session
- Session number and date
- Difficulty level (Very Easy, Easy, Normal, Hard, Expert, Perfect)
- Game mode (tournament)
- Total hands played
- All player statistics

### Per Player (for each session)
- Player name and ID (human vs bot)
- Starting and final chip counts
- Hands played and won
- Win rate
- Net profit/loss
- Biggest pot won
- Best hand achieved
- Number of rebuys
- Strategy type (for bots)

## How to Use

### Viewing Stats
1. Run the program: `python main.py`
2. Choose option **5. View Persistent Stats** from the main menu
3. Choose a view mode:
   - **Option 1**: All players grouped by difficulty
   - **Option 2**: Specific player's complete history
   - **Option 3**: Session history with filters

### Filtering by Difficulty
When viewing stats, you can filter by difficulty level:
- Very Easy (0.2)
- Easy (0.4)
- Normal (0.6)
- Hard (0.75)
- Expert (0.9)
- Perfect (1.0)

### Automatic Saving
Stats are automatically saved after each tournament session ends. You'll see a confirmation message:
```
Session stats saved to persistent storage.
```

## Data Storage

Stats are stored in a JSON file: `player_stats.json` in the project root directory.

### File Structure
```json
{
  "sessions": [
    {
      "session_id": 1,
      "difficulty": "Normal",
      "date": "2026-04-08 15:30:00",
      "hands_played": 50,
      "game_mode": "tournament",
      "players": [...]
    }
  ],
  "players": {
    "h1": {
      "name": "Player 1",
      "is_human": true,
      "sessions_by_difficulty": {
        "Normal": [...],
        "Hard": [...]
      }
    }
  }
}
```

## Features

### Aggregated Statistics
The system automatically calculates:
- Total sessions played
- Total hands played/won
- Overall win rate
- Total net profit/loss
- Average net per session
- Total rebuys
- Biggest pot across all sessions
- Best hand achieved

### Difficulty-Based Analysis
Compare performance across different difficulty levels to:
- Track improvement over time
- Identify which difficulty levels you perform best at
- See how bot strategies adapt to different difficulties

### Session History
Review past sessions to:
- See when you played
- How many hands were dealt
- How many players participated
- What difficulty level was used

## Example Use Cases

### Track Your Progress
```
View Option 2 → Select your name → See all-time stats
```
View your win rate and profit across all sessions at each difficulty level.

### Compare Bot Performance
```
View Option 1 → Select "Normal" → See all bot stats
```
Compare which bot strategies perform best at Normal difficulty.

### Analyze Session Patterns
```
View Option 3 → Filter by "Hard" → See all Hard difficulty sessions
```
Review how many hands you've played at Hard difficulty and overall trends.

## Technical Details

### Files Modified
- `main.py`: Added persistent stats integration and viewer menu option
- `core/stats_persistent.py`: New file containing PersistentStatsManager class
- `tests/test_persistent_stats.py`: New test file with comprehensive tests

### Key Classes

**PersistentStatsManager**
- `save_session()`: Saves completed session stats
- `get_player_history()`: Retrieves player history with optional difficulty filter
- `get_all_players_by_difficulty()`: Gets all players grouped by difficulty
- `get_session_history()`: Retrieves session summaries
- `print_persistent_stats()`: Displays formatted stats to terminal

### Backwards Compatibility
- All existing tests pass (219 tests)
- Existing game functionality unchanged
- Stats file created automatically on first tournament session

## Notes
- Only tournament mode sessions are saved (not cash games)
- Stats accumulate indefinitely - no automatic cleanup
- The JSON file can be manually edited or backed up
- Each player's history is tracked separately by difficulty level
