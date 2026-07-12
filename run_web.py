"""Launch the browser poker client: start the API server, open a Cloudflare quick
tunnel, and open the public tunnel URL in a browser tab.

    python run_web.py                 # tunnel + open the trycloudflare.com URL
    POKER_NO_TUNNEL=1 python run_web.py   # local only, open http://127.0.0.1:PORT
    POKER_PORT=8137 python run_web.py     # pin the local port

Run from anywhere — the script chdir's to its own directory first because
api/server.py mounts StaticFiles(directory="web") with a relative path.
"""
import os

# Must happen before importing api.server: create_app() checks that "web" exists
# relative to the CWD at import time.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import re
import shutil
import socket
import subprocess
import threading
import time
import webbrowser

import uvicorn

from api.server import app

HOST = "127.0.0.1"
_TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def _wait_until_ready(port: int, timeout: float = 15) -> bool:
    """Block until the local server accepts connections (or timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) == 0:
                return True
        time.sleep(0.2)
    return False


def _start_tunnel(port: int) -> subprocess.Popen:
    """Spawn `cloudflared` for a quick tunnel to the local port, streaming output.
    Opens the browser on the public URL the first time it appears in the logs."""
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://{HOST}:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )

    def pump():
        opened = False
        for line in proc.stdout:
            print(line, end="")
            if not opened:
                m = _TUNNEL_URL_RE.search(line)
                if m:
                    opened = True
                    url = m.group(0)
                    print(f"\nPoker Terminal (public) -> {url}\n")
                    webbrowser.open(url, new=2)

    threading.Thread(target=pump, daemon=True).start()
    return proc


def main() -> None:
    port = int(os.environ.get("POKER_PORT") or _free_port())
    use_tunnel = os.environ.get("POKER_NO_TUNNEL") not in ("1", "true", "True")
    if use_tunnel and shutil.which("cloudflared") is None:
        print("cloudflared not found on PATH — falling back to local-only mode.")
        use_tunnel = False

    print(f"Poker Terminal (local) -> http://{HOST}:{port}/   (Ctrl+C to stop)")

    # uvicorn.run blocks, so run it in a daemon thread and keep the main thread
    # free to drive the tunnel + Ctrl+C.
    threading.Thread(
        target=lambda: uvicorn.run(app, host=HOST, port=port, log_level="warning"),
        daemon=True,
    ).start()

    if not _wait_until_ready(port):
        print("Server did not come up in time; exiting.")
        return

    tunnel = None
    if use_tunnel:
        print("Opening Cloudflare tunnel (this can take a few seconds)...")
        tunnel = _start_tunnel(port)
    else:
        webbrowser.open(f"http://{HOST}:{port}/", new=2)

    try:
        if tunnel is not None:
            tunnel.wait()
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if tunnel is not None and tunnel.poll() is None:
            tunnel.terminate()


if __name__ == "__main__":
    main()
