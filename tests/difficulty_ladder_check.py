"""
Phase 2 Task 10 acceptance check — the difficulty ladder.

Not a pytest test (no test_ prefix): a full run takes several minutes because
HARD/EXPERT use 200-trial Monte Carlo equity on the turn/river. Run manually:

    python tests/difficulty_ladder_check.py

One BalancedStrategy at each level (EASY, NORMAL, HARD, EXPERT) plays 48
tables x 150 hands (fresh strategy per table) against three NORMAL
BalancedStrategy opponents. Asserts net(EASY) < net(NORMAL) < net(HARD) <
net(EXPERT), with a clear margin between the extremes — proof the mistake
profiles actually cost/save EV in that order, which noise-only difficulty
never guaranteed.
"""
import time

from core.game import Game
from players.bot import BotPlayer
from strategies.engine import BalancedStrategy
from strategies.difficulty import EASY, NORMAL, HARD, EXPERT


def run_ladder_level(level, num_tables=48, hands_per_table=150,
                      starting_chips=1000, big_blind=20) -> int:
    """Total net chips for one BalancedStrategy(level) subject across
    num_tables independent tables, each with three NORMAL opponents."""
    total_net = 0
    for _ in range(num_tables):
        g = Game(big_blind=big_blind, hands_per_level=9999,
                  live_output=False, game_mode='cash')
        subject_id = 'subject'
        g.add_player(BotPlayer(subject_id, 'Subject', starting_chips, BalancedStrategy(level)))
        for i in range(3):
            g.add_player(BotPlayer(f'opp{i}', f'Opp{i}', starting_chips, BalancedStrategy(NORMAL)))
        for _ in range(hands_per_table):
            g.start_game()
            for p in g.players:
                if p.chips == 0:
                    p.chips = starting_chips
                    g.stats[p.player_id]['total_invested'] += starting_chips
        s = g.stats[subject_id]
        net = next(p.chips for p in g.players if p.player_id == subject_id) - s['total_invested']
        total_net += net
    return total_net


def main():
    t0 = time.time()
    results = {}
    for label, level in [('EASY', EASY), ('NORMAL', NORMAL), ('HARD', HARD), ('EXPERT', EXPERT)]:
        net = run_ladder_level(level)
        results[label] = net
        print(f"{label:8s} {net:>10d}")
    print(f"elapsed {time.time() - t0:.1f}s")

    assert results['EASY'] < results['NORMAL'] < results['HARD'] < results['EXPERT'], (
        f"non-monotone difficulty ladder: {results}")
    assert results['EXPERT'] - results['EASY'] > 0, f"no clear margin: {results}"
    print("OK: monotone easy < normal < hard < expert")


if __name__ == "__main__":
    main()
