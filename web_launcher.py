"""Shared launch helpers for the browser poker client.

Two ways to run the client use these helpers:

  run_web.py                 all-in-one: backend + tunnel in one process. Simple,
                             but the public URL changes every time you restart.

  run_tunnel.py + run_backend.py
                             the tunnel and the backend run as separate processes
                             pinned to a fixed port (DEFAULT_PORT / POKER_PORT).
                             Start the tunnel once and leave it: its
                             trycloudflare.com URL stays the same while you restart
                             the backend as often as you like — the tunnel just
                             502s for the second the backend is down, then serves
                             the fresh one on the same URL.
"""
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

HOST = "127.0.0.1"
# A fixed default port is what lets the tunnel and the backend agree without
# setting POKER_PORT every time, and it's the whole reason the backend can
# restart under a stable public URL. Override with POKER_PORT.
DEFAULT_PORT = 8137
_TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

_shutdown = threading.Event()
_current_proc = None  # the live cloudflared subprocess, for clean teardown


def configure_console() -> None:
    """cloudflared's banner and our status lines contain non-ASCII; the default
    Windows console is cp1252 and would crash on them. Fail soft instead."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def resolve_port() -> int:
    """POKER_PORT if set, otherwise the fixed default. Used by the pinned
    tunnel/backend launchers so they land on the same port."""
    return int(os.environ.get("POKER_PORT") or DEFAULT_PORT)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, port)) == 0


def wait_until_ready(port: int, timeout: float = 15) -> bool:
    """Block until the local server accepts connections (or timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((HOST, port)) == 0:
                return True
        time.sleep(0.2)
    return False


def open_when_reachable(url: str, timeout: float = 30) -> None:
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


def run_tunnel(port: int, open_timeout: float = 30) -> None:
    """Run cloudflared, streaming its logs, and restart it if it drops (quick
    tunnels are flaky). Opens the browser once, when the first URL is reachable.

    Note: if cloudflared itself dies and is respawned, the public URL changes —
    that's inherent to quick tunnels. Restarting only the *backend* keeps the
    URL, because this process (and its cloudflared) stays up."""
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
                        threading.Thread(target=open_when_reachable,
                                         args=(url, open_timeout), daemon=True).start()
                    else:
                        print(f"\nTunnel reconnected -> {url}\n")
        _current_proc.wait()
        if _shutdown.is_set():
            return
        print("\nCloudflare tunnel dropped - restarting in 2s "
              "(the public URL will change)...\n")
        time.sleep(2)


def request_shutdown() -> None:
    """Signal helper threads to stop and tear down cloudflared cleanly."""
    _shutdown.set()
    if _current_proc is not None and _current_proc.poll() is None:
        _current_proc.terminate()
