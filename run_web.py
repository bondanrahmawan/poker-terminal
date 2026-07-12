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
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from api.server import app

# cloudflared's banner and our status lines contain non-ASCII; the default
# Windows console is cp1252 and would crash on them. Fail soft instead.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

HOST = "127.0.0.1"
_TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

_shutdown = threading.Event()
_current_proc = None  # the live cloudflared subprocess, for clean teardown


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


def _open_when_reachable(url: str, timeout: float = 30) -> None:
    """Poll the public URL until Cloudflare's edge actually serves it (quick
    tunnels print the URL before it's routable, so opening immediately can 502),
    then open the browser."""
    print(f"\nPoker Terminal (public) -> {url}")
    deadline = time.time() + timeout
    while time.time() < deadline and not _shutdown.is_set():
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status < 500:
                    break
        except urllib.error.HTTPError as e:
            if e.code < 500:  # a 4xx means the edge is routing to our app
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not _shutdown.is_set():
        webbrowser.open(url, new=2)


def _run_tunnel(port: int) -> None:
    """Run cloudflared, streaming its logs, and restart it if it drops (quick
    tunnels are flaky). Opens the browser once, when the first URL is reachable."""
    global _current_proc
    opened = False
    while not _shutdown.is_set():
        _current_proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://{HOST}:{port}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        url = None
        for line in _current_proc.stdout:
            print(line, end="")
            if url is None:
                m = _TUNNEL_URL_RE.search(line)
                if m:
                    url = m.group(0)
                    if not opened:
                        opened = True
                        threading.Thread(target=_open_when_reachable,
                                         args=(url,), daemon=True).start()
                    else:
                        print(f"\nTunnel reconnected -> {url}\n")
        _current_proc.wait()
        if _shutdown.is_set():
            return
        print("\nCloudflare tunnel dropped - restarting in 2s "
              "(the public URL will change)...\n")
        time.sleep(2)


def main() -> None:
    port = int(os.environ.get("POKER_PORT") or _free_port())
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

    if not _wait_until_ready(port):
        print("Server did not come up in time; exiting.")
        return

    try:
        if use_tunnel:
            print("Opening Cloudflare tunnel (this can take a few seconds)...")
            _run_tunnel(port)
        else:
            webbrowser.open(f"http://{HOST}:{port}/", new=2)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown.set()
        if _current_proc is not None and _current_proc.poll() is None:
            _current_proc.terminate()


if __name__ == "__main__":
    main()
