"""Single-slot, in-memory simulation job runner.

One benchmark job runs at a time on a daemon thread. The game sessions are
untouched, so a tournament hand stays playable while a sim runs — the sim thread
only competes for the GIL (the UI warns the table may lag). ``progress(done,
total)`` writes into the shared job dict the client polls; ``should_stop()``
reads a cancel flag. On successful completion the result is saved into the same
history the TUI reads via SimulationStatsManager.
"""
import threading
import time
import uuid

from core import benchmark
from core.simulation_stats import SimulationStatsManager

# Step ranges + base profile mirror main.py::_run_parameter_sweep.
_SWEEP_BASE = dict(play_range=0.5, aggression=0.5, bluff_freq=0.25, call_freq=0.5)
_SWEEP_STEPS = {
    "aggression": [round(0.1 * i, 1) for i in range(1, 11)],
    "play_range": [round(0.1 * i, 1) for i in range(1, 11)],
    "bluff_freq": [round(0.1 * i, 1) for i in range(0, 9)],
}


class BusyError(Exception):
    """A simulation job is already running."""


def sweep_steps(param_name: str) -> list:
    return _SWEEP_STEPS[param_name]


def _json_safe(obj):
    """Recursively convert tuples to lists so the result serializes as arrays."""
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    return obj


class SimulationManager:
    """Holds the current (or most recent) job. At most one runs at a time."""

    def __init__(self):
        self._lock = threading.Lock()
        self._job = None       # last/current job dict, or None if none ever ran
        self._cancel = False

    @property
    def job(self):
        return self._job

    def start(self, sim_type: str, params: dict) -> dict:
        with self._lock:
            if self._job is not None and self._job["status"] == "running":
                raise BusyError()
            self._cancel = False
            job = {
                "id":      uuid.uuid4().hex,
                "type":    sim_type,
                "params":  params,
                "status":  "running",
                "done":    0,
                "total":   0,
                "started": time.time(),
                "elapsed": 0.0,
                "result":  None,
                "error":   None,
            }
            self._job = job
        threading.Thread(target=self._run, args=(job, sim_type, params),
                         daemon=True).start()
        return job

    def cancel(self) -> bool:
        """Signal the running job to stop. Returns False if nothing is running."""
        with self._lock:
            if self._job is None or self._job["status"] != "running":
                return False
            self._cancel = True
            return True

    def public_view(self, job: dict) -> dict:
        """Job dict minus ``result``; elapsed computed live while running."""
        elapsed = (time.time() - job["started"]) if job["status"] == "running" else job["elapsed"]
        return {
            "id":      job["id"],
            "type":    job["type"],
            "params":  job["params"],
            "status":  job["status"],
            "done":    job["done"],
            "total":   job["total"],
            "started": job["started"],
            "elapsed": round(elapsed, 1),
            "error":   job["error"],
        }

    # ── worker ────────────────────────────────────────────────────────────────

    def _run(self, job, sim_type, params):
        def progress(done, total):
            job["done"] = done
            job["total"] = total

        def should_stop():
            return self._cancel

        try:
            if sim_type == "all_vs_all":
                r = benchmark.run_all_vs_all(
                    params["num_tables"], params["hands_per_table"],
                    params["starting_chips"], params["big_blind"], params["difficulty"],
                    params["ante"], params["short_deck"],
                    progress=progress, should_stop=should_stop)
            elif sim_type == "h2h":
                r = benchmark.run_h2h(
                    params["num_tables"], params["hands_per_table"],
                    params["starting_chips"], params["big_blind"], params["difficulty"],
                    progress=progress, should_stop=should_stop)
            else:  # param_sweep
                r = benchmark.run_param_sweep(
                    params["param_name"], params["steps"], _SWEEP_BASE,
                    params["num_tables"], params["hands_per_table"],
                    params["starting_chips"], params["big_blind"], params["difficulty"],
                    progress=progress, should_stop=should_stop)

            stopped = r.get("stopped", False)
            job["elapsed"] = round(r["elapsed"], 1)
            job["result"] = _json_safe(r)

            # Persist BEFORE flipping status off "running" so a second POST that
            # arrives mid-save still sees the slot as busy (409) — otherwise two
            # jobs could race on the stats file.
            if not stopped:
                self._save(sim_type, params, r)
            job["status"] = "cancelled" if stopped else "done"
        except Exception as e:                       # noqa: BLE001 — surface any failure to the client
            job["status"] = "error"
            job["error"] = str(e)

    def _save(self, sim_type, params, r):
        m = SimulationStatsManager()
        if sim_type == "all_vs_all":
            m.save_all_vs_all(
                params["num_tables"], params["hands_per_table"],
                params["starting_chips"], params["big_blind"], params["difficulty"],
                params["ante"], params["short_deck"], r["ranked"], r["per_table_nets"])
        elif sim_type == "h2h":
            m.save_h2h(
                params["num_tables"], params["hands_per_table"],
                params["starting_chips"], params["big_blind"], params["difficulty"],
                r["strat_names"], r["wins"], r["net_matrix"])
        else:
            m.save_param_sweep(
                params["num_tables"], params["hands_per_table"],
                params["starting_chips"], params["big_blind"], params["difficulty"],
                params["param_name"], r["results"])
