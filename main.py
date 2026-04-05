import os
import time
from core.game import Game
from players.terminal import TerminalPlayer
from players.roster import create_bots, MAX_BOTS
from strategies.difficulty import EASY, NORMAL, HARD


def _prompt_int(prompt: str, default: int, min_val: int = 1, max_val: int = None) -> int:
    """Prompt user for an integer value with validation and retry loop.
    
    Args:
        prompt: The prompt message to display
        default: Default value if user presses Enter
        min_val: Minimum allowed value (inclusive)
        max_val: Maximum allowed value (inclusive), or None for no limit
    
    Returns:
        Validated integer within [min_val, max_val] range
    """
    while True:
        raw = input(prompt).strip()
        
        # Empty input uses default
        if not raw:
            return default
        
        # Validate numeric
        try:
            value = int(raw)
        except ValueError:
            print(f"  Invalid input: '{raw}'. Please enter a number.")
            continue
        
        # Validate range
        if value < min_val:
            print(f"  Value too low. Minimum: {min_val}")
            continue
        
        if max_val is not None and value > max_val:
            print(f"  Value too high. Maximum: {max_val}")
            continue
        
        return value


def _prompt_player_name(default: str = "Player 1", max_length: int = 15) -> str:
    """Prompt user for their player name with validation.
    
    Args:
        default: Default name if user presses Enter
        max_length: Maximum allowed name length
    
    Returns:
        Validated player name
    """
    while True:
        raw = input(f"Enter your name (default {default}): ").strip()
        name = raw if raw else default
        
        # Validate length
        if len(name) > max_length:
            print(f"  Name too long ({len(name)} chars). Maximum: {max_length} chars.")
            continue
        
        # Validate characters (alphanumeric, spaces, underscores, hyphens only)
        import re
        if not re.match(r'^[\w\s\-]+$', name):
            print(f"  Invalid characters. Use only letters, numbers, spaces, underscores, or hyphens.")
            continue
        
        return name


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
        blind_reset = 0
    elif mode_input == '3':
        game_mode = 'tournament'
        spectator = True
        batch_hands = 0
        blind_reset = 0
    elif mode_input == '4':
        game_mode = 'tournament'
        spectator = True
        batch_hands = _prompt_int("Number of hands to simulate? (default 50): ", 50, min_val=1)
        sim_speed = input("Simulation speed: 1=Instant, 2=Fast, 3=Normal (default 1): ").strip()
        sim_delay = {'2': 0.3, '3': 0.8}.get(sim_speed, 0.0)
        # Blind reset interval for simulation mode
        blind_reset = _prompt_int("Reset blinds every N hands? (0=never, default 20): ", 20, min_val=0)
    else:
        game_mode = 'tournament'
        spectator = False
        batch_hands = 0
        sim_delay = 0.0
        blind_reset = 0

    short_deck = _prompt_yn("Short deck (6+ cards, Flush > Full House)? (y/n, default n): ")

    player_name = "Player 1"
    if not spectator:
        player_name = _prompt_player_name()

    num_bots = _prompt_int(f"How many bots? (default 3, max {MAX_BOTS}): ", 3, min_val=1, max_val=MAX_BOTS)

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
        'blind_reset_interval': blind_reset if mode_input == '4' else 0,
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
    # In simulation mode, suppress per-hand output
    is_simulation = settings.get('batch_hands', 0) > 0
    
    g = Game(
        big_blind=settings['big_blind'],
        hands_per_level=settings['hands_per_level'],
        ante=settings['enable_ante'],
        live_output=not is_simulation,  # Suppress output for simulation
        game_mode=settings['game_mode'],
        short_deck=settings['short_deck'],
        blind_reset_interval=settings.get('blind_reset_interval', 0),
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
                g.stats[human.player_id]['total_invested'] += settings['starting_chips']
                g.stats[human.player_id]['rebuys'] += 1
                print(f"Rebought! You now have {settings['starting_chips']} chips.")

        # Cash game auto-rebuy for bots
        elif settings['game_mode'] == 'cash':
            for p in g.players:
                if p.chips == 0 and not isinstance(p, TerminalPlayer):
                    p.chips = settings['starting_chips']
                    g.stats[p.player_id]['total_invested'] += settings['starting_chips']
                    g.stats[p.player_id]['rebuys'] += 1

        active_players = [p for p in g.players if p.chips > 0]

        # Batch mode: auto-rebuy and continue
        if settings['batch_hands'] > 0:
            for p in g.players:
                if p.chips == 0:
                    p.chips = settings['starting_chips']
                    g.stats[p.player_id]['total_invested'] += settings['starting_chips']
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


def _print_gini_coefficient(g: Game):
    """Print Gini coefficient analysis."""
    gini = g.stats_tracker.calculate_gini(g.players)
    print(f"\n  1. WEALTH CONCENTRATION (Gini Index): {gini:.3f}")
    if gini > 0.7:
        print(f"     → EXTREME inequality — Winner-take-all dynamics")
    elif gini > 0.4:
        print(f"     → HIGH inequality — Strategic dominance by few players")
    elif gini > 0.2:
        print(f"     → MODERATE inequality — Balanced competition")
    else:
        print(f"     → LOW inequality — Healthy strategic diversity")


def _print_archetype_analysis(g: Game):
    """Print strategy archetype performance analysis."""
    print(f"\n  2. STRATEGIC ARCHETYPE PERFORMANCE")
    arch_stats = g.stats_tracker.get_archetype_stats(g.players)
    print(f"  {'Archetype':<20} | {'Avg Net':>10} | {'Win Rate':>9} | {'Survival':>9} | {'Hands':>7}")
    print(f"  {'─' * 20}-+-{'─' * 10}-+-{'─' * 9}-+-{'─' * 9}-+-{'─' * 7}")

    sorted_arch = sorted(arch_stats.items(), key=lambda x: x[1]['net']/max(1, x[1]['count']), reverse=True)
    for label, data in sorted_arch:
        avg_net = data['net'] / max(1, data['count'])
        win_rate = (data['won'] / max(1, data['played'])) * 100
        print(f"  {label:<20} | {avg_net:>+10,.0f} | {win_rate:>8.1f}% | {data['survival_rate']:>8.0f}% | {data['played']:>7}")

    return sorted_arch


def _print_key_insights_simulation(g: Game, sorted_arch: list, sorted_players: list):
    """Print key insights for simulation mode."""
    print(f"\n  3. KEY INSIGHTS")

    if sorted_arch:
        most_profitable = sorted_arch[0]
        least_profitable = sorted_arch[-1]
        print(f"     • Most profitable strategy: {most_profitable[0]} (+{most_profitable[1]['net']/max(1, most_profitable[1]['count']):,.0f} avg net)")
        print(f"     • Least profitable strategy: {least_profitable[0]} ({least_profitable[1]['net']/max(1, least_profitable[1]['count']):+,} avg net)")

    if sorted_players:
        best_wr_player = max(
            [p for p in g.players if g.stats[p.player_id]['hands_played'] > 0],
            key=lambda p: g.stats[p.player_id]['hands_won'] / max(1, g.stats[p.player_id]['hands_played'])
        )
        best_wr = g.stats[best_wr_player.player_id]['hands_won'] / g.stats[best_wr_player.player_id]['hands_played'] * 100
        print(f"     • Best win rate: {best_wr_player.name} ({best_wr:.1f}%)")

    chip_leader = max(g.players, key=lambda p: p.chips)
    chip_profit = chip_leader.chips - g.stats[chip_leader.player_id]['starting_chips']
    print(f"     • Chip leader: {chip_leader.name} ({chip_leader.chips:,} chips, +{chip_profit:,})")

    high_rebuy = [p for p in g.players if g.stats[p.player_id].get('rebuys', 0) > 3]
    if high_rebuy:
        print(f"     • High rebuy players (>3): {', '.join(p.name for p in high_rebuy)}")


def _print_key_insights_interactive(g: Game):
    """Print key insights for interactive (non-simulation) mode."""
    print(f"\n  3. KEY INSIGHTS")

    arch_stats = g.stats_tracker.get_archetype_stats(g.players)
    sorted_arch = sorted(arch_stats.items(), key=lambda x: x[1]['net']/max(1, x[1]['count']), reverse=True)
    if sorted_arch:
        most_profitable = sorted_arch[0]
        least_profitable = sorted_arch[-1]
        print(f"     • Most profitable strategy: {most_profitable[0]} (+{most_profitable[1]['net']/max(1, most_profitable[1]['count']):,.0f} avg net)")
        print(f"     • Least profitable strategy: {least_profitable[0]} ({least_profitable[1]['net']/max(1, least_profitable[1]['count']):+,} avg net)")

    sorted_players = sorted(g.players, key=lambda p: p.chips, reverse=True)
    if sorted_players:
        eligible = [p for p in g.players if g.stats[p.player_id]['hands_played'] >= 5]
        if eligible:
            best_wr_player = max(eligible, key=lambda p: g.stats[p.player_id]['hands_won'] / max(1, g.stats[p.player_id]['hands_played']))
            best_wr = g.stats[best_wr_player.player_id]['hands_won'] / g.stats[best_wr_player.player_id]['hands_played'] * 100
            print(f"     • Best win rate: {best_wr_player.name} ({best_wr:.1f}%)")

        chip_leader = max(g.players, key=lambda p: p.chips)
        chip_profit = chip_leader.chips - g.stats[chip_leader.player_id]['starting_chips']
        print(f"     • Chip leader: {chip_leader.name} ({chip_leader.chips:,} chips, +{chip_profit:,})")

        best_hand_player = max(g.players, key=lambda p: g.stats[p.player_id]['best_hand_rank'])
        best_hand_name = g.stats[best_hand_player.player_id]['best_hand_name']
        if best_hand_name and best_hand_name != '-':
            print(f"     • Best hand: {best_hand_player.name} ({best_hand_name})")

        high_rebuy = [p for p in g.players if g.stats[p.player_id].get('rebuys', 0) > 0]
        if high_rebuy:
            print(f"     • Players with rebuys: {', '.join(f'{p.name} ({g.stats[p.player_id]["rebuys"]})' for p in high_rebuy)}")


def _print_game_theory_analysis(g: Game, is_simulation: bool = False):
    """Print complete game theory analysis section."""
    print(f"\n{'GAME THEORY ANALYSIS':^128}")
    print(f"{'─' * 128}")

    _print_gini_coefficient(g)
    sorted_arch = _print_archetype_analysis(g)

    # Get sorted players based on mode
    if is_simulation:
        sorted_players = sorted(
            g.players,
            key=lambda p: g.stats_tracker.get_cumulative_net(p.player_id, p.chips),
            reverse=True
        )
    else:
        sorted_players = sorted(g.players, key=lambda p: p.chips, reverse=True)

    if is_simulation:
        _print_key_insights_simulation(g, sorted_arch, sorted_players)
    else:
        _print_key_insights_interactive(g)


def _print_stats_and_summary(g: Game, settings: dict, hands_simulated: int):
    """Print session stats and game theory analysis for simulation mode."""
    if settings['batch_hands'] > 0:
        # Simulation mode: comprehensive game theory analysis only
        print("\n" + "=" * 128)
        print(f"{'SIMULATION REPORT':^128}")
        print(f"{'─' * 128}")

        # Basic metrics
        print(f"\n{'BASIC METRICS'}")
        print(f"{'─' * 60}")
        total_hands = sum(s['hands_played'] for s in g.stats.values())
        total_rebuys = sum(s.get('rebuys', 0) for s in g.stats.values())
        avg_rebuys = total_rebuys / len(g.players) if g.players else 0
        biggest_pot = max(s['biggest_pot'] for s in g.stats.values())
        best_hand = max(g.stats.values(), key=lambda x: x['best_hand_rank'])

        print(f"  Hands Simulated:      {hands_simulated:>8}")
        print(f"  Players at Table:     {len(g.players):>8}")
        print(f"  Starting Chips:       {settings['starting_chips']:>8,}")
        print(f"  Big Blind:            {settings['big_blind']:>8}")
        print(f"  Total Rebuys:         {total_rebuys:>8,}  (avg: {avg_rebuys:.1f}/player)")
        print(f"  Biggest Single Pot:   {biggest_pot:>8,}")
        print(f"  Best Hand Seen:       {best_hand['best_hand_name']:>15}")

        # Player performance table
        print(f"\n{'PLAYER PERFORMANCE'}")
        print(f"{'─' * 128}")
        print(f"  {'Rank':>4} | {'Player':<15} | {'Strategy':<18} | {'Start':>8} | {'Final':>8} | {'Net':>10} | {'Won':>5} | {'Played':>6} | {'Win%':>6} | {'Status':<12}")
        print(f"  {'─' * 4}-+-{'─' * 15}-+-{'─' * 18}-+-{'─' * 8}-+-{'─' * 8}-+-{'─' * 10}-+-{'─' * 5}-+-{'─' * 6}-+-{'─' * 6}-+-{'─' * 12}")

        sorted_players = sorted(
            g.players,
            key=lambda p: g.stats_tracker.get_cumulative_net(p.player_id, p.chips),
            reverse=True
        )

        for rank, p in enumerate(sorted_players, 1):
            s = g.stats[p.player_id]
            net = g.stats_tracker.get_cumulative_net(p.player_id, p.chips)
            played = s['hands_played']
            won = s['hands_won']
            win_pct = (won / played * 100) if played > 0 else 0
            status = "Active" if p.chips > 0 else f"Bust #{s['bust_hand']}"

            net_str = f"+{net:,}" if net > 0 else f"{net:,}"
            print(f"  {rank:>4} | {p.name:<15} | {g.stats_tracker._strategy_label(p):<18} | {s['starting_chips']:>8,} | {p.chips:>8,} | {net_str:>10} | {won:>5} | {played:>6} | {win_pct:>5.1f}% | {status:<12}")

        _print_game_theory_analysis(g, is_simulation=True)

        print(f"\n{'=' * 128}")
        print(f"{'End of Simulation Report':^128}")
        print(f"{'=' * 128}\n")

    else:
        # Non-simulation mode: show enhanced stats with game theory
        g.print_stats()
        _print_game_theory_analysis(g, is_simulation=False)
        print()


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
