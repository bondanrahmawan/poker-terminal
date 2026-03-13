from game import Game
from bot import BotPlayer
import time

def test():
    g = Game(big_blind=20)
    g.add_player(BotPlayer("p1", "Alice", 1000, aggressiveness=0.8))
    g.add_player(BotPlayer("p2", "Bob", 1000, aggressiveness=0.4))
    
    # Run 1 hand
    g.start_game()
    for log in g.logs:
        print(log)

test()
