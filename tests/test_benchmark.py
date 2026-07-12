"""Tests for the extracted benchmark runners (core/benchmark.py).

Tiny runs (2 tables x 20 hands) that assert result-dict shapes, that all eight
strategy archetypes are present, and that the progress / should_stop callbacks
behave as documented. The sims are stochastic, so only shapes are checked.
"""
from core.benchmark import (
    run_all_vs_all, run_h2h, run_param_sweep, _BENCHMARK_STRATEGIES,
)
from strategies.difficulty import NORMAL

ALL_NAMES = {s[0] for s in _BENCHMARK_STRATEGIES}
SWEEP_BASE = dict(play_range=0.5, aggression=0.5, bluff_freq=0.25, call_freq=0.5)


# ── all-vs-all ────────────────────────────────────────────────────────────────

def test_all_vs_all_shape_and_strategies():
    r = run_all_vs_all(2, 20, 1000, 20, NORMAL)
    assert set(r) == {'ranked', 'per_table_nets', 'convergence_snapshots',
                      'street_totals', 'street_hands', 'elapsed'}
    names = {name for name, _ in r['ranked']}
    assert names == ALL_NAMES
    assert set(r['per_table_nets']) == ALL_NAMES
    # per_table_nets has one entry per table for every strategy.
    for name in ALL_NAMES:
        assert len(r['per_table_nets'][name]) == 2
    assert 'stopped' not in r


def test_all_vs_all_progress_reaches_total():
    calls = []
    run_all_vs_all(2, 20, 1000, 20, NORMAL, progress=lambda d, t: calls.append((d, t)))
    assert calls, "progress was never called"
    assert calls[-1] == (2, 2)


def test_all_vs_all_should_stop_returns_partial():
    r = run_all_vs_all(2, 20, 1000, 20, NORMAL, should_stop=lambda: True)
    assert r['stopped'] is True
    # Stopped before any table ran → no per-table samples recorded.
    for name in ALL_NAMES:
        assert r['per_table_nets'][name] == []


# ── head-to-head ──────────────────────────────────────────────────────────────

def test_h2h_shape():
    r = run_h2h(2, 20, 1000, 20, NORMAL)
    assert set(r) == {'strat_names', 'wins', 'net_matrix', 'elapsed'}
    n = len(_BENCHMARK_STRATEGIES)
    assert set(r['strat_names']) == ALL_NAMES
    assert len(r['wins']) == n and all(len(row) == n for row in r['wins'])
    assert len(r['net_matrix']) == n and all(len(row) == n for row in r['net_matrix'])
    assert 'stopped' not in r


def test_h2h_progress_reaches_total():
    calls = []
    run_h2h(2, 20, 1000, 20, NORMAL, progress=lambda d, t: calls.append((d, t)))
    n = len(_BENCHMARK_STRATEGIES)
    n_matchups = n * (n - 1) // 2
    assert calls[-1] == (n_matchups, n_matchups)


def test_h2h_should_stop_returns_partial():
    r = run_h2h(2, 20, 1000, 20, NORMAL, should_stop=lambda: True)
    assert r['stopped'] is True
    assert all(cell == 0 for row in r['wins'] for cell in row)


# ── parameter sweep ───────────────────────────────────────────────────────────

def test_param_sweep_shape():
    steps = [0.3, 0.6]
    r = run_param_sweep('aggression', steps, SWEEP_BASE, 2, 20, 1000, 20, NORMAL)
    assert set(r) == {'results', 'elapsed'}
    assert len(r['results']) == len(steps)
    for value, avg_net, sd in r['results']:
        assert value in steps
    assert 'stopped' not in r


def test_param_sweep_progress_reaches_total():
    steps = [0.3, 0.6]
    calls = []
    run_param_sweep('aggression', steps, SWEEP_BASE, 2, 20, 1000, 20, NORMAL,
                    progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (len(steps), len(steps))


def test_param_sweep_should_stop_returns_partial():
    steps = [0.3, 0.6]
    r = run_param_sweep('aggression', steps, SWEEP_BASE, 2, 20, 1000, 20, NORMAL,
                        should_stop=lambda: True)
    assert r['stopped'] is True
    assert r['results'] == []
