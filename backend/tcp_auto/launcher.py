"""Desktop launcher: starts FlagPole on this computer and opens it in the browser.

Used by the packaged app (PyInstaller) and by ``python -m tcp_auto``.

    flagpole                       # start and open the browser
    flagpole --port 9000 --no-browser
    flagpole --host 0.0.0.0        # share on the local network (set an access key!)
    flagpole --data-dir D:\\FlagPoleData
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = "FlagPole"


def default_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "flagpole"


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        if _port_free(host, port):
            return port
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _open_when_ready(url: str, host: str, port: int) -> None:
    probe = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    for _ in range(100):
        try:
            with socket.create_connection((probe, port), timeout=0.3):
                break
        except OSError:
            time.sleep(0.15)
    webbrowser.open(url)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="flagpole", description="FlagPole: traffic control plans from pole sheets.")
    ap.add_argument("--host", default=os.environ.get("TCP_HOST", "127.0.0.1"), help="address to listen on (default: this computer only)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("TCP_PORT", "8765")))
    ap.add_argument("--data-dir", default=os.environ.get("TCP_DATA_DIR"), help=f"where projects and rules are saved (default: {default_data_dir()})")
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args(argv)

    from . import __version__

    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0

    data_dir = Path(args.data_dir or default_data_dir()).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TCP_DATA_DIR"] = str(data_dir)  # must be set before the app module is imported

    port = pick_port(args.host, args.port)
    shown_host = "localhost" if args.host in ("127.0.0.1", "0.0.0.0", "::") else args.host
    url = f"http://{shown_host}:{port}/"
    key = os.environ.get("TCP_ACCESS_KEY")
    if key:
        url += f"?key={key}"

    import uvicorn

    from .api.app import app
    from .report.pdf import find_browser

    print(f"\n  {APP_NAME} {__version__}", flush=True)
    print(f"  Open:  {url}")
    print(f"  Data:  {data_dir}")
    print(f"  PDF:   {find_browser() or 'no Chrome/Edge found (use Preview > Print > Save as PDF)'}")
    if args.host not in ("127.0.0.1", "localhost") and not key:
        print("  Warning: listening on the network without TCP_ACCESS_KEY; anyone on the network can open it.")
    print("  Close this window (or press Ctrl+C) to stop.\n", flush=True)

    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(url, args.host, port), daemon=True).start()
    try:
        uvicorn.run(app, host=args.host, port=port, log_level="warning")
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
