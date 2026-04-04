import os
import time
from core.game import Game
from players.terminal import TerminalPlayer
from players.roster import create_bots, MAX_BOTS
from strategies.difficulty import EASY, NORMAL, HARD


def _prompt_int(prompt: str, default: int, min_val: int = 1) -> int:
    raw = input(prompt).strip()
    return max(min_val, int(raw)) if raw.isdigit() else default


def _prompt_yn(prompt: str, default: bool = False) -> bool:
    """Prompt user for yes/no response with configurable default."""
    # Show default in prompt: (y/n, default y) or (y/n, default n)
    raw = input(prompt).strip().lower()
    return raw in ['y', 'yes'] if raw else default


def _collect_settings():
    """Collect all game settings interactively. Returns a settings dict."""
    print("\nGame Mode:")
    print("  1. Tournament  (blinds escalate each level)")
    print("  2. Cash Game   (fixed blinds, unlimited rebuys)")
    print("  3. Spectator   (watch bots play)")
    print("  4. Simulation  (auto-run N hands, then show stats)")
    mode_input = input("Choose (default 1): ").strip()
    if mode_input == '2':
        game_mode = 'cash'
        spectator = False
        batch_hands = 0
    elif mode_input == '3':
        game_mode = 'tournament'
        spectator = True
        batch_hands = 0
    elif mode_input == '4':
        game_mode = 'tournament'
        spectator = True
        batch_hands = _prompt_int("Number of hands to simulate? (default 50): ", 50, min_val=1)
        sim_speed = input("Simulation speed: 1=Instant, 2=Fast, 3=Normal (default 1): ").strip()
        sim_delay = {'2': 0.3, '3': 0.8}.get(sim_speed, 0.0)
    else:
        game_mode = 'tournament'
        spectator = False
        batch_hands = 0
        sim_delay = 0.0

    short_deck = _prompt_yn("Short deck (6+ cards, Flush > Full House)? (y/n, default n): ")

    player_name = "Player 1"
    if not spectator:
        player_name = input("Enter your name (default Player 1): ").strip() or "Player 1"

    num_bots = _prompt_int(f"How many bots? (default 3, max {MAX_BOTS}): ", 3)
    num_bots = min(num_bots, MAX_BOTS)

    print("\nTable difficulty:")
    print("  1. Easy    (bots make more mistakes)")
    print("  2. Normal  (default)")
    print("  3. Hard    (bots play sharper)")
    diff_input = input("Choose (default 2): ").strip()
    difficulty = {1: EASY, '1': EASY, 3: HARD, '3': HARD}.get(diff_input, NORMAL)

    shuffle_bots = _prompt_yn("Randomise bot seating? (y/n, default y): ", default=True)

    starting_chips = _prompt_int("Starting chips? (default 1000): ", 1000)
    big_blind = _prompt_int("Big Blind? (default 20): ", 20)

    if game_mode == 'tournament':
        print("\nBlind schedule:")
        print("  1. Normal  (5 hands per level)")
        print("  2. Turbo   (2 hands per level)")
        turbo = input("Choose (default 1): ").strip()
        hands_per_level = 2 if turbo == '2' else _prompt_int(
            "Hands per blind level? (default 5): ", 5)
    else:
        hands_per_level = 9999

    enable_ante = _prompt_yn("Enable ante? (y/n, default n): ")

    return {
        'game_mode': game_mode,
        'spectator': spectator,
        'batch_hands': batch_hands,
        'sim_delay': sim_delay,
        'short_deck': short_deck,
        'player_name': player_name,
        'num_bots': num_bots,
        'difficulty': difficulty,
        'shuffle_bots': shuffle_bots,
        'starting_chips': starting_chips,
        'big_blind': big_blind,
        'hands_per_level': hands_per_level,
        'enable_ante': enable_ante,
    }


def _build_game(settings: dict) -> tuple:
    """Create a fresh Game instance and players. Returns (game, human_player)."""
    g = Game(
        big_blind=settings['big_blind'],
        hands_per_level=settings['hands_per_level'],
        ante=settings['enable_ante'],
        live_output=True,
        game_mode=settings['game_mode'],
        short_deck=settings['short_deck'],
    )

    human = None
    if not settings['spectator']:
        g.add_player(TerminalPlayer("h1", settings['player_name'], settings['starting_chips']))
        human = next(p for p in g.players if isinstance(p, TerminalPlayer))

    for bot in create_bots(
        settings['num_bots'], settings['starting_chips'],
        difficulty=settings['difficulty'], shuffled=settings['shuffle_bots'],
    ):
        g.add_player(bot)

    return g, human


def _run_session(g: Game, human, settings: dict):
    """Run hands until the user quits or the session ends."""
    hands_simulated = 0

    while True:
        # Only clear screen for human interactive modes (tournament/cash)
        if settings['batch_hands'] == 0 and not settings['spectator']:
            os.system('clear' if os.name == 'posix' else 'cls')

        g.start_game()

        # Track simulated hands
        if settings['batch_hands'] > 0:
            hands_simulated += 1
            if settings['sim_delay'] > 0:
                time.sleep(settings['sim_delay'])

        # Human rebuy
        if human and human.chips == 0:
            ans = input(
                f"\nYou're out of chips! Rebuy for {settings['starting_chips']}? (y/n): "
            ).strip().lower()
            if ans in ['y', 'yes']:
                human.chips = settings['starting_chips']
                g.stats[human.player_id]['starting_chips'] += settings['starting_chips']
                g.stats[human.player_id]['rebuys'] += 1
                print(f"Rebought! You now have {settings['starting_chips']} chips.")

        # Cash game auto-rebuy for bots
        elif settings['game_mode'] == 'cash':
            for p in g.players:
                if p.chips == 0 and not isinstance(p, TerminalPlayer):
                    p.chips = settings['starting_chips']
                    g.stats[p.player_id]['starting_chips'] += settings['starting_chips']
                    g.stats[p.player_id]['rebuys'] += 1

        active_players = [p for p in g.players if p.chips > 0]

        # Batch mode: auto-rebuy and continue
        if settings['batch_hands'] > 0:
            for p in g.players:
                if p.chips == 0:
                    p.chips = settings['starting_chips']
                    g.stats[p.player_id]['starting_chips'] += settings['starting_chips']
                    g.stats[p.player_id]['rebuys'] += 1
            if hands_simulated >= settings['batch_hands']:
                break
            # Show progress every 10 hands
            if hands_simulated % 10 == 0:
                print(
                    f"\n--- Simulating hands "
                    f"{hands_simulated + 1}-{min(hands_simulated + 10, settings['batch_hands'])} ---"
                )
            continue

        # Spectator mode
        if settings['spectator']:
            if len(active_players) <= 1:
                winner = active_players[0].name if active_players else "Nobody"
                print(f"\nGame Over! {winner} wins!")
                break
            ans = input("\nNext hand? (Enter to continue, q to quit): ").strip().lower()
            if ans == 'q':
                break
            continue

        # Human mode
        if len(active_players) <= 1:
            winner = active_players[0].name if active_players else "Nobody"
            print(f"\nGame Over! {winner} wins!")
            break
        ans = input("\nPlay another hand? (y/n): ").strip().lower()
        if ans not in ['y', 'yes', '']:
            break


def _print_stats_and_summary(g: Game, settings: dict, hands_simulated: int):
    """Print session stats and a quick summary."""
    g.print_stats()

    if settings['batch_hands'] > 0:
        print(f"\nSimulation complete: {hands_simulated} hands played")
        print("\n--- Simulation Summary ---")
        sorted_players = sorted(g.players, key=lambda p: p.chips, reverse=True)
        if sorted_players:
            winner = sorted_players[0]
            print(f"  Top earner: {winner.name} ({winner.chips} chips)")
            best_hand = max(g.stats.values(), key=lambda x: x['best_hand_rank'])
            print(f"  Best hand: {best_hand['best_hand_name']}")
            total_rebuys = sum(s.get('rebuys', 0) for s in g.stats.values())
            print(f"  Total rebuys: {total_rebuys}")


def main():
    print("=" * 50)
    print("  Welcome to Poker Terminal!")
    print("=" * 50)

    settings = None
    session_num = 0

    while True:
        session_num += 1

        # Collect settings on first run or when user chooses to change them
        if settings is None:
            if session_num > 1:
                print(f"\n{'=' * 50}")
                print(f"  Session #{session_num} — Same Settings")
                print(f"{'=' * 50}")
            settings = _collect_settings()
        else:
            # Reuse existing settings for replay
            if session_num > 1:
                print(f"\n{'=' * 50}")
                print(f"  Session #{session_num} — Replaying with same settings")
                print(f"{'=' * 50}")

        g, human = _build_game(settings)
        _run_session(g, human, settings)

        hands_simulated = settings['batch_hands'] if settings['batch_hands'] > 0 else g.hand_count
        _print_stats_and_summary(g, settings, hands_simulated)

        print("\n" + "-" * 40)
        ans = input(
            "Play again with same settings? (y/n, r to change settings): "
        ).strip().lower()
        if ans == 'r':
            settings = None  # Force re-prompt on next iteration
            continue
        if ans not in ['y', 'yes']:
            break

    print("Thanks for playing!")


if __name__ == "__main__":
    main()
