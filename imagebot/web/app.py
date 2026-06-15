"""Flask app: paste news -> generate cards -> edit & re-render -> download."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from flask import (Flask, jsonify, render_template, request,
                   send_from_directory, abort)

from ..config import get_settings
from ..image_search import CACHE_DIR
from ..models import Panel
from ..pipeline import GenerateOptions, generate_from_news, render_panels

ALLOWED_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def _opts_from_form(data: dict) -> GenerateOptions:
    def b(key, default=False):
        v = data.get(key, default)
        return v in (True, "true", "on", "1", 1) if not isinstance(v, bool) else v

    return GenerateOptions(
        provider=(data.get("provider") or None) if data.get("provider") not in ("auto", "", None) else None,
        panels_per_card=int(data.get("panels_per_card") or 4),
        watermark=data.get("watermark") if data.get("watermark") is not None else None,
        event_name=data.get("event_name") or None,
        date_text=data.get("date_text") or None,
        find_art=b("find_art", True),
        ai_fallback=b("ai_fallback", False),
        write_caption=b("write_caption", True),
        prefix=f"card_{int(time.time())}",
    )


def _result_json(res, settings):
    return {
        "ok": True,
        "provider_used": res.provider_used,
        "panels": [p.to_dict() for p in res.panels],
        "cards": [f"/file/{Path(p).name}?d=output" for p in res.card_paths],
        "caption": res.caption,
        "warnings": res.warnings,
        "log": res.log,
    }


def create_app(settings=None) -> Flask:
    settings = settings or get_settings()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25MB uploads

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            providers=settings.available_text_providers(),
            text_provider=settings.resolve_text_provider(),
            brand=settings.brand,
            themes=sorted((settings.themes or {}).keys()),
            search_keyed=bool(settings.serpapi_key or (settings.google_api_key and settings.google_cse_id)),
        )

    @app.post("/generate")
    def generate():
        data = request.get_json(silent=True) or request.form.to_dict()
        news = (data.get("news") or "").strip()
        if not news:
            return jsonify(ok=False, error="Please paste some news text."), 400
        opts = _opts_from_form(data)
        log: list[str] = []
        res = generate_from_news(news, settings, opts, progress=log.append)
        res.log = log
        return jsonify(_result_json(res, settings))

    @app.post("/render")
    def render():
        data = request.get_json(silent=True) or {}
        panels = [Panel.from_dict(p) for p in data.get("panels", []) if p.get("title")]
        if not panels:
            return jsonify(ok=False, error="No panels to render."), 400
        opts = _opts_from_form(data)
        log: list[str] = []
        res = render_panels(panels, settings, opts, progress=log.append)
        res.log = log
        return jsonify(_result_json(res, settings))

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
        return jsonify(ok=True, image_path=str(dest),
                       url=f"/file/{name}?d=cache")

    @app.get("/file/<path:name>")
    def serve_file(name):
        # only serve from the project's output/ and cache/ dirs
        which = request.args.get("d", "output")
        base = {"output": Path(settings.output_dir), "cache": CACHE_DIR}.get(which)
        if base is None:
            abort(404)
        safe = Path(name).name  # strip any path components
        return send_from_directory(base.resolve(), safe)

    @app.get("/health")
    def health():
        return jsonify(ok=True, providers=settings.available_text_providers())

    return app
