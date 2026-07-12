# Browser Full Menu — Simulations & All-Time Stats in the Web Client

**Status:** Spec, not yet implemented.
**The gap this closes:** the TUI's main menu (`main.py::_collect_settings`) has
four modes — 1. Tournament, 2. Strategy Benchmark, 3. View Tournament Stats,
4. View Simulation Stats. The browser client has ONLY mode 1: it boots straight
into the game-settings form. This doc brings the other three modes (and a real
landing menu) to the browser.

**Audience:** an implementer per phase in a fresh context window. Read
`notes/browser_play_assessment.md` §4 (as-built API conventions) first. The
as-built code always wins over any doc prose.

**Ground rules:** all API additions follow the existing conventions in
`api/server.py` (no `/api` prefix, JSON errors as `409 {"reason": ...}`,
`asyncio.to_thread` for engine work). Client stays vanilla JS, no build step,
existing dark theme, tables + CSS bars only — no chart libraries.

---

## 0. Current facts (verified 2026-07-12)

- `main.py` modes 2–4 are driven by `input()` prompts and `print()` — nothing
  reusable as-is for HTTP, but the underlying data layers are:
- **`core/stats_persistent.py` — PersistentStatsManager** (`player_stats.json`
  at repo root). Has proper getters: `get_all_players_by_difficulty(difficulty=None)`,
  `get_player_history(player_id, difficulty=None)`, `get_session_history(difficulty=None)`.
  Difficulty stored as labels via `_difficulty_to_label` (Easy/Normal/Hard).
  **Browser sessions are never saved into it today** — `api/` never touches it,
  so the viewer would show only TUI sessions until Phase M1 adds the save hook.
- **`core/simulation_stats.py` — SimulationStatsManager** (`simulation_stats.json`
  at repo root). Stores structured session entries + all-time buckets via
  `save_all_vs_all` / `save_h2h` / `save_param_sweep`; read side is `_load()`
  plus print methods only (no getters — Phase M2 exposes the raw dict).
- **The three benchmark runners live inside `main.py`**:
  `_run_strategy_benchmark` (all-vs-all), `_run_h2h_benchmark` (round-robin
  matrix), `_run_parameter_sweep`. Each interleaves: prompt → simulation loops
  (building bot-only `Game`s, cheap per hand but 10⁴–10⁵ hands total) →
  `\r`-progress printing → result printing → SimulationStatsManager save.
  The compute cores build plain data structures (`agg`/`ranked`,
  `per_table_nets`, `convergence_snapshots`, `street_totals/street_hands`;
  `wins`/`net_matrix`; sweep `results`) that the printers then consume — they
  are cleanly extractable (Phase M3).
- Benchmark difficulty has FOUR levels incl. Expert (`_prompt_difficulty`:
  0.4/0.6/0.75/0.9) — unlike tournament's three. The simulation API must
  accept all four.
- Web client screens are `<section>`s toggled by `S.phase` in `web/app.js`
  (`"settings" | "table"`); `render()` drives visibility.

## 1. Phase plan (one fresh session per phase, one commit each)

| phase | what | touches |
|---|---|---|
| M1 | Landing menu + tournament-stats viewer + session persistence + Quit | `api/`, `web/`, `tests/test_api.py` |
| M2 | Simulation-stats viewer | `api/server.py`, `web/`, tests |
| M3 | Extract benchmark runners out of `main.py` (no behavior change) | `core/benchmark.py` (new), `main.py`, `tests/test_benchmark.py` (new) |
| M4 | Simulation job API + browser simulation UI | `api/`, `web/`, tests |

M1 and M2 are independent. M4 requires M3. Do M3 before or in parallel with
M1/M2 if multiple sessions run.

---

## 2. Phase M1 — Landing menu, tournament stats viewer, persistence, quit

### M1.1 Landing menu (client)

New first screen (`S.phase = "menu"`), shown instead of the settings form:

```
  POKER TERMINAL
  ▶ Play            → existing settings form (tournament/cash)
  ▶ Simulation      → disabled placeholder until M4 ("coming in M4")
  ▶ Tournament stats→ stats viewer screen (M1.3)
  ▶ Simulation stats→ disabled placeholder until M2
```

- `S.phase` gains `"menu" | "stats_view"`; every non-table screen gets a
  "← Menu" back button. `restoreSession()` still jumps straight to `"table"`
  when a live game exists (menu is only for idle state).
- The settings form gets a back button and no longer *is* the landing page.

### M1.2 Persist web sessions (server) — prerequisite for the viewer to be useful

- `api/sessions.py`: add `GameSession.persist()` — build `game_stats` exactly
  like the call site at the end of `main.py::main()`
  (`{'hand_count': g.hand_count}` + `game_stats[pid] = g.stats[pid]` per
  player), then `PersistentStatsManager().save_session(session_id=...,
  difficulty=<the EASY/NORMAL/HARD float already imported>, players=game.players,
  game_stats=..., game_mode=settings["game_mode"])`. Derive `session_id` from
  `len(get_session_history()) + 1` (inspect `save_session` first; follow
  whatever uniqueness it actually needs). Guards: skip if `hand_count == 0`;
  `self._persisted` flag → at most once per session.
- Call `persist()` from: the `GameOverError` path of `start_next_hand`, and
  the `DELETE /games/{id}` handler (persist, then remove).
- Client: **Quit table** button next to "Next hand" (between-hands only) →
  confirm → `DELETE /games/{id}` → `newGame()` (which now lands on the menu).
- Tests: monkeypatch the manager (or its file path) to `tmp_path`; assert one
  record after play→delete, zero records for a 0-hand delete.

### M1.3 Tournament stats endpoints + viewer

Endpoints (read-only, thin wrappers over the existing getters — no new logic):

| route | returns |
|---|---|
| `GET /stats/tournament/players?difficulty=` | `get_all_players_by_difficulty(...)` |
| `GET /stats/tournament/players/{player_id}?difficulty=` | `get_player_history(...)` |
| `GET /stats/tournament/sessions?difficulty=` | `get_session_history(...)` |

(Managers are cheap file reads — construct per request, no caching. Routes are
static-path, so they must be registered before the `/` static mount like
everything else; note they do NOT collide with `/games/{id}` routes.)

Client screen: difficulty filter (All/Easy/Normal/Hard) + two tabs —
**Players** (table: name, sessions, hands, won, win%, net — mirror the fields
`print_persistent_stats` shows) and **Sessions** (table mirroring
`main.py::_view_persistent_stats` mode 3: id, difficulty, date, hands, mode,
player count). Clicking a player row loads their history detail. Reuse the
stats-modal table CSS.

### M1 acceptance

- [ ] Fresh load with no live game → menu; with a live game → table directly.
- [ ] Play a short web game, Quit → it appears in the Tournament-stats screen
      AND in the TUI viewer (`python main.py` → mode 3).
- [ ] Game-over (not quit) also persists exactly once.
- [ ] All existing tests + new persistence tests green; TUI untouched except
      nothing (main.py unchanged this phase).

---

## 3. Phase M2 — Simulation stats viewer

- `SimulationStatsManager` has no getters: add ONE small method
  `get_data(self) -> dict` returning `self.data` (the loaded JSON) — do not
  restructure the file format. Endpoint: `GET /stats/simulation` → that dict.
- Client screen (menu entry goes live): render the sessions list (read
  `save_all_vs_all/save_h2h/save_param_sweep` in `core/simulation_stats.py`
  FIRST to learn the exact stored fields) and the all-time buckets. Follow the
  presentation intent of `print_stats`/`_print_session_history` /
  `_print_alltime_*` — tables, win% coloring via the existing `.pos`/`.neg`
  classes. Unknown/legacy entries: render raw key/values rather than crashing.
- Acceptance: run one TUI benchmark (`python main.py` → mode 2, small: 5
  tables × 50 hands), then see it listed in the browser viewer. Empty-file
  state shows "no simulations yet", not an error.

---

## 4. Phase M3 — Extract benchmark runners (pure refactor, TUI output unchanged)

The risky phase; behavior-preserving only. New module `core/benchmark.py`:

```python
def run_all_vs_all(num_tables, hands_per_table, starting_chips, big_blind,
                   difficulty, ante=False, short_deck=False,
                   progress=None, should_stop=None) -> dict
    # → {'ranked', 'per_table_nets', 'convergence_snapshots',
    #    'street_totals', 'street_hands', 'elapsed'}

def run_h2h(num_tables, hands_per_table, starting_chips, big_blind,
            difficulty, progress=None, should_stop=None) -> dict
    # → {'strat_names', 'wins', 'net_matrix', 'elapsed'}

def run_param_sweep(param_name, steps, base_profile, num_tables,
                    hands_per_table, starting_chips, big_blind, difficulty,
                    progress=None, should_stop=None) -> dict
    # → {'results': [(value, avg_net, sd)], 'elapsed'}
```

- Move the loop bodies from `main.py` **verbatim** (table loop incl. rebuy
  handling, street-investment accounting, convergence snapshots; pair loop;
  sweep loop). `_BENCHMARK_STRATEGIES` and its imports move to
  `core/benchmark.py`; `main.py` imports them back from there (the TUI's
  `_STRATEGY_NOTES` and all printers stay in `main.py`).
- `progress(done, total)` optional callback replaces the inline `\r` prints —
  `main.py` passes a lambda reproducing its current progress line exactly.
- `should_stop()` optional callback checked once per table/matchup/step; when
  it returns True, return partial results with `'stopped': True` (M4 uses this
  for cancellation; TUI passes None).
- `main.py`'s three `_run_*` functions become: prompts → call runner →
  existing `_print_*` + `SimulationStatsManager.save_*` calls, unchanged.
- New `tests/test_benchmark.py`: tiny runs (2 tables × 20 hands) assert result
  dict shapes, all 8 strategies present, per_table_nets lengths == num_tables,
  progress callback called with final (total, total), should_stop honored.
- Acceptance: `pytest` green; run TUI mode 2 option 1 with small params
  before/after the refactor — output format identical (numbers may differ,
  the sims are stochastic).

---

## 5. Phase M4 — Simulation jobs API + browser UI

### M4.1 Job model (server)

Single-slot, in-memory (mirrors the single-user design; the sim thread will
compete with game handling for the GIL — acceptable, note it in the UI as
"table may lag during simulation"):

```python
# api/simulations.py
job = {"id", "type": "all_vs_all"|"h2h"|"param_sweep", "params": {...},
       "status": "running"|"done"|"cancelled"|"error",
       "done": int, "total": int, "started": ts, "elapsed": float,
       "result": dict | None, "error": str | None}
```

| route | behavior |
|---|---|
| `POST /simulations` | body: type + params (Pydantic-validate; difficulty is one of 0.4/0.6/0.75/0.9 or labels easy/normal/hard/expert; clamp web limits: tables ≤ 200, hands ≤ 1000 — a browser user should not queue an hour-long job). `409 {"reason": "busy"}` if a job is running. Starts a `threading.Thread` running the M3 runner with `progress` writing into the job dict and `should_stop` reading a cancel flag. On completion, call the matching `SimulationStatsManager.save_*` so results land in the same history the TUI reads. |
| `GET /simulations/current` | the job dict minus `result` (or `404` if none ever ran) — the client polls this ~1s while running |
| `GET /simulations/current/result` | full result once `status == "done"` |
| `POST /simulations/current/cancel` | sets the cancel flag → job ends `"cancelled"` with partial result |

Serialize result to JSON-safe form in the endpoint (tuples → lists).

### M4.2 Client simulation screen

Menu's Simulation entry goes live: type picker (3 modes) → params form with
the same defaults as the TUI prompts (`main.py` `_run_*` prompt defaults) →
Run → progress bar (`done/total`, elapsed, Cancel button) → results rendered
per type, following the TUI printers as the presentation spec:

- **All-vs-all** (`_print_benchmark_results`): leaderboard table — rank, name,
  avg net, ±95% CI (`1.96*sd/√n`), std dev, win%, rebuys, tables won; the
  1st-vs-2nd z-score significance line; a horizontal CSS bar chart of avg net
  (green/red divs, width ∝ |value|); convergence check lines if present.
- **H2H** (`_print_h2h_matrix`): the win-rate matrix as a table, cells colored
  `.pos` ≥60% / `.neg` ≤40%, plus the dominance ranking list.
- **Sweep** (`_print_parameter_sweep`): value/avg-net/CI table + CSS bars,
  optimal value highlighted.

Compute the derived stats (CI, z, verdicts) client-side from the raw result —
copy the exact formulas from the printers; do NOT modify the printers.

Guard rails: navigating to the table while a sim runs is allowed; the
simulation screen restores its polling state on return (job is server-side).
Refresh during a run → menu → Simulation shows the running job (poll
`/simulations/current` on screen entry).

### M4 acceptance

- [ ] Run a 10×100 all-vs-all from the browser: live progress, cancel works
      (partial result labelled cancelled), completed run appears in BOTH the
      M2 simulation-stats viewer and the TUI viewer (mode 4).
- [ ] Second `POST /simulations` while running → 409 busy.
- [ ] A tournament hand remains playable during a running sim (may lag).
- [ ] `pytest` green incl. new endpoint tests (run a tiny 2×20 job to
      completion in-test via polling loop with timeout).

---

## 6. Kickoff prompts

> **M1:** Read `notes/browser_full_menu.md` fully. Implement Phase M1 only
> (§2), meeting its acceptance list. Do not start M2–M4. Commit:
> `api+web: landing menu, tournament stats viewer, session persistence, quit`.

> **M2:** Read `notes/browser_full_menu.md`. M1 is done. Implement Phase M2
> only (§3). Read `core/simulation_stats.py` before writing any code. Commit:
> `api+web: simulation stats viewer`.

> **M3:** Read `notes/browser_full_menu.md`. Implement Phase M3 only (§4) — a
> behavior-preserving extraction; TUI output format must be unchanged. Commit:
> `core: extract benchmark runners from main.py`.

> **M4:** Read `notes/browser_full_menu.md`. M1–M3 are done. Implement Phase
> M4 (§5). Commit: `api+web: simulation jobs + browser benchmark UI`.
