import os
from game import Game
from terminal import TerminalPlayer
from bot import BotPlayer

def main():
    print("Welcome to Poker Terminal Game!")
    
    player_name = input("Enter your name: ").strip()
    if not player_name:
        player_name = "Player 1"
        
    num_bots_str = input("How many bots? (default 3): ").strip()
    num_bots = 3
    if num_bots_str.isdigit():
        num_bots = int(num_bots_str)
        
    starting_chips_str = input("Starting chips? (default 1000): ").strip()
    starting_chips = 1000
    if starting_chips_str.isdigit():
        starting_chips = int(starting_chips_str)
        
    big_blind_str = input("Big Blind? (default 20): ").strip()
    big_blind = 20
    if big_blind_str.isdigit():
        big_blind = int(big_blind_str)

    g = Game(big_blind=big_blind, live_output=True)
    g.add_player(TerminalPlayer("h1", player_name, starting_chips))

    bot_names = ["Bot_Alice", "Bot_Bob", "Bot_Charlie", "Bot_Dave", "Bot_Eve", "Bot_Frank", "Bot_Grace"]
    for i in range(min(num_bots, len(bot_names))):
        g.add_player(BotPlayer(f"b{i}", bot_names[i], starting_chips))

    play_again = True
    while play_again:
        os.system('clear' if os.name == 'posix' else 'cls')
        g.start_game()
        g.logs = []  # Clear logs for next hand
        
        active_players = [p for p in g.players if p.chips > 0]
        if len(active_players) <= 1:
            print(f"\nGame Over! {active_players[0].name if active_players else 'Nobody'} wins!")
            break
            
        ans = input("\nPlay another hand? (y/n): ").strip().lower()
        if ans not in ['y', 'yes', '']:
            play_again = False

    print("Thanks for playing!")

if __name__ == "__main__":
    main()
