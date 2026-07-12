"""SimulationStatsManager - Persistent storage for strategy benchmark results."""

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

SIM_STATS_FILE = Path(__file__).parent.parent / "simulation_stats.json"

_DIM   = '\033[2m'
_RESET = '\033[0m'
_GREEN = '\033[92m'
_RED   = '\033[91m'
_BOLD  = '\033[1m'

_SHORT_NAMES = {
    'TightAggressive': 'TightAgg', 'TightPassive': 'TightPas',
    'LooseAggressive': 'LooseAgg', 'LoosePassive': 'LoosePas',
    'Balanced': 'Balanced', 'Nit': 'Nit', 'Maniac': 'Maniac', 'Trapper': 'Trapper',
}


class SimulationStatsManager:

    def __init__(self, stats_file: Path = SIM_STATS_FILE):
        self.stats_file = stats_file
        self._data = self._load()

    def _load(self) -> Dict:
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                print("Warning: Could not load simulation stats, starting fresh")
        return {'sessions': [], 'alltime': {'all_vs_all': {}, 'h2h': {}}}

    def _save(self):
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"Error saving simulation stats: {e}")

    def _next_session_id(self) -> int:
        sessions = self._data['sessions']
        return (sessions[-1]['session_id'] + 1) if sessions else 1

    @staticmethod
    def difficulty_label(difficulty: float) -> str:
        if difficulty <= 0.4:
            return 'Easy'
        elif difficulty <= 0.6:
            return 'Normal'
        elif difficulty <= 0.75:
            return 'Hard'
        else:
            return 'Expert'

    @staticmethod
    def stack_depth(big_blind: int, starting_chips: int) -> str:
        ratio = big_blind / starting_chips
        if ratio <= 0.02:
            return 'deep'
        elif ratio <= 0.05:
            return 'medium'
        else:
            return 'short'

    @staticmethod
    def bucket_key(difficulty: str, short_deck: bool, ante: bool, depth: str) -> str:
        return f"{difficulty}|{short_deck}|{ante}|{depth}"

    # ── Save methods ──────────────────────────────────────────────────────────

    def save_all_vs_all(self, num_tables: int, hands_per_table: int,
                        starting_chips: int, big_blind: int,
                        difficulty: float, ante: bool, short_deck: bool,
                        ranked: list, per_table_nets: dict) -> None:
        diff   = self.difficulty_label(difficulty)
        depth  = self.stack_depth(big_blind, starting_chips)
        config = {
            'num_tables':      num_tables,
            'hands_per_table': hands_per_table,
            'starting_chips':  starting_chips,
            'big_blind':       big_blind,
            'difficulty':      diff,
            'ante':            ante,
            'short_deck':      short_deck,
            'stack_depth':     depth,
        }

        results = {}
        for rank, (sname, data) in enumerate(ranked):
            nets    = per_table_nets.get(sname, [])
            avg_net = data['total_net'] / num_tables
            avg_roi = avg_net / starting_chips
            hands   = data['hands_played']
            if len(nets) > 1:
                sd = (sum((x - avg_net) ** 2 for x in nets) / (len(nets) - 1)) ** 0.5
                ci = 1.96 * sd / math.sqrt(len(nets))
            else:
                sd = ci = 0.0
            results[sname] = {
                'rank':        rank + 1,
                'avg_net_roi': round(avg_roi, 4),
                'std_dev_roi': round(sd / starting_chips, 4),
                'ci_95_roi':   round(ci / starting_chips, 4),
                'win_rate':    round(data['hands_won'] / hands * 100, 2) if hands > 0 else 0.0,
                'avg_rebuys':  round(data['total_rebuys'] / num_tables, 2),
                'tables_won':  data['tables_won'],
            }

        self._data['sessions'].append({
            'session_id': self._next_session_id(),
            'type':       'all_vs_all',
            'date':       datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'config':     config,
            'results':    results,
        })

        # Update all-time
        key = self.bucket_key(diff, short_deck, ante, depth)
        at  = self._data['alltime']['all_vs_all']
        if key not in at:
            at[key] = {'total_tables': 0, 'sessions_count': 0}
        at[key]['total_tables']  += num_tables
        at[key]['sessions_count'] += 1

        for rank, (sname, data) in enumerate(ranked):
            if sname not in at[key]:
                at[key][sname] = {
                    'total_roi':          0.0,
                    'total_hands_played': 0,
                    'total_hands_won':    0,
                    'total_rebuys':       0,
                    'tables_won':         0,
                    'rank_histogram':     {},
                }
            s = at[key][sname]
            avg_roi = data['total_net'] / num_tables / starting_chips
            s['total_roi']          += round(avg_roi * num_tables, 6)
            s['total_hands_played'] += data['hands_played']
            s['total_hands_won']    += data['hands_won']
            s['total_rebuys']       += data['total_rebuys']
            s['tables_won']         += data['tables_won']
            rk = str(rank + 1)
            s['rank_histogram'][rk] = s['rank_histogram'].get(rk, 0) + 1

        self._save()

    def save_h2h(self, num_tables: int, hands_per_table: int,
                 starting_chips: int, big_blind: int,
                 difficulty: float, strat_names: list,
                 wins: list, net_matrix: list) -> None:
        diff  = self.difficulty_label(difficulty)
        depth = self.stack_depth(big_blind, starting_chips)
        n     = len(strat_names)

        win_rates         = {}
        overall_win_rates = {}
        for i, s_i in enumerate(strat_names):
            win_rates[s_i] = {
                s_j: round(wins[i][j] / num_tables * 100, 1)
                for j, s_j in enumerate(strat_names) if i != j
            }
            total_wins = sum(wins[i][j] for j in range(n) if j != i)
            overall_win_rates[s_i] = round(total_wins / ((n - 1) * num_tables) * 100, 1)

        self._data['sessions'].append({
            'session_id': self._next_session_id(),
            'type':       'h2h',
            'date':       datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'config': {
                'num_tables':      num_tables,
                'hands_per_table': hands_per_table,
                'starting_chips':  starting_chips,
                'big_blind':       big_blind,
                'difficulty':      diff,
                'stack_depth':     depth,
            },
            'results': {
                'win_rates':         win_rates,
                'overall_win_rates': overall_win_rates,
                'matchups_per_pair': num_tables,
            },
        })

        # Update all-time (H2H has no ante/short_deck options)
        key = self.bucket_key(diff, False, False, depth)
        at  = self._data['alltime']['h2h']
        if key not in at:
            at[key] = {'sessions_count': 0}
        at[key]['sessions_count'] += 1

        for i, s_i in enumerate(strat_names):
            if s_i not in at[key]:
                at[key][s_i] = {'vs': {}, 'overall_wins': 0, 'overall_total': 0}
            entry = at[key][s_i]
            for j, s_j in enumerate(strat_names):
                if i == j:
                    continue
                if s_j not in entry['vs']:
                    entry['vs'][s_j] = {'wins': 0, 'total': 0}
                entry['vs'][s_j]['wins']  += wins[i][j]
                entry['vs'][s_j]['total'] += num_tables
            entry['overall_wins']  += sum(wins[i][j] for j in range(n) if j != i)
            entry['overall_total'] += (n - 1) * num_tables

        self._save()

    def save_param_sweep(self, num_tables: int, hands_per_table: int,
                         starting_chips: int, big_blind: int,
                         difficulty: float, param_name: str,
                         results: list) -> None:
        diff  = self.difficulty_label(difficulty)
        depth = self.stack_depth(big_blind, starting_chips)
        best  = max(results, key=lambda r: r[1])

        self._data['sessions'].append({
            'session_id': self._next_session_id(),
            'type':       'param_sweep',
            'date':       datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'config': {
                'num_tables':      num_tables,
                'hands_per_table': hands_per_table,
                'starting_chips':  starting_chips,
                'big_blind':       big_blind,
                'difficulty':      diff,
                'stack_depth':     depth,
            },
            'results': {
                'param_name':      param_name,
                'optimal_value':   best[0],
                'optimal_net_roi': round(best[1] / starting_chips, 4),
                'data_points': [
                    {
                        'value':       v,
                        'avg_net_roi': round(avg / starting_chips, 4),
                        'std_dev_roi': round(sd / starting_chips, 4),
                    }
                    for v, avg, sd in results
                ],
            },
        })
        self._save()

    # ── Viewer ────────────────────────────────────────────────────────────────

    def get_data(self) -> Dict:
        """Return the raw loaded stats dict (read-only accessor for the API)."""
        return self._data

    def print_stats(self) -> None:
        print("\n" + "=" * 60)
        print("  Simulation Statistics")
        print("=" * 60)
        print("  1. Session history")
        print("  2. All-time All-vs-All rankings")
        print("  3. All-time Head-to-Head matrix")

        choice = input("\nChoose (default 1): ").strip()
        if choice == '2':
            self._print_alltime_all_vs_all()
        elif choice == '3':
            self._print_alltime_h2h()
        else:
            self._print_session_history()

    def _print_session_history(self) -> None:
        sessions = self._data['sessions']
        if not sessions:
            print("\n  No simulation sessions recorded yet.")
            return

        print(f"\n  {'#':>4}  {'Type':<12}  {'Date':<20}  {'Difficulty':<8}  {'Config':<22}  Top Result")
        print(f"  {'─'*4}  {'─'*12}  {'─'*20}  {'─'*8}  {'─'*22}  {'─'*30}")

        for s in sessions:
            cfg  = s['config']
            tags = [cfg['stack_depth'] + ' stack']
            if cfg.get('ante'):
                tags.append('ante')
            if cfg.get('short_deck'):
                tags.append('short')
            config_str = ', '.join(tags)

            if s['type'] == 'all_vs_all':
                top  = min(s['results'].items(), key=lambda x: x[1]['rank'])
                roi  = top[1]['avg_net_roi']
                top_str = f"{top[0]} ({roi*100:+.1f}% ROI)"
            elif s['type'] == 'h2h':
                best    = max(s['results']['overall_win_rates'].items(), key=lambda x: x[1])
                top_str = f"{best[0]} ({best[1]:.1f}% overall)"
            else:
                r       = s['results']
                top_str = f"{r['param_name']}={r['optimal_value']} ({r['optimal_net_roi']*100:+.1f}% ROI)"

            print(f"  {s['session_id']:>4}  {s['type']:<12}  {s['date']:<20}  "
                  f"{cfg['difficulty']:<8}  {config_str:<22}  {top_str}")

    def _pick_bucket(self, at: Dict, label: str) -> Optional[str]:
        if not at:
            print(f"\n  No {label} all-time data recorded yet.")
            return None

        keys = list(at.keys())
        if len(keys) == 1:
            return keys[0]

        print(f"\n  Available config buckets:")
        for i, k in enumerate(keys, 1):
            diff, short, ante, depth = k.split('|')
            tags = [depth + ' stack']
            if short == 'True':
                tags.append('short deck')
            if ante == 'True':
                tags.append('ante')
            sc = at[k].get('sessions_count', 0)
            tt = at[k].get('total_tables', 0)
            table_info = f"  ({sc} sessions, {tt:,} tables)" if tt else f"  ({sc} sessions)"
            print(f"  {i}. {diff:<8}  {', '.join(tags):<28}{table_info}")

        raw = input("\nChoose bucket (default 1): ").strip()
        try:
            return keys[int(raw) - 1 if raw else 0]
        except (ValueError, IndexError):
            return keys[0]

    def _print_alltime_all_vs_all(self) -> None:
        at  = self._data['alltime']['all_vs_all']
        key = self._pick_bucket(at, "All-vs-All")
        if not key:
            return

        data         = at[key]
        diff, short, ante, depth = key.split('|')
        total_tables = data.get('total_tables', 0)
        sessions     = data.get('sessions_count', 0)

        header = f"  ALL-TIME ALL-vs-ALL  |  {diff}  |  {depth} stack"
        if ante  == 'True': header += '  |  ante'
        if short == 'True': header += '  |  short deck'

        print(f"\n{'=' * 80}")
        print(header)
        print(f"  {sessions} sessions, {total_tables:,} total tables")
        print(f"{'=' * 80}")

        rows = []
        for sname, s in data.items():
            if not isinstance(s, dict) or 'total_roi' not in s:
                continue
            avg_roi  = s['total_roi'] / total_tables if total_tables > 0 else 0
            win_rate = (s['total_hands_won'] / s['total_hands_played'] * 100
                        if s['total_hands_played'] > 0 else 0)
            firsts   = s['rank_histogram'].get('1', 0)
            rows.append((sname, avg_roi, win_rate, s['tables_won'],
                         s['total_rebuys'], firsts, total_tables))

        rows.sort(key=lambda x: x[1], reverse=True)

        print(f"\n  {'Rank':<5}  {'Strategy':<18}  {'Avg ROI':>8}  {'Win%':>6}  "
              f"{'Tbl Won':>9}  {'1st Place':>9}  {'Rebuys':>7}")
        print(f"  {'─'*5}  {'─'*18}  {'─'*8}  {'─'*6}  {'─'*9}  {'─'*9}  {'─'*7}")

        for rank, (sname, avg_roi, win_rate, tbl_won, rebuys, firsts, _) in enumerate(rows, 1):
            color   = _GREEN if avg_roi >= 0 else _RED
            roi_str = f"{avg_roi*100:+.2f}%"
            print(f"  {rank:<5}  {sname:<18}  {color}{roi_str:>8}{_RESET}"
                  f"  {win_rate:>5.1f}%  {tbl_won:>9,}  {firsts:>9}  {rebuys:>7,}")

    def _print_alltime_h2h(self) -> None:
        at  = self._data['alltime']['h2h']
        key = self._pick_bucket(at, "H2H")
        if not key:
            return

        data = at[key]
        diff, _, _, depth = key.split('|')
        sessions = data.get('sessions_count', 0)

        strat_names = [k for k, v in data.items() if isinstance(v, dict) and 'vs' in v]
        if not strat_names:
            print("  No H2H data in this bucket.")
            return

        abbrevs = [_SHORT_NAMES.get(s, s[:8]) for s in strat_names]
        ROW_W   = 16

        print(f"\n{'=' * 80}")
        print(f"  ALL-TIME HEAD-TO-HEAD  |  {diff}  |  {depth} stack  |  {sessions} sessions")
        print(f"  (row beats column)")
        print(f"{'=' * 80}")

        print(f"\n  {'':>{ROW_W}}", end='')
        for a in abbrevs:
            print(f" {a:>8}", end='')
        print(f" {'Overall':>8}")
        print(f"  {'':>{ROW_W}}" + " --------" * len(strat_names) + " --------")

        for s_i in strat_names:
            entry = data.get(s_i, {})
            print(f"  {s_i:>{ROW_W}}", end='')
            for s_j in strat_names:
                if s_i == s_j:
                    print(f" {'---':>8}", end='')
                    continue
                vs    = entry.get('vs', {}).get(s_j, {})
                total = vs.get('total', 0)
                if total > 0:
                    pct  = vs['wins'] / total * 100
                    cell = f"{pct:>6.1f}%"
                    if   pct >= 60: print(f" {_GREEN}{cell}{_RESET} ", end='')
                    elif pct <= 40: print(f" {_RED}{cell}{_RESET} ", end='')
                    else:           print(f" {cell} ", end='')
                else:
                    print(f" {'N/A':>8}", end='')

            ov_total = entry.get('overall_total', 0)
            if ov_total > 0:
                ov_pct = entry['overall_wins'] / ov_total * 100
                cell   = f"{ov_pct:>6.1f}%"
                if   ov_pct >= 55: print(f" {_GREEN}{cell}{_RESET}")
                elif ov_pct <  45: print(f" {_RED}{cell}{_RESET}")
                else:              print(f" {cell}")
            else:
                print(f" {'N/A':>8}")
