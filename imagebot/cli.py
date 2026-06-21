"""Command-line interface:  python -m imagebot <command>

    python -m imagebot make --news "Bleach S4 new info July 4"
    python -m imagebot make --file news.txt --per 4 --no-art
    python -m imagebot web --port 8080
"""
from __future__ import annotations

import argparse
import sys

from .config import get_settings
from .pipeline import GenerateOptions, make_variants, build_carousel


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

    styles = None if args.all_styles else [args.style]
    opts = GenerateOptions(
        provider=args.provider,
        panels_per_card=args.per,
        event_name=args.event,
        watermark=args.watermark,
        date_text=args.date,
        find_art=not args.no_art,
        vision_pick=not args.no_vision,
        clean_art=args.clean,
        ai_fallback=args.ai_art,
        find_logo=args.find_logo,
        write_caption=not args.no_caption,
        cover_title=args.cover_title,
        styles=styles,
    )
    res = make_variants(settings, opts, news=news, progress=lambda m: print("  ·", m))
    print("\nProvider:", res.provider_used, "| run:", res.runid)
    for p in res.panels:
        print(f"  • {p.title} — {p.tag_main}" + (f" ({p.date_text})" if p.date_text else ""))
    for w in res.warnings:
        print("  ⚠", w)
    print("\nStyles rendered:")
    for v in res.variants:
        print(f"  → {v['name']:16} {v['cards'][0]}")
    if args.carousel and res.variants:
        key = (styles or [res.variants[0]["key"]])[0]
        car = build_carousel(res.panels, settings, opts, key, res.runid, with_cover=True)
        print("\nCarousel zip:", car["zip"])
    if res.caption:
        print("\nCaption:\n" + res.caption)
    return 0


def _cmd_news(args) -> int:
    settings = get_settings()
    if args.file:
        news = open(args.file, "r", encoding="utf-8").read()
    elif args.news:
        news = args.news
    else:
        news = sys.stdin.read()
    if not news.strip():
        print("No news provided (use --news, --file, or stdin).", file=sys.stderr)
        return 2
    from .pipeline import make_news_post, render_news_one
    from .newscard import NEWS_TEMPLATES
    opts = GenerateOptions(
        provider=args.provider, event_name=args.event, watermark=args.watermark,
        date_text=args.date, find_art=not args.no_art, vision_pick=not args.no_vision,
        clean_art=args.clean, ai_fallback=args.ai_art, write_caption=not args.no_caption,
    )
    res = make_news_post(news, settings, opts, template_key=args.template,
                         progress=lambda m: print("  ·", m))
    print("\nHeadline:", res.post.headline)
    print("Category:", res.post.category, "| date:", res.post.date_text or "—", "| run:", res.runid)
    for w in res.warnings:
        print("  ⚠", w)
    if res.current:
        print("Post:", res.current["outputs"][0]["cards"][0])
    if args.all_templates:
        print("\nAll templates:")
        for k, n, _ in NEWS_TEMPLATES:
            outs = render_news_one(res.post, settings, opts, k, res.runid)
            print(f"  → {n:16} {outs[0]['cards'][0]}")
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
    m.add_argument("--style", default="classic", help="style key (see --all-styles)")
    m.add_argument("--all-styles", action="store_true", help="render every style variant")
    m.add_argument("--cover-title", default="LINE-UP", help="carousel cover title")
    m.add_argument("--carousel", action="store_true", help="also build a carousel .zip (with cover)")
    m.add_argument("--no-art", action="store_true", help="skip image search (gradients only)")
    m.add_argument("--no-vision", action="store_true", help="don't use AI to pick the best image")
    m.add_argument("--clean", action="store_true", help="OCR + inpaint to remove watermarks (GPU)")
    m.add_argument("--find-logo", action="store_true", help="auto search+download transparent logos")
    m.add_argument("--ai-art", action="store_true", help="AI-generate art when none found")
    m.add_argument("--no-caption", action="store_true", help="don't write a caption")
    m.set_defaults(func=_cmd_make)

    nw = sub.add_parser("news", help="make a single-story news post")
    nw.add_argument("--news", help="the news story")
    nw.add_argument("--file", help="read the story from a file")
    nw.add_argument("--provider", choices=["claude", "openai", "gemini", "grok", "auto", "none"], default=None)
    nw.add_argument("--template", default="bottom", help="news template key (default: bottom)")
    nw.add_argument("--all-templates", action="store_true", help="render every news template")
    nw.add_argument("--event", default=None)
    nw.add_argument("--watermark", default=None)
    nw.add_argument("--date", default=None)
    nw.add_argument("--no-art", action="store_true")
    nw.add_argument("--no-vision", action="store_true")
    nw.add_argument("--clean", action="store_true")
    nw.add_argument("--ai-art", action="store_true")
    nw.add_argument("--no-caption", action="store_true")
    nw.set_defaults(func=_cmd_news)

    w = sub.add_parser("web", help="launch the web UI")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=5000)
    w.set_defaults(func=_cmd_web)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
