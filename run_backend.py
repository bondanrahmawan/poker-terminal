"""Run only the poker API backend, on the pinned port, so it can be restarted
under a stable Cloudflare tunnel (see run_tunnel.py).

    python run_backend.py
    POKER_PORT=9000 python run_backend.py   # must match run_tunnel.py

Ctrl+C to stop; just relaunch to restart. The tunnel in the other terminal keeps
the same public URL across restarts. Note: restarting wipes all in-memory game
sessions — anyone mid-hand on the tunnel URL gets reset.

Run from anywhere — the script chdir's to its own directory first because
api/server.py mounts StaticFiles(directory="web") with a relative path.
"""
import os
import sys

# Must happen before importing api.server: create_app() checks that "web" exists
# relative to the CWD at import time.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import uvicorn

from api.server import app
import web_launcher
from web_launcher import HOST, resolve_port

web_launcher.configure_console()


def main() -> None:
    port = resolve_port()
    if web_launcher.port_in_use(port):
        print(f"Port {port} is already in use — is a previous backend still "
              f"running? Stop it first (or set POKER_PORT to a free port). Exiting.")
        sys.exit(1)

    print(f"Poker Terminal backend -> http://{HOST}:{port}/   "
          f"(Ctrl+C to stop, relaunch to restart; tunnel URL is unaffected)")
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
