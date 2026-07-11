"""Launch the browser poker client: start the API server and open a browser tab.

    python run_web.py              # auto-pick a free port, open the browser
    POKER_PORT=8137 python run_web.py   # pin a port

Run from anywhere — the script chdir's to its own directory first because
api/server.py mounts StaticFiles(directory="web") with a relative path.
"""
import os

# Must happen before importing api.server: create_app() checks that "web" exists
# relative to the CWD at import time.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import socket
import threading
import time
import webbrowser

import uvicorn

from api.server import app

HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _open_when_ready(port: int) -> None:
    """Poll the port and open the browser once the server accepts connections."""
    deadline = time.time() + 15
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) == 0:
                webbrowser.open(f"http://{HOST}:{port}/", new=2)
                return
        time.sleep(0.2)


def main() -> None:
    port = int(os.environ.get("POKER_PORT") or _free_port())
    print(f"Poker Terminal -> http://{HOST}:{port}/   (Ctrl+C to stop)")
    threading.Thread(target=_open_when_ready, args=(port,), daemon=True).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
