import os
import time
import math
from core.game import Game
from players.terminal import TerminalPlayer
from players.roster import create_bots, MAX_BOTS
from players.bot import BotPlayer
from strategies.difficulty import EASY, NORMAL, HARD
from strategies.profile import StyleProfile
from strategies.engine import DesignedBotStrategy
from strategies.engine import (
    TightPassiveStrategy, TightAggressiveStrategy,
    LoosePassiveStrategy, LooseAggressiveStrategy,
    BalancedStrategy, NitStrategy, ManiacStrategy, TrapperStrategy,
)
from core.stats_persistent import PersistentStatsManager

# Color codes for terminal output
_DIM    = '\033[2m'
_RESET  = '\033[0m'
_GREEN  = '\033[92m'
_RED    = '\033[91m'
_BOLD   = '\033[1m'
_YELLOW = '\033[93m'

# One representative bot per strategy archetype — used in benchmark mode
_BENCHMARK_STRATEGIES = [
    ("TightAggressive", TightAggressiveStrategy),
    ("TightPassive",    TightPassiveStrategy),
    ("LooseAggressive", LooseAggressiveStrategy),
    ("LoosePassive",    LoosePassiveStrategy),
    ("Balanced",        BalancedStrategy),
    ("Nit",             NitStrategy),
    ("Maniac",          ManiacStrategy),
    ("Trapper",         TrapperStrategy),
]

# Per-strategy explanations for the insight section
_STRATEGY_NOTES = {
    "TightAggressive": "selective hand choice + aggression maximizes EV",
    "TightPassive":    "tight range but no fold equity — misses value",
    "LooseAggressive": "high variance; strong short-run, bleeds long-run",
    "LoosePassive":    "wide range + no aggression = easiest to exploit",
    "Balanced":        "balanced play avoids exploitation in the long run",
    "Nit":             "ultra-tight survives but leaves too much EV on the table",
    "Maniac":          "overplays weak hands, bleeds chips through bad calls",
    "Trapper":         "slow-play earns big pots but telegraphs strength",
}


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


def _view_persistent_stats():
    """View persistent stats from all sessions, filtered by difficulty."""
    persistent_stats = PersistentStatsManager()
    
    print("\n" + "=" * 50)
    print("  Persistent Statistics Viewer")
    print("=" * 50)
    print("\nView Options:")
    print("  1. All players by difficulty")
    print("  2. Specific player history")
    print("  3. Session history")
    
    view_choice = input("\nChoose (default 1): ").strip()
    
    if view_choice == '2':
        # View specific player
        print("\nAvailable players:")
        all_players = persistent_stats.get_all_players_by_difficulty()
        player_names = {}
        for diff, players in all_players.items():
            for p in players:
                if p['player_id'] not in player_names:
                    player_names[p['player_id']] = p['name']
        
        if not player_names:
            print("  No players found in history.")
            return
        
        for idx, (p_id, name) in enumerate(player_names.items(), 1):
            print(f"  {idx}. {name}")
        
        player_idx = input("\nSelect player (number): ").strip()
        try:
            selected_player_id = list(player_names.keys())[int(player_idx) - 1]
        except (ValueError, IndexError):
            print("  Invalid selection.")
            return
        
        # Optional difficulty filter
        print("\nFilter by difficulty (or press Enter for all):")
        print("  Easy, Normal, Hard")
        diff_filter = input("Difficulty: ").strip()
        if not diff_filter:
            diff_filter = None
        
        persistent_stats.print_persistent_stats(
            difficulty=diff_filter,
            player_id=selected_player_id
        )
        
    elif view_choice == '3':
        # View session history
        print("\nFilter by difficulty (or press Enter for all):")
        print("  Easy, Normal, Hard")
        diff_filter = input("Difficulty: ").strip()
        if not diff_filter:
            diff_filter = None
        
        sessions = persistent_stats.get_session_history(diff_filter)
        if not sessions:
            print(f"  No sessions found{' for ' + diff_filter if diff_filter else ''}.")
            return
        
        print(f"\n{'=' * 100}")
        print(f"{'SESSION HISTORY':^100}")
        if diff_filter:
            print(f"{'Filtered: ' + diff_filter:^100}")
        print(f"{'=' * 100}")
        print(f"  {'Session':>7} | {'Difficulty':<10} | {'Date':<20} | {'Hands':>7} | {'Mode':<12} | {'Players':>7}")
        print(f"  {'─' * 7}-+-{'─' * 10}-+-{'─' * 20}-+-{'─' * 7}-+-{'─' * 12}-+-{'─' * 7}")
        
        for s in sessions:
            print(f"  #{s['session_id']:<6} | {s['difficulty']:<10} | {s['date']:<20} | {s['hands_played']:>7} | {s['game_mode']:<12} | {len(s['players']):>7}")
        
    else:
        # View all players by difficulty
        print("\nFilter by difficulty (or press Enter for all):")
        print("  Easy, Normal, Hard")
        diff_filter = input("Difficulty: ").strip()
        if not diff_filter:
            diff_filter = None
        
        persistent_stats.print_persistent_stats(difficulty=diff_filter)
    
    input("\nPress Enter to continue...")


def _print_benchmark_results(ranked: list, num_tables: int, hands_per_table: int,
                              starting_chips: int, big_blind: int,
                              per_table_nets: dict = None,
                              convergence_snapshots: list = None,
                              difficulty: float = 0.6,
                              ante: bool = False,
                              short_deck: bool = False,
                              street_totals: dict = None,
                              street_hands: dict = None) -> None:
    """Print benchmark leaderboard, bar chart, statistical analysis, and insights."""
    W = 84
    total_hands = num_tables * hands_per_table
    print("\n" + "=" * W)
    print(f"  {_BOLD}STRATEGY BENCHMARK RESULTS{_RESET}")
    print(f"  {num_tables} tables × {hands_per_table} hands = {total_hands:,} total hands"
          f"  |  chips: {starting_chips:,}  |  BB: {big_blind}")
    diff_label = {0.4: 'Easy', 0.6: 'Normal', 0.75: 'Hard', 0.9: 'Expert'}.get(difficulty, f'{difficulty}')
    opts = f"  Difficulty: {diff_label}"
    if ante:
        opts += "  |  Ante: On"
    if short_deck:
        opts += "  |  Short Deck"
    print(opts)
    print("=" * W)

    has_stats = per_table_nets is not None and len(per_table_nets) > 0

    # ── Leaderboard ───────────────────────────────────────────────────────────
    if has_stats:
        print(f"\n  {'Rank':<5}  {'Strategy':<18}  {'Avg Net':>9}  {'± 95%CI':>9}  {'Std Dev':>9}"
              f"  {'Win%':>6}  {'Rebuys':>7}  {'Tbl Won':>8}")
        print(f"  {'-'*5}  {'-'*18}  {'-'*9}  {'-'*9}  {'-'*9}"
              f"  {'-'*6}  {'-'*7}  {'-'*8}")
    else:
        print(f"\n  {'Rank':<5}  {'Strategy':<18}  {'Avg Net':>9}  {'Win Rate':>9}"
              f"  {'Avg Rebuys':>10}  {'Tables Won':>11}")
        print(f"  {'-'*5}  {'-'*18}  {'-'*9}  {'-'*9}  {'-'*10}  {'-'*11}")

    medals = {0: '1st', 1: '2nd', 2: '3rd'}
    for rank, (sname, data) in enumerate(ranked):
        avg_net    = data['total_net'] / num_tables
        hands_pl   = data['hands_played']
        win_rate   = (data['hands_won'] / hands_pl * 100) if hands_pl > 0 else 0.0
        avg_rebuys = data['total_rebuys'] / num_tables
        tables_won = data['tables_won']

        rank_str = medals.get(rank, str(rank + 1))
        net_str  = f"+{avg_net:,.0f}" if avg_net >= 0 else f"{avg_net:,.0f}"
        color    = _GREEN if avg_net >= 0 else _RED

        if has_stats and sname in per_table_nets:
            nets = per_table_nets[sname]
            sd = (sum((x - avg_net)**2 for x in nets) / (len(nets) - 1)) ** 0.5 if len(nets) > 1 else 0
            ci = 1.96 * sd / math.sqrt(len(nets)) if len(nets) > 1 else 0
            print(f"  {rank_str:<5}  {sname:<18}  {color}{net_str:>9}{_RESET}"
                  f"  {_DIM}±{ci:>7,.0f}{_RESET}  {_DIM}{sd:>9,.0f}{_RESET}"
                  f"  {win_rate:>5.1f}%  {avg_rebuys:>7.1f}  {tables_won:>5}/{num_tables}")
        else:
            print(f"  {rank_str:<5}  {sname:<18}  {color}{net_str:>9}{_RESET}"
                  f"  {win_rate:>8.1f}%  {avg_rebuys:>10.1f}  {tables_won:>8}/{num_tables}")

    # ── Significance check ────────────────────────────────────────────────────
    if has_stats and len(ranked) >= 2:
        top_name, top_data = ranked[0]
        second_name, second_data = ranked[1]
        top_nets = per_table_nets[top_name]
        second_nets = per_table_nets[second_name]
        top_avg = top_data['total_net'] / num_tables
        second_avg = second_data['total_net'] / num_tables

        top_sd = (sum((x - top_avg)**2 for x in top_nets) / (len(top_nets) - 1)) ** 0.5 if len(top_nets) > 1 else 0
        sec_sd = (sum((x - second_avg)**2 for x in second_nets) / (len(second_nets) - 1)) ** 0.5 if len(second_nets) > 1 else 0

        pooled_se = math.sqrt(top_sd**2 / len(top_nets) + sec_sd**2 / len(second_nets)) if len(top_nets) > 1 else 1
        z_score = (top_avg - second_avg) / pooled_se if pooled_se > 0 else 0

        print(f"\n  {_DIM}Statistical significance (1st vs 2nd):{_RESET}")
        if z_score >= 2.576:
            print(f"  z = {z_score:.2f} --{_GREEN}HIGHLY SIGNIFICANT (p < 0.01){_RESET}")
        elif z_score >= 1.96:
            print(f"  z = {z_score:.2f} --{_GREEN}SIGNIFICANT (p < 0.05){_RESET}")
        elif z_score >= 1.645:
            print(f"  z = {z_score:.2f} --{_YELLOW}MARGINALLY SIGNIFICANT (p < 0.10){_RESET}")
        else:
            print(f"  z = {z_score:.2f} --{_RED}NOT SIGNIFICANT — increase tables for confidence{_RESET}")

    # ── Bar chart ─────────────────────────────────────────────────────────────
    print(f"\n  NET PROFIT CHART  (avg chips per table)")
    print(f"  {'-' * 60}")

    max_abs   = max(abs(d['total_net'] / num_tables) for _, d in ranked) or 1
    bar_width = 22
    for sname, data in ranked:
        avg_net = data['total_net'] / num_tables
        n_bars  = round(abs(avg_net) / max_abs * bar_width) if avg_net != 0 else 0
        n_bars  = max(n_bars, 1) if avg_net != 0 else 0
        spaces  = ' ' * (bar_width - n_bars)
        if avg_net >= 0:
            bar = _GREEN + '█' * n_bars + _RESET + spaces
        else:
            bar = _RED   + '▒' * n_bars + _RESET + spaces
        net_str = f"+{avg_net:,.0f}" if avg_net >= 0 else f"{avg_net:,.0f}"
        print(f"  {sname:<18}  {bar}  {net_str}")

    # ── Convergence ───────────────────────────────────────────────────────────
    if convergence_snapshots:
        final_top3 = [s for s, _ in ranked[:3]]
        print(f"\n  CONVERGENCE CHECK")
        print(f"  {'-' * 60}")
        for tables_done, top3 in convergence_snapshots:
            match = sum(1 for s in top3 if s in final_top3)
            pct = tables_done / num_tables * 100
            indicator = _GREEN + '●' + _RESET if match == 3 else (_YELLOW + '◐' + _RESET if match >= 2 else _RED + '○' + _RESET)
            print(f"  {indicator} At {pct:>3.0f}% ({tables_done:>4} tables): "
                  f"top 3 = {', '.join(top3)}  ({match}/3 match)")
        last_snap = convergence_snapshots[-1][1] if convergence_snapshots else []
        if set(last_snap) == set(final_top3):
            print(f"  --{_GREEN}Ranking CONVERGED by 75% — results are stable{_RESET}")
        else:
            print(f"  --{_YELLOW}Ranking shifted after 75% — consider more tables{_RESET}")

    # ── Insights ──────────────────────────────────────────────────────────────
    best_name,  best_data  = ranked[0]
    worst_name, worst_data = ranked[-1]
    best_avg  = best_data['total_net']  / num_tables
    worst_avg = worst_data['total_net'] / num_tables
    spread    = best_avg - worst_avg

    if   spread > starting_chips * 4: verdict = "MASSIVE — strategy is the dominant factor"
    elif spread > starting_chips * 2: verdict = "LARGE   — strategy strongly impacts outcome"
    elif spread > starting_chips:     verdict = "MODERATE — strategy matters but variance is real"
    else:                             verdict = "SMALL — strategies closely matched at this sample size"

    print(f"\n  GAME THEORY INSIGHTS")
    print(f"  {'-' * 60}")
    sign = '+' if best_avg >= 0 else ''
    print(f"  • Best strategy:  {_GREEN}{best_name}{_RESET}"
          f"  (avg {sign}{best_avg:,.0f} chips/table)")
    print(f"  • Worst strategy: {_RED}{worst_name}{_RESET}"
          f"  (avg {worst_avg:,.0f} chips/table)")
    print(f"  • Spread: {spread:,.0f} chips — {verdict}")
    print(f"\n  Strategy notes:")
    for sname, _ in ranked:
        note = _STRATEGY_NOTES.get(sname, '')
        if note:
            print(f"    {sname:<18}  {note}")

    if street_totals and street_hands:
        print(f"\n  INVESTMENT BY STREET  (avg chips per hand when active)")
        print(f"  {'-' * 70}")
        print(f"  {'Strategy':<18}  {'Preflop':>8}  {'Flop':>8}  {'Turn':>8}  {'River':>8}  {'Post/Pre':>9}")
        print(f"  {'-'*18}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*9}")
        for sname, _ in ranked:
            st = street_totals.get(sname, {})
            sh = street_hands.get(sname, {})
            avgs = {}
            for street in ['preflop', 'flop', 'turn', 'river']:
                h = sh.get(street, 0)
                avgs[street] = st.get(street, 0) / h if h > 0 else 0
            pre = avgs['preflop']
            post = avgs['flop'] + avgs['turn'] + avgs['river']
            ratio = f"{post/pre:.1f}x" if pre > 0 else "-"
            print(f"  {sname:<18}  {avgs['preflop']:>8.0f}  {avgs['flop']:>8.0f}"
                  f"  {avgs['turn']:>8.0f}  {avgs['river']:>8.0f}  {ratio:>9}")

    print("=" * W + "\n")


def _prompt_difficulty() -> float:
    """Prompt user for difficulty level. Returns float."""
    print("\nDifficulty for all bots:")
    print("  1. Easy (0.4)   2. Normal (0.6)   3. Hard (0.75)   4. Expert (0.9)")
    diff_input = input("Choose (default 2): ").strip()
    return {'1': 0.4, '3': 0.75, '4': 0.9}.get(diff_input, 0.6)


def _run_strategy_benchmark() -> None:
    """Run multiple independent tables to rank all strategy archetypes."""
    W = 74
    print("\n" + "=" * W)
    print(f"  {_BOLD}STRATEGY BENCHMARK — ALL vs ALL{_RESET}")
    print("  Runs independent tables — one bot per strategy type — and ranks")
    print("  strategies by avg profit with statistical confidence intervals.")
    print("=" * W + "\n")

    num_tables      = _prompt_int("Number of tables?  (default 50):   ", 50,   min_val=1, max_val=1000)
    hands_per_table = _prompt_int("Hands per table?   (default 500):  ", 500,  min_val=10)
    starting_chips  = _prompt_int("Starting chips?    (default 1000): ", 1000, min_val=100)
    big_blind       = _prompt_int("Big Blind?         (default 20):   ", 20,   min_val=2)
    difficulty      = _prompt_difficulty()
    enable_ante     = _prompt_yn("Enable ante? (y/n, default n): ")
    short_deck      = _prompt_yn("Short deck? (y/n, default n): ")

    total_hands = num_tables * hands_per_table
    strat_names = [s[0] for s in _BENCHMARK_STRATEGIES]
    diff_label = {0.4: 'Easy', 0.6: 'Normal', 0.75: 'Hard', 0.9: 'Expert'}.get(difficulty, f'{difficulty}')
    print(f"\n  Strategies : {', '.join(strat_names)}")
    print(f"  Total hands: {total_hands:,}  ({num_tables} tables × {hands_per_table} hands)")
    print(f"  Difficulty : {diff_label}  |  Ante: {'Yes' if enable_ante else 'No'}"
          f"  |  Short deck: {'Yes' if short_deck else 'No'}")
    print(f"\n  Simulating ", end='', flush=True)

    agg = {name: {'total_net': 0, 'hands_won': 0, 'hands_played': 0,
                  'total_rebuys': 0, 'tables_won': 0}
           for name in strat_names}

    per_table_nets = {name: [] for name in strat_names}
    street_totals = {name: {'preflop': 0, 'flop': 0, 'turn': 0, 'river': 0} for name in strat_names}
    street_hands = {name: {'preflop': 0, 'flop': 0, 'turn': 0, 'river': 0} for name in strat_names}
    convergence_snapshots = []
    check_at = set()
    if num_tables >= 8:
        check_at = {num_tables // 4, num_tables // 2, 3 * num_tables // 4}

    t_start    = time.time()
    dot_every  = max(1, num_tables // 20)

    for table_num in range(num_tables):
        g = Game(
            big_blind=big_blind,
            hands_per_level=9999,
            ante=enable_ante,
            live_output=False,
            game_mode='cash',
            short_deck=short_deck,
        )

        pid_to_strat: dict = {}
        for i, (sname, strategy_cls) in enumerate(_BENCHMARK_STRATEGIES):
            pid = f"b{i}"
            g.add_player(BotPlayer(pid, sname[:12], starting_chips, strategy_cls(difficulty)))
            pid_to_strat[pid] = sname

        for _ in range(hands_per_table):
            g.start_game()
            for p in g.players:
                pid = p.player_id
                sname = pid_to_strat[pid]
                if pid in g.street_investments:
                    for street, amt in g.street_investments[pid].items():
                        street_totals[sname][street] += amt
                        if amt > 0:
                            street_hands[sname][street] += 1
                if p.chips == 0:
                    p.chips = starting_chips
                    g.stats[p.player_id]['total_invested'] += starting_chips
                    g.stats[p.player_id]['rebuys'] += 1

        chip_leader = max(g.players, key=lambda p: p.chips)

        for p in g.players:
            sname = pid_to_strat[p.player_id]
            s     = g.stats[p.player_id]
            net   = p.chips - s['total_invested']
            agg[sname]['total_net']    += net
            agg[sname]['hands_won']    += s['hands_won']
            agg[sname]['hands_played'] += s['hands_played']
            agg[sname]['total_rebuys'] += s.get('rebuys', 0)
            per_table_nets[sname].append(net)
            if p is chip_leader:
                agg[sname]['tables_won'] += 1

        if (table_num + 1) in check_at:
            snapshot = sorted(strat_names, key=lambda n: sum(per_table_nets[n]), reverse=True)
            convergence_snapshots.append((table_num + 1, snapshot[:3]))

        if (table_num + 1) % dot_every == 0:
            print('.', end='', flush=True)

    elapsed = time.time() - t_start
    print(f"  done ({elapsed:.1f}s)")

    ranked = sorted(agg.items(), key=lambda x: x[1]['total_net'], reverse=True)
    _print_benchmark_results(ranked, num_tables, hands_per_table, starting_chips, big_blind,
                             per_table_nets, convergence_snapshots, difficulty, enable_ante, short_deck,
                             street_totals, street_hands)


def _run_h2h_benchmark() -> None:
    """Run round-robin head-to-head matches between all strategy pairs."""
    W = 84
    print("\n" + "=" * W)
    print(f"  {_BOLD}HEAD-TO-HEAD MATRIX{_RESET}")
    print("  Round-robin: every strategy pair plays N tables of heads-up poker.")
    print("  Shows win rate of row strategy vs column strategy.")
    print("=" * W + "\n")

    num_tables      = _prompt_int("Tables per matchup? (default 50):  ", 50,  min_val=5, max_val=500)
    hands_per_table = _prompt_int("Hands per table?    (default 200): ", 200, min_val=10)
    starting_chips  = _prompt_int("Starting chips?     (default 1000):", 1000, min_val=100)
    big_blind       = _prompt_int("Big Blind?          (default 20):  ", 20,  min_val=2)
    difficulty      = _prompt_difficulty()

    strat_names = [s[0] for s in _BENCHMARK_STRATEGIES]
    n_strats = len(strat_names)
    n_matchups = n_strats * (n_strats - 1) // 2
    total_tables = n_matchups * num_tables

    print(f"\n  {n_matchups} matchups × {num_tables} tables = {total_tables:,} total tables")
    print(f"  Simulating ", end='', flush=True)

    wins = [[0] * n_strats for _ in range(n_strats)]
    net_matrix = [[0.0] * n_strats for _ in range(n_strats)]

    t_start = time.time()
    matchup_count = 0
    dot_every = max(1, n_matchups // 20)

    for i in range(n_strats):
        for j in range(i + 1, n_strats):
            _, cls_a = _BENCHMARK_STRATEGIES[i]
            _, cls_b = _BENCHMARK_STRATEGIES[j]

            a_wins = 0
            a_total_net = 0

            for _ in range(num_tables):
                g = Game(
                    big_blind=big_blind,
                    hands_per_level=9999,
                    ante=False,
                    live_output=False,
                    game_mode='cash',
                )

                g.add_player(BotPlayer("a", strat_names[i][:12], starting_chips, cls_a(difficulty)))
                g.add_player(BotPlayer("b", strat_names[j][:12], starting_chips, cls_b(difficulty)))

                for _ in range(hands_per_table):
                    g.start_game()
                    for p in g.players:
                        if p.chips == 0:
                            p.chips = starting_chips
                            g.stats[p.player_id]['total_invested'] += starting_chips
                            g.stats[p.player_id]['rebuys'] += 1

                pa = next(p for p in g.players if p.player_id == "a")
                pb = next(p for p in g.players if p.player_id == "b")
                net_a = pa.chips - g.stats["a"]['total_invested']
                a_total_net += net_a
                if pa.chips > pb.chips:
                    a_wins += 1

            wins[i][j] = a_wins
            wins[j][i] = num_tables - a_wins
            net_matrix[i][j] = a_total_net / num_tables
            net_matrix[j][i] = -a_total_net / num_tables

            matchup_count += 1
            if matchup_count % dot_every == 0:
                print('.', end='', flush=True)

    elapsed = time.time() - t_start
    print(f"  done ({elapsed:.1f}s)")

    _print_h2h_matrix(strat_names, wins, net_matrix, num_tables)


def _print_h2h_matrix(strat_names: list, wins: list, net_matrix: list,
                       num_tables: int) -> None:
    """Print head-to-head win rate matrix with dominance analysis."""
    n = len(strat_names)
    abbrevs = [s[:7] for s in strat_names]

    W = 84
    print(f"\n{'=' * W}")
    print(f"  {_BOLD}HEAD-TO-HEAD WIN RATES{_RESET}  (row vs column, {num_tables} tables each)")
    print(f"{'=' * W}")

    # Header row
    print(f"\n  {'':>14}", end='')
    for a in abbrevs:
        print(f" {a:>8}", end='')
    print(f" {'Overall':>8}")
    print(f"  {'':>14}" + " --------" * n + " --------")

    for i in range(n):
        total_wins = sum(wins[i][j] for j in range(n) if j != i)
        total_possible = (n - 1) * num_tables
        total_pct = total_wins / total_possible * 100 if total_possible else 0

        print(f"  {strat_names[i]:>14}", end='')
        for j in range(n):
            if i == j:
                print(f" {'—':>8}", end='')
            else:
                pct = wins[i][j] / num_tables * 100
                if pct >= 60:
                    print(f" {_GREEN}{pct:>6.0f}%{_RESET} ", end='')
                elif pct <= 40:
                    print(f" {_RED}{pct:>6.0f}%{_RESET} ", end='')
                else:
                    print(f" {pct:>7.0f}%", end='')

        color = _GREEN if total_pct >= 55 else (_RED if total_pct < 45 else '')
        reset = _RESET if color else ''
        print(f" {color}{total_pct:>6.1f}%{reset} ")

    # Dominance ranking
    print(f"\n  {_BOLD}DOMINANCE RANKING{_RESET}")
    print(f"  {'-' * 70}")

    total_pcts = []
    for i in range(n):
        total_wins = sum(wins[i][j] for j in range(n) if j != i)
        total_possible = (n - 1) * num_tables
        total_pcts.append((strat_names[i], total_wins / total_possible * 100 if total_possible else 0, i))

    total_pcts.sort(key=lambda x: x[1], reverse=True)
    medals = {0: '1st', 1: '2nd', 2: '3rd'}
    for rank, (name, pct, _) in enumerate(total_pcts):
        rank_str = medals.get(rank, f'{rank+1}th')
        color = _GREEN if pct >= 55 else (_RED if pct < 45 else '')
        reset = _RESET if color else ''
        note = _STRATEGY_NOTES.get(name, '')
        print(f"  {rank_str:<4}  {name:<18}  {color}{pct:>5.1f}% win rate{reset}  {_DIM}{note}{_RESET}")

    # Worst matchups for each top strategy
    print(f"\n  {_BOLD}EXPLOITABILITY{_RESET}  (worst matchup for each strategy)")
    print(f"  {'-' * 70}")
    for name, pct, idx in total_pcts:
        worst_j = min((j for j in range(n) if j != idx), key=lambda j: wins[idx][j])
        worst_pct = wins[idx][worst_j] / num_tables * 100
        worst_name = strat_names[worst_j]
        print(f"  {name:<18}  weakest vs {worst_name:<18} ({_RED}{worst_pct:.0f}%{_RESET} win rate)")

    # Rock-paper-scissors detection
    rps_cycles = []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            for k in range(n):
                if k in (i, j):
                    continue
                if (wins[i][j] > num_tables * 0.55 and
                    wins[j][k] > num_tables * 0.55 and
                    wins[k][i] > num_tables * 0.55):
                    cycle = tuple(sorted([i, j, k]))
                    if cycle not in rps_cycles:
                        rps_cycles.append(cycle)

    if rps_cycles:
        print(f"\n  {_BOLD}CYCLICAL DYNAMICS{_RESET}  (rock-paper-scissors patterns)")
        print(f"  {'-' * 70}")
        for cycle in rps_cycles[:5]:
            i, j, k = cycle
            parts = []
            for a, b in [(i, j), (j, k), (k, i)]:
                if wins[a][b] > wins[b][a]:
                    parts.append(f"{strat_names[a]} > {strat_names[b]}")
                else:
                    parts.append(f"{strat_names[b]} > {strat_names[a]}")
            print(f"    {' -- '.join(parts)}")
    else:
        print(f"\n  {_DIM}No strong cyclical dynamics detected at this sample size.{_RESET}")

    print(f"\n{'=' * W}\n")


def _run_parameter_sweep() -> None:
    """Vary one strategy parameter across a range and chart its effect on profit."""
    W = 84
    print("\n" + "=" * W)
    print(f"  {_BOLD}PARAMETER SWEEP{_RESET}")
    print("  Vary one parameter while holding others fixed.")
    print("  Shows how each value performs against a full table of standard bots.")
    print("=" * W + "\n")

    print("  Which parameter to sweep?")
    print("    1. Aggression     (0.1 to 1.0)")
    print("    2. Play range     (0.1 to 1.0)")
    print("    3. Bluff frequency (0.0 to 0.8)")
    param_choice = input("  Choose (default 1): ").strip()

    if param_choice == '2':
        param_name = 'play_range'
        steps = [round(0.1 * i, 1) for i in range(1, 11)]
        base_profile = dict(play_range=0.5, aggression=0.5, bluff_freq=0.25, call_freq=0.5)
    elif param_choice == '3':
        param_name = 'bluff_freq'
        steps = [round(0.1 * i, 1) for i in range(0, 9)]
        base_profile = dict(play_range=0.5, aggression=0.5, bluff_freq=0.25, call_freq=0.5)
    else:
        param_name = 'aggression'
        steps = [round(0.1 * i, 1) for i in range(1, 11)]
        base_profile = dict(play_range=0.5, aggression=0.5, bluff_freq=0.25, call_freq=0.5)

    num_tables      = _prompt_int("Tables per data point? (default 30):  ", 30,  min_val=5, max_val=200)
    hands_per_table = _prompt_int("Hands per table?      (default 300): ", 300, min_val=10)
    starting_chips  = _prompt_int("Starting chips?       (default 1000):", 1000, min_val=100)
    big_blind       = _prompt_int("Big Blind?            (default 20):  ", 20,  min_val=2)
    difficulty      = _prompt_difficulty()

    print(f"\n  Sweeping {param_name}: {steps[0]} -> {steps[-1]} ({len(steps)} points)")
    print(f"  {len(steps)} × {num_tables} tables × {hands_per_table} hands = {len(steps) * num_tables * hands_per_table:,} total hands")
    print(f"\n  Simulating ", end='', flush=True)

    results = []  # list of (param_value, avg_net, std_dev)
    t_start = time.time()
    dot_every = max(1, len(steps) // 10)

    for step_idx, value in enumerate(steps):
        profile_args = dict(base_profile)
        profile_args[param_name] = value
        sweep_profile = StyleProfile(name=f'sweep_{value}', **profile_args)

        nets = []
        for _ in range(num_tables):
            g = Game(
                big_blind=big_blind,
                hands_per_level=9999,
                ante=False,
                live_output=False,
                game_mode='cash',
            )

            # Add the sweep bot
            sweep_strategy = DesignedBotStrategy(sweep_profile, difficulty)
            g.add_player(BotPlayer("sweep", "Sweep", starting_chips, sweep_strategy))

            # Add standard opponents (use a few diverse strategies)
            opponents = [
                ("TightAggressive", TightAggressiveStrategy),
                ("LoosePassive",    LoosePassiveStrategy),
                ("Balanced",        BalancedStrategy),
            ]
            for i, (oname, ocls) in enumerate(opponents):
                g.add_player(BotPlayer(f"opp{i}", oname[:12], starting_chips, ocls(difficulty)))

            for _ in range(hands_per_table):
                g.start_game()
                for p in g.players:
                    if p.chips == 0:
                        p.chips = starting_chips
                        g.stats[p.player_id]['total_invested'] += starting_chips
                        g.stats[p.player_id]['rebuys'] += 1

            sweep_p = next(p for p in g.players if p.player_id == "sweep")
            net = sweep_p.chips - g.stats["sweep"]['total_invested']
            nets.append(net)

        avg_net = sum(nets) / len(nets)
        sd = (sum((x - avg_net)**2 for x in nets) / (len(nets) - 1)) ** 0.5 if len(nets) > 1 else 0
        results.append((value, avg_net, sd))

        if (step_idx + 1) % dot_every == 0:
            print('.', end='', flush=True)

    elapsed = time.time() - t_start
    print(f"  done ({elapsed:.1f}s)")

    _print_parameter_sweep(param_name, results, num_tables, hands_per_table, starting_chips, big_blind)


def _print_parameter_sweep(param_name: str, results: list, num_tables: int,
                            hands_per_table: int, starting_chips: int,
                            big_blind: int) -> None:
    """Print parameter sweep results as table and ASCII chart."""
    W = 84
    print(f"\n{'=' * W}")
    print(f"  {_BOLD}PARAMETER SWEEP: {param_name.upper()}{_RESET}")
    print(f"  Base profile: Balanced (play_range=0.5, aggression=0.5, bluff=0.25, call=0.5)")
    print(f"  Opponents: TightAggressive + LoosePassive + Balanced")
    print(f"  {num_tables} tables × {hands_per_table} hands per data point")
    print(f"{'=' * W}")

    # Table
    print(f"\n  {param_name:<12}  {'Avg Net':>9}  {'± 95%CI':>9}  {'Std Dev':>9}")
    print(f"  {'-'*12}  {'-'*9}  {'-'*9}  {'-'*9}")

    best_val, best_net = None, float('-inf')
    for value, avg_net, sd in results:
        ci = 1.96 * sd / math.sqrt(num_tables) if num_tables > 1 else 0
        color = _GREEN if avg_net >= 0 else _RED
        net_str = f"+{avg_net:,.0f}" if avg_net >= 0 else f"{avg_net:,.0f}"
        print(f"  {value:<12.1f}  {color}{net_str:>9}{_RESET}  {_DIM}+/-{ci:>5,.0f}{_RESET}  {_DIM}{sd:>9,.0f}{_RESET}")
        if avg_net > best_net:
            best_net = avg_net
            best_val = value

    # ASCII chart
    max_abs = max(abs(r[1]) for r in results) or 1
    chart_width = 30
    center = chart_width // 2

    print(f"\n  {param_name.upper()} vs NET PROFIT")
    print(f"  {'':>5}  {'':>{center}}|")

    for value, avg_net, _ in results:
        bar_len = round(abs(avg_net) / max_abs * center)
        bar_len = max(bar_len, 1) if avg_net != 0 else 0

        if avg_net >= 0:
            left_pad = ' ' * center
            bar = _GREEN + '█' * bar_len + _RESET
            line = f"  {value:>4.1f}  {left_pad}|{bar}"
        else:
            padding = ' ' * (center - bar_len)
            bar = _RED + '▒' * bar_len + _RESET
            line = f"  {value:>4.1f}  {padding}{bar}|"

        print(line)

    print(f"  {'':>5}  {'':>{center}}|")
    print(f"  {'':>5}  {'-loss':>{center}}   +profit")

    # Optimal point
    print(f"\n  {_BOLD}OPTIMAL{_RESET}: {param_name} = {_GREEN}{best_val}{_RESET}"
          f" (avg net: {_GREEN}+{best_net:,.0f}{_RESET} chips/table)")

    # Insight
    nets = [r[1] for r in results]
    spread = max(nets) - min(nets)
    if spread > starting_chips * 2:
        print(f"  Sensitivity: {_RED}HIGH{_RESET} — {param_name} strongly impacts results")
    elif spread > starting_chips:
        print(f"  Sensitivity: {_YELLOW}MODERATE{_RESET} — {param_name} matters")
    else:
        print(f"  Sensitivity: {_DIM}LOW{_RESET} — other factors dominate")

    print(f"\n{'=' * W}\n")


def _benchmark_menu() -> None:
    """Show benchmark sub-menu and dispatch."""
    print("\nBenchmark Mode:")
    print("  1. All-vs-All       (rank strategies by profit with confidence intervals)")
    print("  2. Head-to-Head     (round-robin win-rate matrix between all pairs)")
    print("  3. Parameter Sweep  (vary one param, chart its effect on profit)")
    choice = input("Choose (default 1): ").strip()
    if choice == '2':
        _run_h2h_benchmark()
    elif choice == '3':
        _run_parameter_sweep()
    else:
        _run_strategy_benchmark()


def _collect_settings():
    """Collect all game settings interactively. Returns a settings dict."""
    print("\nMode:")
    print("  1. Tournament          (blinds escalate, play against bots)")
    print("  2. Strategy Benchmark  (rank all archetypes over many tables)")
    print("  3. View Persistent Stats")
    mode_input = input("Choose (default 1): ").strip()

    if mode_input == '2':
        _benchmark_menu()
        return None
    if mode_input == '3':
        _view_persistent_stats()
        return None

    short_deck  = _prompt_yn("Short deck (6+ cards, Flush > Full House)? (y/n, default n): ")
    player_name = _prompt_player_name()
    num_bots    = _prompt_int(f"How many bots? (default 3, max {MAX_BOTS}): ", 3, min_val=1, max_val=MAX_BOTS)

    print("\nTable difficulty:")
    print("  1. Easy    (bots make more mistakes)")
    print("  2. Normal  (default)")
    print("  3. Hard    (bots play sharper)")
    diff_input = input("Choose (default 2): ").strip()
    difficulty = {1: EASY, '1': EASY, 3: HARD, '3': HARD}.get(diff_input, NORMAL)

    shuffle_bots   = _prompt_yn("Randomise bot seating? (y/n, default y): ", default=True)
    starting_chips = _prompt_int("Starting chips? (default 1000): ", 1000)
    big_blind      = _prompt_int("Big Blind? (default 20): ", 20)

    print("\nBlind schedule:")
    print("  1. Normal  (5 hands per level)")
    print("  2. Turbo   (2 hands per level)")
    turbo = input("Choose (default 1): ").strip()
    hands_per_level = 2 if turbo == '2' else _prompt_int("Hands per blind level? (default 5): ", 5)

    enable_ante = _prompt_yn("Enable ante? (y/n, default n): ")

    return {
        'short_deck':      short_deck,
        'player_name':     player_name,
        'num_bots':        num_bots,
        'difficulty':      difficulty,
        'shuffle_bots':    shuffle_bots,
        'starting_chips':  starting_chips,
        'big_blind':       big_blind,
        'hands_per_level': hands_per_level,
        'enable_ante':     enable_ante,
    }


def _build_game(settings: dict) -> tuple:
    """Create a fresh Game instance and players. Returns (game, human_player)."""
    g = Game(
        big_blind=settings['big_blind'],
        hands_per_level=settings['hands_per_level'],
        ante=settings['enable_ante'],
        live_output=True,
        game_mode='tournament',
        short_deck=settings['short_deck'],
    )

    g.add_player(TerminalPlayer("h1", settings['player_name'], settings['starting_chips']))
    human = next(p for p in g.players if isinstance(p, TerminalPlayer))

    for bot in create_bots(
        settings['num_bots'], settings['starting_chips'],
        difficulty=settings['difficulty'], shuffled=settings['shuffle_bots'],
    ):
        g.add_player(bot)

    return g, human


def _run_session(g: Game, human, settings: dict):
    """Run hands until the player quits or is the last one standing."""
    while True:
        os.system('clear' if os.name == 'posix' else 'cls')
        g.start_game()

        if human.chips == 0:
            ans = input(
                f"\nYou're out of chips! Rebuy for {settings['starting_chips']}? (y/n): "
            ).strip().lower()
            if ans in ['y', 'yes']:
                human.chips = settings['starting_chips']
                g.stats[human.player_id]['total_invested'] += settings['starting_chips']
                g.stats[human.player_id]['rebuys'] += 1
                print(f"Rebought! You now have {settings['starting_chips']} chips.")

        active_players = [p for p in g.players if p.chips > 0]
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
        print(f"     --EXTREME inequality — Winner-take-all dynamics")
    elif gini > 0.4:
        print(f"     --HIGH inequality — Strategic dominance by few players")
    elif gini > 0.2:
        print(f"     --MODERATE inequality — Balanced competition")
    else:
        print(f"     --LOW inequality — Healthy strategic diversity")


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
        chip_profit = g.stats_tracker.get_cumulative_net(chip_leader.player_id, chip_leader.chips)
        profit_str = f"+{chip_profit:,}" if chip_profit > 0 else f"{chip_profit:,}"
        print(f"     • Chip leader: {chip_leader.name} ({chip_leader.chips:,} chips, {profit_str})")

        best_hand_player = max(g.players, key=lambda p: g.stats[p.player_id]['best_hand_rank'])
        best_hand_name = g.stats[best_hand_player.player_id]['best_hand_name']
        if best_hand_name and best_hand_name != '-':
            print(f"     • Best hand: {best_hand_player.name} ({best_hand_name})")

        high_rebuy = [p for p in g.players if g.stats[p.player_id].get('rebuys', 0) > 0]
        if high_rebuy:
            print(f"     • Players with rebuys: {', '.join(f'{p.name} ({g.stats[p.player_id]["rebuys"]})' for p in high_rebuy)}")


def _print_game_theory_analysis(g: Game):
    """Print complete game theory analysis section."""
    print(f"\n{'GAME THEORY ANALYSIS':^128}")
    print(f"{'─' * 128}")
    _print_gini_coefficient(g)
    _print_archetype_analysis(g)
    _print_key_insights_interactive(g)


def _print_stats_and_summary(g: Game):
    """Print session stats and game theory analysis."""
    g.print_stats()
    _print_game_theory_analysis(g)
    print()


def main():
    print("=" * 50)
    print("  Welcome to Poker Terminal!")
    print("=" * 50)

    # Initialize persistent stats manager
    persistent_stats = PersistentStatsManager()
    
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
            # If user chose to view stats, skip game setup
            if settings is None:
                continue
        else:
            # Reuse existing settings for replay
            if session_num > 1:
                print(f"\n{'=' * 50}")
                print(f"  Session #{session_num} — Replaying with same settings")
                print(f"{'=' * 50}")

        g, human = _build_game(settings)
        _run_session(g, human, settings)
        _print_stats_and_summary(g)

        # Save session stats to persistent storage
        game_stats = {'hand_count': g.hand_count}
        for p in g.players:
            game_stats[p.player_id] = g.stats[p.player_id]
        persistent_stats.save_session(
            session_id=session_num,
            difficulty=settings['difficulty'],
            players=g.players,
            game_stats=game_stats,
            game_mode='tournament'
        )
        print(f"\n  {_DIM}Session stats saved to persistent storage.{_RESET}")

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
