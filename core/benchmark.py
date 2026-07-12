"""Benchmark compute cores — pure simulation loops extracted from main.py.

These build the plain data structures the TUI printers and SimulationStatsManager
consume; they do no I/O of their own. Progress is reported via an optional
``progress(done, total)`` callback (in place of main.py's inline ``\r`` prints),
and an optional ``should_stop()`` callback is checked once per table / matchup /
step — when it returns True the runner returns its partial results with
``'stopped': True`` (used for cancellation; the TUI passes None).
"""
import time

from core.game import Game
from players.bot import BotPlayer
from strategies.profile import StyleProfile
from strategies.engine import DesignedBotStrategy
from strategies.engine import (
    TightPassiveStrategy, TightAggressiveStrategy,
    LoosePassiveStrategy, LooseAggressiveStrategy,
    BalancedStrategy, NitStrategy, ManiacStrategy, TrapperStrategy,
)

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


def run_all_vs_all(num_tables, hands_per_table, starting_chips, big_blind,
                   difficulty, ante=False, short_deck=False,
                   progress=None, should_stop=None) -> dict:
    """Run independent tables — one bot per strategy type — and rank archetypes."""
    strat_names = [s[0] for s in _BENCHMARK_STRATEGIES]

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
    report_every = max(1, num_tables // 10)

    stopped = False
    for table_num in range(num_tables):
        if should_stop and should_stop():
            stopped = True
            break
        if (table_num + 1) % report_every == 0 or table_num == 0:
            if progress:
                progress(table_num + 1, num_tables)
        g = Game(
            big_blind=big_blind,
            hands_per_level=9999,
            ante=ante,
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

    elapsed = time.time() - t_start
    ranked = sorted(agg.items(), key=lambda x: x[1]['total_net'], reverse=True)

    result = {
        'ranked':                ranked,
        'per_table_nets':        per_table_nets,
        'convergence_snapshots': convergence_snapshots,
        'street_totals':         street_totals,
        'street_hands':          street_hands,
        'elapsed':               elapsed,
    }
    if stopped:
        result['stopped'] = True
    return result


def run_h2h(num_tables, hands_per_table, starting_chips, big_blind,
            difficulty, progress=None, should_stop=None) -> dict:
    """Round-robin head-to-head matches between all strategy pairs."""
    strat_names = [s[0] for s in _BENCHMARK_STRATEGIES]
    n_strats = len(strat_names)
    n_matchups = n_strats * (n_strats - 1) // 2

    wins = [[0] * n_strats for _ in range(n_strats)]
    net_matrix = [[0.0] * n_strats for _ in range(n_strats)]

    t_start = time.time()
    matchup_count = 0
    stopped = False

    for i in range(n_strats):
        for j in range(i + 1, n_strats):
            if should_stop and should_stop():
                stopped = True
                break
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
            if progress:
                progress(matchup_count, n_matchups)
        if stopped:
            break

    elapsed = time.time() - t_start

    result = {
        'strat_names': strat_names,
        'wins':        wins,
        'net_matrix':  net_matrix,
        'elapsed':     elapsed,
    }
    if stopped:
        result['stopped'] = True
    return result


def run_param_sweep(param_name, steps, base_profile, num_tables,
                    hands_per_table, starting_chips, big_blind, difficulty,
                    progress=None, should_stop=None) -> dict:
    """Vary one strategy parameter across a range and measure its effect on profit."""
    results = []  # list of (param_value, avg_net, std_dev)
    t_start = time.time()
    stopped = False

    for step_idx, value in enumerate(steps):
        if should_stop and should_stop():
            stopped = True
            break
        if progress:
            progress(step_idx + 1, len(steps))
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

    elapsed = time.time() - t_start

    result = {'results': results, 'elapsed': elapsed}
    if stopped:
        result['stopped'] = True
    return result
