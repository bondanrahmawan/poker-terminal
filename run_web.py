"""Launch the browser poker client: start the API server, open a Cloudflare quick
tunnel, and open the public tunnel URL in a browser tab.

    python run_web.py                 # tunnel + open the trycloudflare.com URL
    POKER_NO_TUNNEL=1 python run_web.py   # local only, open http://127.0.0.1:PORT
    POKER_PORT=8137 python run_web.py     # pin the local port

This is the all-in-one path: the tunnel and backend share one process, so the
public URL changes whenever you restart. To keep a stable URL across backend
restarts, run run_tunnel.py and run_backend.py instead (two terminals).

Run from anywhere — the script chdir's to its own directory first because
api/server.py mounts StaticFiles(directory="web") with a relative path.
"""
import os

# Must happen before importing api.server: create_app() checks that "web" exists
# relative to the CWD at import time.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import shutil
import threading
import time
import webbrowser

import uvicorn

from api.server import app
import web_launcher
from web_launcher import HOST

web_launcher.configure_console()


def main() -> None:
    # All-in-one launcher keeps its historical random-port default; only the
    # pinned tunnel/backend launchers default to web_launcher.DEFAULT_PORT.
    port = int(os.environ.get("POKER_PORT") or web_launcher.free_port())
    use_tunnel = os.environ.get("POKER_NO_TUNNEL") not in ("1", "true", "True")
    if use_tunnel and shutil.which("cloudflared") is None:
        print("cloudflared not found on PATH — falling back to local-only mode.")
        use_tunnel = False

    print(f"Poker Terminal (local) -> http://{HOST}:{port}/   (Ctrl+C to stop)")
    if use_tunnel:
        print("!  The tunnel URL is PUBLIC - anyone who has the link can open "
              "your table. Share it only with people you want playing.")

    # uvicorn.run blocks, so run it in a daemon thread and keep the main thread
    # free to drive the tunnel + Ctrl+C.
    threading.Thread(
        target=lambda: uvicorn.run(app, host=HOST, port=port, log_level="warning"),
        daemon=True,
    ).start()

    if not web_launcher.wait_until_ready(port):
        print("Server did not come up in time; exiting.")
        return

    try:
        if use_tunnel:
            print("Opening Cloudflare tunnel (this can take a few seconds)...")
            web_launcher.run_tunnel(port)
        else:
            webbrowser.open(f"http://{HOST}:{port}/", new=2)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        web_launcher.request_shutdown()


if __name__ == "__main__":
    main()
