#!/usr/bin/env python3
"""Launch the IMAGEBOT web app.

    python run.py            # open http://127.0.0.1:5000
    python run.py --port 8080

For command-line (no browser) use:  python -m imagebot make --help
"""
from __future__ import annotations

import argparse
import webbrowser

from imagebot.config import get_settings
from imagebot.web import create_app


def main() -> None:
    settings = get_settings()
    ap = argparse.ArgumentParser(description="IMAGEBOT web UI")
    ap.add_argument("--host", default=settings.host)
    ap.add_argument("--port", type=int, default=settings.port)
    ap.add_argument("--no-browser", action="store_true", help="don't auto-open the browser")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    app = create_app(settings)
    url = f"http://{args.host}:{args.port}"
    provs = settings.available_text_providers()
    print(f"\n  IMAGEBOT  →  {url}")
    print(f"  AI text provider : {settings.resolve_text_provider()}"
          + (f"   (available: {', '.join(provs)})" if provs else "   (no keys — rule-based parser)"))
    print(f"  Output folder    : {settings.output_dir}/\n")

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
