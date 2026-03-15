import os
from game import Game
from terminal import TerminalPlayer
from bot import BotPlayer
from strategies.simple import SimpleStrategy

def main():
    print("Welcome to Poker Terminal Game!")

    player_name = input("Enter your name: ").strip()
    if not player_name:
        player_name = "Player 1"

    MAX_BOTS = 10
    num_bots_str = input(f"How many bots? (default 3, max {MAX_BOTS}): ").strip()
    num_bots = 3
    if num_bots_str.isdigit():
        num_bots = min(int(num_bots_str), MAX_BOTS)

    starting_chips_str = input("Starting chips? (default 1000): ").strip()
    starting_chips = 1000
    if starting_chips_str.isdigit():
        starting_chips = int(starting_chips_str)

    big_blind_str = input("Big Blind? (default 20): ").strip()
    big_blind = 20
    if big_blind_str.isdigit():
        big_blind = int(big_blind_str)

    hands_per_level_str = input("Hands per blind level? (default 5): ").strip()
    hands_per_level = 5
    if hands_per_level_str.isdigit():
        hands_per_level = int(hands_per_level_str)

    ante_str = input("Enable ante? (y/n, default n): ").strip().lower()
    enable_ante = ante_str in ['y', 'yes']

    g = Game(big_blind=big_blind, hands_per_level=hands_per_level, ante=enable_ante, live_output=True)
    g.add_player(TerminalPlayer("h1", player_name, starting_chips))

    bot_names = ["Bot_Alice", "Bot_Bob", "Bot_Charlie", "Bot_Dave", "Bot_Eve",
                 "Bot_Frank", "Bot_Grace", "Bot_Hank", "Bot_Iris", "Bot_Jack"]
    # Varied personalities — cycles through archetypes for a diverse table
    strategy_pool = [
        SimpleStrategy(aggressiveness=0.6),
        SimpleStrategy(aggressiveness=0.3),
        SimpleStrategy(aggressiveness=0.7),
        SimpleStrategy(aggressiveness=0.4),
        SimpleStrategy(aggressiveness=0.5),
        SimpleStrategy(aggressiveness=0.8),
        SimpleStrategy(aggressiveness=0.35),
        SimpleStrategy(aggressiveness=0.65),
        SimpleStrategy(aggressiveness=0.45),
        SimpleStrategy(aggressiveness=0.55),
    ]
    for i in range(num_bots):
        g.add_player(BotPlayer(f"b{i}", bot_names[i], starting_chips, strategy_pool[i]))

    human = next(p for p in g.players if isinstance(p, TerminalPlayer))

    play_again = True
    while play_again:
        os.system('clear' if os.name == 'posix' else 'cls')
        g.start_game()
        g.logs = []

        # Offer rebuy to human if they busted this hand
        if human.chips == 0:
            ans = input(f"\nYou're out of chips! Rebuy for {starting_chips}? (y/n): ").strip().lower()
            if ans in ['y', 'yes']:
                human.chips = starting_chips
                g.stats[human.player_id]['starting_chips'] += starting_chips
                print(f"Rebought! You now have {starting_chips} chips.")

        active_players = [p for p in g.players if p.chips > 0]
        if len(active_players) <= 1:
            winner = active_players[0].name if active_players else "Nobody"
            print(f"\nGame Over! {winner} wins!")
            break

        ans = input("\nPlay another hand? (y/n): ").strip().lower()
        if ans not in ['y', 'yes', '']:
            play_again = False

    g.print_stats()
    print("Thanks for playing!")

if __name__ == "__main__":
    main()
