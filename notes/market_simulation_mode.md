# Market Simulation Mode — Design & Implementation Plan

## Overview

A large-table tournament variant (25–40 bot players) designed to simulate trading market
dynamics. Each bot represents a market participant with a distinct risk profile and
decision style. Blind escalation simulates time pressure. Chip distribution over time
mirrors capital concentration and wealth dynamics.

This mode runs without a human player. The goal is to observe and measure how different
strategy archetypes perform in a competitive, resource-constrained environment over many
hands (or many runs).

---

## Concept Mapping: Poker → Trading Market

| Poker Element         | Market Equivalent                                      |
|-----------------------|--------------------------------------------------------|
| Hole cards            | Private information (asymmetric information)           |
| Pot size              | Price discovery through competitive bidding            |
| Blind escalation      | Time pressure / margin calls / funding costs           |
| Chip stack            | Capital / account balance                              |
| Fold                  | Exit position / stop-loss                              |
| All-in                | Leveraged / concentrated position                      |
| Raise                 | Aggressive bid / offer                                 |
| Call                  | Follow the market / passive execution                  |
| Elimination           | Bankruptcy / margin call / market exit                 |
| Strategy archetype    | Trader personality (risk-averse, momentum, speculator) |
| Chip distribution     | Wealth / capital concentration (Gini coefficient)      |
| Multi-run aggregation | Monte Carlo simulation / statistical sampling          |

---

## Strategy → Trader Archetype Mapping

| Strategy            | Trader Type               | Description                                          |
|---------------------|---------------------------|------------------------------------------------------|
| `nit`               | Risk-averse / value only  | Waits for near-certain setups. Rarely participates.  |
| `tight_passive`     | Conservative long-only    | Enters selectively, holds, rarely leverages.         |
| `tight_aggressive`  | Disciplined swing trader  | Selective entry, high conviction, cuts losers fast.  |
| `balanced`          | Quantitative / systematic | Balanced risk/reward, pot odds driven.               |
| `loose_passive`     | Retail / FOMO buyer       | Enters many positions, holds too long.               |
| `loose_aggressive`  | Momentum / trend trader   | Wide participation, constant pressure, high variance.|
| `maniac`            | Reckless speculator       | Ignores odds, maximum aggression, early flame-out.   |

---

## Architecture

### New files to create

```
poker-terminal/
├── notes/
│   └── market_simulation_mode.md        ← this file
├── simulation/
│   ├── __init__.py
│   ├── market_runner.py                  ← single-run engine
│   ├── batch_runner.py                   ← multi-run aggregator
│   ├── metrics.py                        ← Gini, volatility, etc.
│   └── reporter.py                       ← output formatting + CSV export
└── players/
    └── roster.py                         ← extend to 40 bots
```

### Modified files

| File                  | Change                                                         |
|-----------------------|----------------------------------------------------------------|
| `players/roster.py`   | Add `market_roster(n, seed)` factory for 25–40 procedural bots|
| `core/game.py`        | Add `output_mode` param (verbose/summary/silent)              |
| `core/game.py`        | Add exponential blind schedule option                          |
| `core/game.py`        | Emit per-hand chip snapshot to a listener/callback             |
| `main.py`             | Add Market Simulation entry point                              |

---

## Detailed Component Design

### 1. Roster Expansion — `players/roster.py`

Add a `market_roster(n: int, difficulty: float, seed: int = None) -> list` factory.

**Strategy distribution for N bots (proportional):**

| Strategy           | % of table | Example for N=30 |
|--------------------|-----------|------------------|
| `balanced`         | 20%       | 6                |
| `tight_aggressive` | 18%       | 5                |
| `tight_passive`    | 15%       | 4                |
| `loose_passive`    | 15%       | 4                |
| `loose_aggressive` | 13%       | 4                |
| `nit`              | 10%       | 3                |
| `maniac`           | 9%        | 3 (capped at 3)  |

**Bot naming:** Procedural names from a pool of 50+ names. If `seed` is set, the
shuffle is deterministic (reproducible runs).

**Difficulty per strategy:** Each strategy type gets a slight difficulty variation to
add realism:
- Maniac: always `EASY` (maniacs make mistakes)
- Nit: `HARD` (nits are disciplined)
- Others: use the passed `difficulty` ± small random offset

```python
def market_roster(n: int, difficulty: float = NORMAL, seed: int = None) -> list:
    """
    Generate n bots with a realistic strategy distribution.
    seed: set for reproducible simulations.
    """
```

---

### 2. Output Mode — `core/game.py`

Add `output_mode: str = 'verbose'` parameter to `Game.__init__`.

| Mode      | What is printed                                                    |
|-----------|--------------------------------------------------------------------|
| `verbose` | Current behaviour — every action, every card, every pot            |
| `summary` | One line per hand: hand#, winner, pot size, players remaining      |
| `silent`  | Nothing during play; stats printed at end                          |

**Implementation:** Replace `if self.live_output: print(msg)` with a dispatcher:

```python
def log(self, msg: str):
    self.logs.append(msg)
    if self.output_mode == 'verbose':
        print(msg)
    elif self.output_mode == 'summary' and msg.startswith('>>'):
        print(msg)  # only print win lines
```

**Summary line format (one per hand):**
```
Hand #12 | Pot: 340 | Winner: Bot_Alice (Flush) | Players left: 28/40
```

---

### 3. Blind Escalation Styles — `core/game.py`

Add `blind_style: str = 'uniform'` parameter.

| Style         | Schedule (starting BB=20)                  | Use case              |
|---------------|---------------------------------------------|-----------------------|
| `uniform`     | 20, 40, 60, 80, 100 ...                    | Current behaviour     |
| `turbo`       | 20, 40, 60 ... but every 2 hands           | Fast games            |
| `exponential` | 20, 40, 80, 160, 320, 640 ...              | Market simulation     |
| `hyper`       | 20, 60, 180, 540 ... (3× each level)       | Very fast elimination |

**Implementation:** Replace `blind_schedule` list construction in `__init__`:

```python
def _build_blind_schedule(self, big_blind, style, levels=12):
    if style == 'exponential':
        return [big_blind * (2 ** i) for i in range(levels)]
    elif style == 'hyper':
        return [big_blind * (3 ** i) for i in range(levels)]
    else:  # uniform
        return [big_blind * (i + 1) for i in range(levels)]
```

For market simulation: use `exponential` with `hands_per_level=3`.

---

### 4. Chip History Tracking — `core/game.py`

After each hand ends (`_handle_end`), record a snapshot of all chip counts.

**Data structure:**
```python
self.chip_history: List[Dict[str, int]] = []
# Each entry: {'hand': 5, 'Bot_Alice': 1200, 'Bot_Bob': 0, ...}
```

**Hook in `_handle_end`:**
```python
snapshot = {'hand': self.hand_count}
snapshot.update({p.name: p.chips for p in self.players})
self.chip_history.append(snapshot)
```

This data feeds the metrics and reporter modules.

---

### 5. Metrics — `simulation/metrics.py`

```python
def gini_coefficient(chip_counts: list) -> float:
    """
    Measures capital concentration. 0 = perfect equality, 1 = one player has all chips.
    Uses the standard economic Gini formula.
    """

def chip_volatility(history: list, player_name: str) -> float:
    """Standard deviation of chip count changes per hand for a player."""

def elimination_curve(chip_history: list) -> list:
    """Returns list of (hand_number, players_remaining) pairs."""

def strategy_survival_rate(players: list, stats: dict) -> dict:
    """
    Groups players by strategy archetype.
    Returns: {strategy_name: avg_finish_position, avg_final_chips, survival_rate}
    """

def top_n_leaders(chip_snapshot: dict, n: int = 5) -> list:
    """Returns top N (name, chips) pairs from a snapshot."""
```

---

### 6. Market Runner — `simulation/market_runner.py`

Runs a single simulation from start to finish.

```python
class MarketRunner:
    def __init__(self, config: dict):
        """
        config keys:
            num_players     : int  (25–40)
            starting_chips  : int  (default 1000)
            big_blind       : int  (default 20)
            hands_per_level : int  (default 3)
            blind_style     : str  ('exponential')
            difficulty      : float (NORMAL)
            output_mode     : str  ('summary' or 'silent')
            seed            : int | None
        """

    def run(self) -> SimulationResult:
        """
        Runs the game to completion (one winner or max_hands reached).
        Returns a SimulationResult with chip_history, final_stats, elimination_order.
        """

    def run_hands(self, n: int) -> None:
        """Run exactly n hands (for step-by-step or batch use)."""
```

**SimulationResult dataclass:**
```python
@dataclass
class SimulationResult:
    config: dict
    chip_history: list          # per-hand chip snapshots
    elimination_order: list     # [(player_name, strategy, hand_eliminated)]
    final_stats: dict           # game.stats
    gini_per_hand: list         # Gini coefficient per hand
    strategy_summary: dict      # per-strategy aggregate performance
    total_hands: int
    winner: str
```

---

### 7. Batch Runner — `simulation/batch_runner.py`

Runs the same configuration multiple times for statistical significance.

```python
class BatchRunner:
    def __init__(self, config: dict, num_runs: int = 10):
        ...

    def run(self) -> BatchResult:
        """
        Runs num_runs independent simulations.
        Aggregates results across all runs.
        """

    def run_parallel(self, workers: int = 4) -> BatchResult:
        """Parallel execution using multiprocessing.Pool."""
```

**BatchResult:**
```python
@dataclass
class BatchResult:
    num_runs: int
    config: dict
    strategy_win_rates: dict        # {strategy: win% across all runs}
    strategy_avg_finish: dict       # {strategy: avg finish position}
    avg_gini_curve: list            # avg Gini per hand across runs
    avg_elimination_curve: list     # avg players remaining per hand
    avg_total_hands: float
```

---

### 8. Reporter — `simulation/reporter.py`

**Terminal output (summary mode):**
```
=== MARKET SIMULATION RESULT ===
Runs: 10 | Players: 30 | Blinds: exponential | Difficulty: normal

STRATEGY PERFORMANCE
  tight_aggressive   Win rate: 28%   Avg finish: 4.2   Avg final chips: 3240
  balanced           Win rate: 22%   Avg finish: 6.1   Avg final chips: 2810
  nit                Win rate: 18%   Avg finish: 5.8   Avg final chips: 2650
  loose_aggressive   Win rate: 14%   Avg finish: 12.3  Avg final chips: 820
  maniac             Win rate:  2%   Avg finish: 27.1  Avg final chips: 0

CAPITAL CONCENTRATION (Gini)
  Start: 0.00 (equal)  →  Hand 20: 0.42  →  Hand 40: 0.71  →  End: 0.94

ELIMINATION CURVE
  Hand 10: 28/30 remain
  Hand 25: 20/30 remain
  Hand 50: 10/30 remain
  Hand 78: 1/30 remain (winner: Bot_Alice, tight_aggressive)
```

**CSV export:**
```python
def export_chip_history_csv(result: SimulationResult, path: str) -> None:
    """Writes chip_history to CSV: columns = hand, player1, player2, ..."""

def export_strategy_summary_csv(batch: BatchResult, path: str) -> None:
    """Writes strategy performance across all runs to CSV."""
```

---

### 9. Main Entry Point — `main.py`

Add "Market Simulation" as option 4 in the game mode menu:

```
Game Mode:
  1. Tournament  (blinds escalate each level)
  2. Cash Game   (fixed blinds, unlimited rebuys)
  3. Spectator   (watch bots play)
  4. Market Simulation  (large bot table, analytics output)
```

When selected, prompt:
```
Number of players (25–40, default 30):
Blind style: 1. Exponential (default)  2. Hyper (3×)
Difficulty: 1. Easy  2. Normal (default)  3. Hard
Output: 1. Summary (default)  2. Silent (stats only)
Number of runs (1 = single sim, 10 = batch, default 1):
Export CSV? (y/n, default n):
Random seed (leave blank for random):
```

---

## Implementation Order (Suggested)

| Step | Task                                             | Files                        | Complexity |
|------|--------------------------------------------------|------------------------------|------------|
| 1    | Add `output_mode` to `Game`                      | `core/game.py`               | Low        |
| 2    | Add `blind_style` + exponential schedule         | `core/game.py`               | Low        |
| 3    | Add chip history tracking (`chip_history`)       | `core/game.py`               | Low        |
| 4    | Expand roster (`market_roster`)                  | `players/roster.py`          | Low        |
| 5    | Create `simulation/metrics.py`                   | new file                     | Medium     |
| 6    | Create `simulation/market_runner.py`             | new file                     | Medium     |
| 7    | Create `simulation/reporter.py`                  | new file                     | Medium     |
| 8    | Create `simulation/batch_runner.py`              | new file                     | Medium     |
| 9    | Wire into `main.py`                              | `main.py`                    | Low        |
| 10   | Write tests for simulation module                | `tests/test_simulation.py`   | Medium     |

Total: ~8 new/modified files. Steps 1–4 are isolated and safe to do first without
touching the simulation module at all.

---

## Open Questions / Risks

### Side pot edge case
With 40 players and frequent all-ins, `PotManager.calculate_pots()` may create
15–20 side pots per hand. This code path is untested at scale. Should run a
stress test with 40 players before declaring the mode stable.

**Mitigation:** Add a dedicated stress test in `tests/test_simulation.py` that runs
50 hands with 40 bots and asserts no exceptions and final chip totals balance.

### Statistical noise
A single run with 40 random-card players is highly noisy. Strategy differences only
emerge clearly after 10+ runs. Batch runner is essential for meaningful insights.

**Mitigation:** Default to `num_runs=10` in the market sim prompt. Show confidence
intervals or ranges in the strategy performance output.

### Convergence time
With 40 players at 1000 chips each and exponential blinds starting at 20:
- Hands to first elimination: ~5–10
- Hands to half the field gone: ~25–40
- Hands to one winner: ~60–100 (estimate)

This is manageable since bots decide instantly. A 100-hand run completes in
under a second.

### Display width
A 40-player `print_stats` table will have 40 rows. The current column widths fit
in 90 chars. No change needed. But the chip history CSV will have 41 columns
(hand + 40 players), which is fine for spreadsheet analysis.

---

## Future Extensions (out of scope for now)

- **Price chart**: ASCII chart of top-3 chip leaders over time (like a stock chart)
- **Market events**: mid-game shocks (e.g. "all players lose 10% chips" simulating a market crash)
- **Coalition detection**: identify hands where multiple bots consistently fold to the same player (clustering)
- **Strategy evolution**: bots adjust their `play_range`/`aggression` based on their chip relative to the field (adaptive agents)
- **Export to Jupyter**: output chip_history as a pandas DataFrame for external analysis
