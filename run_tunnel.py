"""Long-lived Cloudflare tunnel for the poker client, pinned to a fixed port.

Start this ONCE and leave it running. Its trycloudflare.com URL stays the same
for as long as this process lives, so you can restart the backend
(run_backend.py) as often as you like without the public URL changing.

    python run_tunnel.py
    POKER_PORT=9000 python run_tunnel.py   # must match run_backend.py

Then start the backend in another terminal:

    python run_backend.py

Order doesn't matter for URL stability: the tunnel points at a port, and the
backend can come and go behind it. This process opens the browser once, as soon
as the backend behind the tunnel is reachable.
"""
import shutil
import sys

import web_launcher
from web_launcher import HOST, resolve_port

web_launcher.configure_console()


def main() -> None:
    if shutil.which("cloudflared") is None:
        print("cloudflared not found on PATH. Install it, or for local-only play "
              "use: POKER_NO_TUNNEL=1 python run_web.py")
        sys.exit(1)

    port = resolve_port()
    print(f"Cloudflare tunnel -> http://{HOST}:{port}  "
          f"(start the backend with run_backend.py on the same port)")
    print("!  The tunnel URL is PUBLIC - anyone who has the link can open your "
          "table. Share it only with people you want playing.")
    print("Opening Cloudflare tunnel (this can take a few seconds)...")

    try:
        # Generous reachability window so the browser still opens when you start
        # the backend a little after the tunnel.
        web_launcher.run_tunnel(port, open_timeout=300)
    except KeyboardInterrupt:
        pass
    finally:
        web_launcher.request_shutdown()


if __name__ == "__main__":
    main()
