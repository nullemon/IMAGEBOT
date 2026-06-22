#!/usr/bin/env python3
"""Launch the IMAGEBOT web app.

    python run.py            # opens http://127.0.0.1:8777
    python run.py --port 9001
    python run.py --host 0.0.0.0   # reach it from another device / Windows via the box IP

For command-line (no browser) use:  python -m imagebot make --help
"""
from __future__ import annotations

import argparse
import socket
import webbrowser

from imagebot.config import get_settings
from imagebot.web import create_app


def _pick_port(host: str, port: int, tries: int = 30) -> int:
    """Return `port` if free, else the next free port — so a taken port never blocks."""
    probe = "127.0.0.1" if host in ("", "0.0.0.0") else host
    for p in range(port, port + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((probe, p))
                return p
            except OSError:
                continue
    return port


def main() -> None:
    settings = get_settings()
    ap = argparse.ArgumentParser(description="IMAGEBOT web UI")
    ap.add_argument("--host", default=settings.host)
    ap.add_argument("--port", type=int, default=settings.port)
    ap.add_argument("--no-browser", action="store_true", help="don't auto-open the browser")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    port = _pick_port(args.host, args.port)
    url = f"http://{args.host if args.host != '0.0.0.0' else '127.0.0.1'}:{port}"
    provs = settings.available_text_providers()
    if port != args.port:
        print(f"\n  (port {args.port} was busy — using {port})")
    print(f"\n  IMAGEBOT  →  {url}")
    print(f"  AI text provider : {settings.resolve_text_provider()}"
          + (f"   (available: {', '.join(provs)})" if provs else "   (no keys — rule-based parser)"))
    print(f"  Output folder    : {settings.output_dir}/\n")

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    app = create_app(settings)
    app.run(host=args.host, port=port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
