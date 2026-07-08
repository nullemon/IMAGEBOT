"""Flask app: news -> one card -> switch templates instantly -> download.

Supports two modes (line-up lists / single-story news posts) and multi-account
branding: pick up to 4 handles and each render comes out stamped with that
account's @username.
"""
from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path

from flask import (Flask, jsonify, render_template, request,
                   send_from_directory, abort)

from ..config import get_settings, ROOT
from ..image_search import CACHE_DIR
from ..models import Panel, NewsPost, RankingList
from ..pipeline import (GenerateOptions, build_carousel, render_one,
                        prepare_lineup, prepare_news, render_news_one,
                        render_news_from_post, prepare_ranking, render_ranking_one,
                        render_ranking_from_list, prepare_auto, export_all,
                        DEFAULT_RANK, SIZES)
from ..styles import all_styles
from ..newscard import news_templates, NEWS_TEMPLATES, DEFAULT_NEWS
from ..rankcard import rank_templates, RANK_TEMPLATES
from .. import logos

ALLOWED_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_STYLE = all_styles()[0].key


def _resolve_mode(data: dict) -> str:
    """The concrete mode for a request. 'auto' (stale client / race) is resolved
    from whichever content the payload actually carries."""
    mode = data.get("mode") or "lineup"
    if mode == "auto":
        mode = "ranking" if data.get("ranking") else ("news" if data.get("post") else "lineup")
    return mode
NEWS_NAME = {k: n for k, n, _ in NEWS_TEMPLATES}
RANK_NAME = {k: n for k, n in RANK_TEMPLATES}
_STYLE_NAME = {s.key: s.name for s in all_styles()}

# settings field (on the Settings object) -> .env variable name
_KEY_FIELDS = {
    "anthropic_key": "ANTHROPIC_API_KEY",
    "openai_key": "OPENAI_API_KEY",
    "gemini_key": "GEMINI_API_KEY",
    "xai_key": "XAI_API_KEY",
    "serpapi_key": "SERPAPI_KEY",
    "google_api_key": "GOOGLE_API_KEY",
    "google_cse_id": "GOOGLE_CSE_ID",
    "sd_url": "IMAGEBOT_SD_URL",
}


def _update_env_file(path: Path, updates: dict) -> None:
    """Upsert KEY=VALUE lines in .env, preserving everything else."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, seen = [], set()
    for ln in lines:
        m = re.match(r"\s*(?:export\s+)?([A-Za-z0-9_]+)\s*=", ln)
        if m and m.group(1) in updates:
            out.append(f"{m.group(1)}={updates[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(ln)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")


def _bool(v, default=False):
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    return str(v).lower() in ("true", "on", "1", "yes")


def _opts_from(data: dict) -> GenerateOptions:
    prov = data.get("provider")
    w, h = SIZES.get(data.get("size") or "portrait", SIZES["portrait"])
    return GenerateOptions(
        provider=None if prov in (None, "", "auto") else prov,
        width=w, height=h,
        panels_per_card=int(data.get("panels_per_card") or 4),
        watermark=data.get("watermark") if data.get("watermark") is not None else None,
        event_name=data.get("event_name") or None,
        date_text=data.get("date_text") or None,
        find_art=_bool(data.get("find_art"), True),
        vision_pick=_bool(data.get("vision_pick"), True),
        clean_art=_bool(data.get("clean_art"), False),
        ai_fallback=_bool(data.get("ai_fallback"), False),
        find_logo=_bool(data.get("find_logo"), False),
        write_caption=_bool(data.get("write_caption"), True),
        cover_title=data.get("cover_title") or "LINE-UP",
        accounts=data.get("accounts") or [],
    )


def _asset_version() -> str:
    """Newest mtime of the static files — busts the browser cache after a pull."""
    base = Path(__file__).resolve().parent / "static"
    try:
        return str(int(max(p.stat().st_mtime for p in base.glob("*.*"))))
    except Exception:
        return "1"


def create_app(settings=None) -> Flask:
    settings = settings or get_settings()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0       # always revalidate static files

    def file_url(path: str) -> str:
        p = Path(path).resolve()
        for base, d in ((Path(settings.output_dir).resolve(), "output"),
                        (CACHE_DIR.resolve(), "cache")):
            try:
                return f"/file/{p.relative_to(base).as_posix()}?d={d}"
            except ValueError:
                continue
        return ""

    def outputs_urls(outputs):
        return [{"account": o["account"], "cards": [file_url(c) for c in o["cards"]]}
                for o in outputs]

    def with_art(d):
        """Attach a browsable URL for an item's resolved art (for the editor)."""
        ip = d.get("image_path")
        d["art_url"] = file_url(ip) if ip else ""
        return d

    def _caps():
        try:
            from .. import enhance
            return enhance.capabilities()
        except Exception:
            return {}

    def lineup_payload(runid, prep, current_key, outputs, log):
        return {
            "ok": True, "mode": "lineup", "runid": runid,
            "provider_used": prep["provider_used"],
            "panels": [with_art(p.to_dict()) for p in prep["panels"]],
            "styles": [{"key": s.key, "name": s.name} for s in all_styles()],
            "current": {"key": current_key, "name": _STYLE_NAME.get(current_key, current_key),
                        "outputs": outputs_urls(outputs)},
            "caption": prep["caption"], "warnings": prep["warnings"],
            "log": log, "capabilities": _caps(),
        }

    def news_payload(runid, post, current_key, outputs, provider_used, caption, warnings, log):
        return {
            "ok": True, "mode": "news", "runid": runid, "provider_used": provider_used,
            "post": with_art(post.to_dict()), "styles": news_templates(),
            "current": {"key": current_key, "name": NEWS_NAME.get(current_key, current_key),
                        "outputs": outputs_urls(outputs)},
            "caption": caption, "warnings": warnings, "log": log, "capabilities": _caps(),
        }

    def ranking_payload(runid, rl, current_key, outputs, provider_used, caption, warnings, log):
        rd = rl.to_dict()
        rd["entries"] = [with_art(e) for e in rd.get("entries", [])]
        rd["logo_url"] = file_url(rd["logo_path"]) if rd.get("logo_path") else ""
        return {
            "ok": True, "mode": "ranking", "runid": runid, "provider_used": provider_used,
            "ranking": rd, "styles": rank_templates(),
            "current": {"key": current_key, "name": RANK_NAME.get(current_key, current_key),
                        "outputs": outputs_urls(outputs)},
            "caption": caption, "warnings": warnings, "log": log, "capabilities": _caps(),
        }

    # ---- page -----------------------------------------------------------
    @app.get("/")
    def index():
        return render_template(
            "index.html",
            providers=settings.available_text_providers(),
            text_provider=settings.resolve_text_provider(),
            brand=settings.brand,
            themes=sorted((settings.themes or {}).keys()),
            styles=[{"key": s.key, "name": s.name} for s in all_styles()],
            accounts=settings.accounts or [],
            search_keyed=bool(settings.serpapi_key or (settings.google_api_key and settings.google_cse_id)),
            sd=bool(settings.sd_url),
            caps=_caps(),
            asset_v=_asset_version(),
        )

    # ---- generate (parse + art once + render default template) ----------
    @app.post("/generate")
    def generate():
        data = request.get_json(silent=True) or request.form.to_dict()
        news = (data.get("news") or "").strip()
        if not news:
            return jsonify(ok=False, error="Please paste some news text."), 400
        opts = _opts_from(data)
        runid = time.strftime("%Y%m%d-%H%M%S")
        log: list[str] = []
        if data.get("mode") == "auto":
            ap = prepare_auto(settings, opts, news, progress=log.append)
            m, current = ap["mode"], ap["template"]
            if m == "ranking":
                outputs = render_ranking_one(ap["ranking"], settings, opts, current, runid)
                payload = ranking_payload(runid, ap["ranking"], current, outputs,
                                          ap["provider_used"], ap["caption"], ap["warnings"], log)
            elif m == "news":
                outputs = render_news_one(ap["post"], settings, opts, current, runid)
                payload = news_payload(runid, ap["post"], current, outputs,
                                       ap["provider_used"], ap["caption"], ap["warnings"], log)
            else:
                outputs = render_one(ap["panels"], settings, opts, current, runid)
                prep = {"panels": ap["panels"], "warnings": ap["warnings"],
                        "provider_used": ap["provider_used"], "caption": ap["caption"]}
                payload = lineup_payload(runid, prep, current, outputs, log)
            payload["auto"] = ap["why"]
            return jsonify(payload)
        if data.get("mode") == "ranking":
            opts.find_art = _bool(data.get("find_art"), True)
            prep = prepare_ranking(settings, opts, news, progress=log.append)
            if not prep["ranking"].entries:
                return jsonify(ok=False, error="Couldn't read any list entries."), 400
            current = data.get("style") or DEFAULT_RANK
            outputs = render_ranking_one(prep["ranking"], settings, opts, current, runid)
            return jsonify(ranking_payload(runid, prep["ranking"], current, outputs,
                                           prep["provider_used"], prep["caption"], prep["warnings"], log))
        if data.get("mode") == "news":
            prep = prepare_news(settings, opts, news, progress=log.append)
            if not prep["post"].headline:
                return jsonify(ok=False, error="Couldn't read a headline."), 400
            current = data.get("style") or DEFAULT_NEWS
            outputs = render_news_one(prep["post"], settings, opts, current, runid)
            return jsonify(news_payload(runid, prep["post"], current, outputs,
                                        prep["provider_used"], prep["caption"], prep["warnings"], log))
        prep = prepare_lineup(settings, opts, news=news, progress=log.append)
        if not prep["panels"]:
            return jsonify(ok=False, error="No panels could be parsed."), 400
        current = data.get("style") or DEFAULT_STYLE
        outputs = render_one(prep["panels"], settings, opts, current, runid)
        return jsonify(lineup_payload(runid, prep, current, outputs, log))

    # ---- re-render current template with edits (+ re-find art) ----------
    @app.post("/render")
    def render():
        data = request.get_json(silent=True) or {}
        opts = _opts_from(data)
        runid = data.get("runid") or time.strftime("%Y%m%d-%H%M%S")
        log: list[str] = []
        rmode = _resolve_mode(data)
        if rmode == "ranking":
            rl = RankingList.from_dict(data.get("ranking", {}))
            if not rl.entries:
                return jsonify(ok=False, error="No list entries."), 400
            current = data.get("style") or DEFAULT_RANK
            res = render_ranking_from_list(rl, settings, opts, runid, current)
            return jsonify(ranking_payload(runid, res.ranking, current, res.current["outputs"],
                                           res.provider_used, "", res.warnings, log))
        if rmode == "news":
            post = NewsPost.from_dict(data.get("post", {}))
            if not post.headline:
                return jsonify(ok=False, error="No headline."), 400
            current = data.get("style") or DEFAULT_NEWS
            res = render_news_from_post(post, settings, opts, runid, current)
            return jsonify(news_payload(runid, res.post, current, res.current["outputs"],
                                        res.provider_used, "", res.warnings, log))
        panels = [Panel.from_dict(p) for p in data.get("panels", []) if p.get("title")]
        if not panels:
            return jsonify(ok=False, error="No panels to render."), 400
        prep = prepare_lineup(settings, opts, panels=panels, progress=log.append)
        current = data.get("style") or DEFAULT_STYLE
        outputs = render_one(prep["panels"], settings, opts, current, runid)
        return jsonify(lineup_payload(runid, prep, current, outputs, log))

    # ---- instant template switch (no re-search) -------------------------
    @app.post("/render_one")
    def render_one_route():
        data = request.get_json(silent=True) or {}
        runid = data.get("runid") or time.strftime("%Y%m%d-%H%M%S")
        opts = _opts_from(data)
        rmode = _resolve_mode(data)
        if rmode == "ranking":
            rl = RankingList.from_dict(data.get("ranking", {}))
            if not rl.entries:
                return jsonify(ok=False, error="Nothing to render."), 400
            style = data.get("style") or DEFAULT_RANK
            outputs = render_ranking_one(rl, settings, opts, style, runid)
            return jsonify(ok=True, mode="ranking", key=style, name=RANK_NAME.get(style, style),
                           runid=runid, outputs=outputs_urls(outputs))
        if rmode == "news":
            post = NewsPost.from_dict(data.get("post", {}))
            if not post.headline:
                return jsonify(ok=False, error="Nothing to render."), 400
            style = data.get("style") or DEFAULT_NEWS
            outputs = render_news_one(post, settings, opts, style, runid)
            return jsonify(ok=True, mode="news", key=style, name=NEWS_NAME.get(style, style),
                           runid=runid, outputs=outputs_urls(outputs))
        panels = [Panel.from_dict(p) for p in data.get("panels", []) if p.get("title")]
        if not panels:
            return jsonify(ok=False, error="Nothing to render."), 400
        style = data.get("style") or DEFAULT_STYLE
        outputs = render_one(panels, settings, opts, style, runid)
        return jsonify(ok=True, mode="lineup", key=style, name=_STYLE_NAME.get(style, style),
                       runid=runid, outputs=outputs_urls(outputs))

    # ---- carousel zip (line-up) -----------------------------------------
    @app.post("/carousel")
    def carousel():
        data = request.get_json(silent=True) or {}
        panels = [Panel.from_dict(p) for p in data.get("panels", []) if p.get("title")]
        runid = data.get("runid") or time.strftime("%Y%m%d-%H%M%S")
        style_key = data.get("style") or DEFAULT_STYLE
        if not panels:
            return jsonify(ok=False, error="No panels."), 400
        out = build_carousel(panels, settings, _opts_from(data), style_key, runid,
                             with_cover=_bool(data.get("cover"), True))
        return jsonify(ok=True, cards=[file_url(c) for c in out["cards"]], zip=file_url(out["zip"]))

    # ---- export the FULL gallery (every template, current content) -------
    @app.post("/export_all")
    def export_all_route():
        data = request.get_json(silent=True) or {}
        opts = _opts_from(data)
        runid = data.get("runid") or time.strftime("%Y%m%d-%H%M%S")
        mode = _resolve_mode(data)
        kw = {}
        if mode == "news":
            post = NewsPost.from_dict(data.get("post", {}))
            if not post.headline:
                return jsonify(ok=False, error="Nothing to export."), 400
            kw["post"] = post
        elif mode == "ranking":
            rl = RankingList.from_dict(data.get("ranking", {}))
            if not rl.entries:
                return jsonify(ok=False, error="Nothing to export."), 400
            kw["ranking"] = rl
        else:
            panels = [Panel.from_dict(p) for p in data.get("panels", []) if p.get("title")]
            if not panels:
                return jsonify(ok=False, error="Nothing to export."), 400
            kw["panels"] = panels
        out = export_all(mode, settings, opts, runid, **kw)
        return jsonify(ok=True, zip=file_url(out["zip"]), count=out["count"],
                       templates=out["templates"])

    # ---- uploads / logos ------------------------------------------------
    @app.post("/upload")
    def upload():
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify(ok=False, error="No file."), 400
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_IMG_EXT:
            return jsonify(ok=False, error="Use PNG/JPG/WEBP."), 400
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        name = f"upload_{uuid.uuid4().hex[:12]}{ext}"
        dest = CACHE_DIR / name
        f.save(dest)
        return jsonify(ok=True, image_path=str(dest), url=file_url(str(dest)))

    @app.post("/upload_logo")
    def upload_logo():
        f = request.files.get("file")
        title = (request.form.get("title") or "logo").strip()
        if not f or not f.filename:
            return jsonify(ok=False, error="No file."), 400
        if Path(f.filename).suffix.lower() not in ALLOWED_IMG_EXT:
            return jsonify(ok=False, error="Use PNG/WEBP (transparent)."), 400
        try:
            path = logos.save_logo(title, f.stream)
            return jsonify(ok=True, logo_path=path, url=file_url(path))
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 500

    @app.post("/find_logo")
    def find_logo():
        data = request.get_json(silent=True) or {}
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify(ok=False, error="No title."), 400
        from ..providers import get_text_provider
        prov = get_text_provider(settings, data.get("provider"))
        path = logos.search_logo(title, settings, prov)
        if not path:
            return jsonify(ok=False, error="No clean logo found — try uploading one.")
        return jsonify(ok=True, logo_path=path, url=file_url(path))

    # ---- misc -----------------------------------------------------------
    @app.get("/file/<path:relpath>")
    def serve_file(relpath):
        which = request.args.get("d", "output")
        base = {"output": Path(settings.output_dir), "cache": CACHE_DIR}.get(which)
        if base is None:
            abort(404)
        return send_from_directory(base.resolve(), relpath)

    # ---- API keys (saved to .env, applied live) -------------------------
    @app.get("/settings")
    def settings_get():
        def stat(v):
            v = v or ""
            return {"set": bool(v), "hint": ("•••• " + v[-4:]) if len(v) >= 6 else ("set" if v else "")}
        return jsonify(ok=True,
                       providers=settings.available_text_providers(),
                       text_provider=settings.text_provider,
                       resolved=settings.resolve_text_provider(),
                       fields={f: stat(getattr(settings, f, "")) for f in _KEY_FIELDS})

    @app.post("/settings")
    def settings_post():
        data = request.get_json(silent=True) or {}
        updates = {}
        for field, env in _KEY_FIELDS.items():
            if field not in data:
                continue
            val = (data.get(field) or "").strip()
            if val == "":                 # blank = leave the saved value untouched
                continue
            if val == "__CLEAR__":        # explicit clear
                val = ""
            setattr(settings, field, val)
            os.environ[env] = val
            updates[env] = val
        tp = (data.get("text_provider") or "").strip().lower()
        if tp in ("auto", "none", "claude", "openai", "gemini", "grok"):
            settings.text_provider = tp
            os.environ["IMAGEBOT_TEXT_PROVIDER"] = tp
            updates["IMAGEBOT_TEXT_PROVIDER"] = tp
        wrote = True
        if updates:
            try:
                _update_env_file(ROOT / ".env", updates)
            except Exception as e:
                wrote = False
                return jsonify(ok=True, saved=False, wrote=False, note=f"applied now, but couldn't write .env: {e}",
                               providers=settings.available_text_providers(),
                               text_provider=settings.text_provider,
                               resolved=settings.resolve_text_provider())
        return jsonify(ok=True, saved=True, wrote=wrote,
                       providers=settings.available_text_providers(),
                       text_provider=settings.text_provider,
                       resolved=settings.resolve_text_provider())

    @app.get("/capabilities")
    def capabilities():
        return jsonify(ok=True, capabilities=_caps(), providers=settings.available_text_providers())

    @app.get("/health")
    def health():
        return jsonify(ok=True, providers=settings.available_text_providers())

    return app
