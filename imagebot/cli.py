"""Command-line interface:  python -m imagebot <command>

    python -m imagebot make --news "Bleach S4 new info July 4"
    python -m imagebot make --file news.txt --per 4 --no-art
    python -m imagebot web --port 8080
"""
from __future__ import annotations

import argparse
import sys

from .config import get_settings
from .pipeline import GenerateOptions, generate_from_news


def _cmd_make(args) -> int:
    settings = get_settings()
    if args.file:
        news = open(args.file, "r", encoding="utf-8").read()
    elif args.news:
        news = args.news
    else:
        news = sys.stdin.read()
    if not news.strip():
        print("No news provided (use --news, --file, or pipe via stdin).", file=sys.stderr)
        return 2

    opts = GenerateOptions(
        provider=args.provider,
        panels_per_card=args.per,
        event_name=args.event,
        watermark=args.watermark,
        date_text=args.date,
        find_art=not args.no_art,
        ai_fallback=args.ai_art,
        write_caption=not args.no_caption,
        prefix=args.prefix,
    )
    res = generate_from_news(news, settings, opts, progress=lambda m: print("  ·", m))
    print("\nProvider:", res.provider_used)
    for p in res.panels:
        print(f"  • {p.title} — {p.tag_main}" + (f" ({p.date_text})" if p.date_text else ""))
    for w in res.warnings:
        print("  ⚠", w)
    print("\nCards:")
    for c in res.card_paths:
        print("  →", c)
    if res.caption:
        print("\nCaption:\n" + res.caption)
    return 0


def _cmd_web(args) -> int:
    from .web import create_app
    settings = get_settings()
    app = create_app(settings)
    print(f"IMAGEBOT web → http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="imagebot", description="Anime news card maker")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("make", help="generate cards from news text")
    m.add_argument("--news", help="news text")
    m.add_argument("--file", help="read news from a file")
    m.add_argument("--provider", choices=["claude", "openai", "gemini", "grok", "auto", "none"],
                   default=None, help="AI text provider (default: auto)")
    m.add_argument("--per", type=int, default=4, help="series per card image")
    m.add_argument("--event", default=None, help="event wordmark, e.g. 'ANIME EXPO'")
    m.add_argument("--watermark", default=None, help="center watermark text")
    m.add_argument("--date", default=None, help="apply this date to all panels")
    m.add_argument("--prefix", default="card", help="output filename prefix")
    m.add_argument("--no-art", action="store_true", help="skip image search (gradients only)")
    m.add_argument("--ai-art", action="store_true", help="AI-generate art when none found")
    m.add_argument("--no-caption", action="store_true", help="don't write a caption")
    m.set_defaults(func=_cmd_make)

    w = sub.add_parser("web", help="launch the web UI")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=5000)
    w.set_defaults(func=_cmd_web)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
