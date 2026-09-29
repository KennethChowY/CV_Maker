"""Local web app: add information in plain words, and the CV rebuilds itself."""

from __future__ import annotations

import os
import re
from html import escape
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from pydantic import ValidationError

from .ai import AIError, Attachment
from .models import NO_AI_MESSAGE, ModelManager, build_ai, credentials_configured, default_choice
from .render import basic_cv, render_cv, section_list, tidy_cv
from .schema import Memory
from .store import Store

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
EDIT_CONFLICT = (
    "Your CV has manual edits, so it wasn't rebuilt automatically. Use "
    "'Save edits to memory' to keep them, or 'Rebuild CV' to replace them."
)

__all__ = ["create_app", "select_ai", "credentials_configured", "clean_html", "main"]


def select_ai(backend: str | None = None):
    """Build the default backend: 'claude', 'ollama', 'none', or 'auto' (Claude if a key is set, else Ollama)."""
    return build_ai(default_choice(backend))


def ai_status(ai) -> dict:
    if ai is None:
        return {"label": "No AI model", "ready": False, "message": NO_AI_MESSAGE, "local": False}
    status = getattr(ai, "status", None)
    return status() if status else {"label": "AI", "ready": True, "message": "", "local": False}


def clean_html(html: str) -> str:
    """Strip anything executable from CV HTML edited in the browser."""
    html = re.sub(r"<(script|style|iframe|object|embed)\b.*?</\1\s*>", "", html, flags=re.I | re.S)
    html = re.sub(r"<(script|iframe|object|embed)\b[^>]*>", "", html, flags=re.I)
    html = re.sub(r"\s+on\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.I)
    html = re.sub(r"(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2", r'\1="#"', html, flags=re.I)
    return html


_UNSET = object()


def create_app(data_dir: str | Path | None = None, ai=_UNSET, backend: str | None = None) -> Flask:
    """Create the app. Pass `ai` to pin a specific backend object (None for no AI);
    otherwise the model is picked on the page, defaulting to `backend` / CV_MAKER_AI."""
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    store = Store(data_dir or os.environ.get("CV_MAKER_DATA", "data"))
    models = ModelManager(store, fixed=ai, pinned=True) if ai is not _UNSET else ModelManager(store, backend=backend)

    def layout() -> tuple[list[str], list[str]]:
        settings = store.load_settings()
        return settings["section_order"], settings["hidden_sections"]

    def build(target: str) -> list[str]:
        memory = store.load_memory()
        ai = models.current()
        cv = tidy_cv(ai.build_cv(memory, target) if ai else basic_cv(memory))
        store.save_cv(cv, render_cv(cv, *layout()), target)
        return cv.advice

    def state(**extra) -> Response:
        cv = store.load_cv()
        ai = models.current()
        payload = {
            "memory": store.load_memory().model_dump(),
            "history": store.history(),
            "can_undo": store.can_undo(),
            "settings": store.load_settings(),
            "cv_html": store.cv_html(),
            "cv_meta": store.cv_meta(),
            "advice": cv.advice if cv else [],
            "sections": section_list(cv, *layout()) if cv else [],
            "ai_enabled": ai is not None,
            "ai_status": ai_status(ai),
        }
        payload.update(extra)
        return jsonify(payload)

    def error(message: str, status: int = 400) -> tuple[Response, int]:
        return jsonify({"error": message}), status

    def auto_rebuild() -> dict:
        settings = store.load_settings()
        if not settings["auto_rebuild"]:
            return {}
        if store.cv_meta().get("edited"):
            return {"notice": EDIT_CONFLICT}
        try:
            build(settings["target"])
        except AIError as e:
            return {"notice": f"Memory saved, but the CV couldn't be rebuilt: {e}"}
        return {}

    @app.errorhandler(AIError)
    def handle_ai_error(e: AIError):
        return error(str(e), 502)

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name: str):
        return send_from_directory(STATIC, name)

    @app.get("/api/state")
    def get_state():
        return state()

    @app.get("/api/models")
    def get_models():
        return jsonify(models.catalog())

    @app.post("/api/models/choose")
    def choose_model():
        body = request.get_json(silent=True) or {}
        models.choose(body.get("backend", ""), body.get("model", ""))
        return state()

    @app.post("/api/models/download")
    def download_model():
        models.start_download((request.get_json(silent=True) or {}).get("model", ""))
        return jsonify(models.catalog())

    @app.post("/api/ingest")
    def ingest():
        ai = models.current()
        if not ai:
            return error(NO_AI_MESSAGE)
        text = (request.form.get("text") or "").strip()
        attachments = [
            Attachment(f.filename or "upload", f.mimetype or "text/plain", f.read())
            for f in request.files.getlist("files")
            if f.filename
        ]
        if not text and not attachments:
            return error("Type something or attach a file first.")
        for a in attachments:
            if a.media_type != "application/pdf" and not (
                a.media_type.startswith("text/") or a.filename.lower().endswith((".md", ".txt", ".json"))
            ):
                return error(f"{a.filename}: upload a PDF or a text file. Save Word documents as PDF first.")

        result = ai.ingest(store.load_memory(), text, attachments)
        label = text or ", ".join(a.filename for a in attachments)
        store.save_memory(result.memory, source="input", input_text=label, changes=result.changes)
        return state(changes=result.changes, questions=result.questions, **auto_rebuild())

    @app.post("/api/build")
    def rebuild():
        body = request.get_json(silent=True) or {}
        target = body.get("target")
        if target is not None:
            store.save_settings({"target": target})
        build(store.load_settings()["target"])
        return state()

    @app.post("/api/cv")
    def save_cv_edits():
        html = (request.get_json(silent=True) or {}).get("html")
        if not isinstance(html, str):
            return error("Missing CV HTML.")
        store.save_cv_edits(clean_html(html))
        return state()

    @app.post("/api/cv/layout")
    def save_layout():
        body = request.get_json(silent=True) or {}
        order, hidden = body.get("order"), body.get("hidden")
        if not (isinstance(order, list) and isinstance(hidden, list)):
            return error("Missing section order.")
        store.save_settings({"section_order": [str(x) for x in order], "hidden_sections": [str(x) for x in hidden]})
        cv = store.load_cv()
        if cv and store.cv_meta().get("edited") and isinstance(body.get("html"), str):
            store.save_cv_edits(clean_html(body["html"]))  # keep hand edits; the page already moved the sections
        elif cv:
            store.save_cv_html(render_cv(cv, *layout()))
        return state()

    @app.post("/api/cv/learn")
    def learn_from_cv():
        ai = models.current()
        if not ai:
            return error(NO_AI_MESSAGE)
        text = ((request.get_json(silent=True) or {}).get("text") or "").strip()
        if not text:
            return error("The CV is empty.")
        note = (
            "The person edited their CV by hand. Here is the edited text. Update the memory "
            "with any facts they corrected or added, and treat their wording as preferred phrasing. "
            "Don't remove memory items just because they are missing from this CV, because the CV "
            "is a selection.\n\n" + text
        )
        result = ai.ingest(store.load_memory(), note)
        store.save_memory(result.memory, source="cv-edits", input_text="Learned from manual CV edits", changes=result.changes)
        store.mark_cv_edits_learned()
        return state(changes=result.changes, questions=result.questions)

    @app.post("/api/undo")
    def undo():
        if not store.undo():
            return error("Nothing to undo.")
        return state(**auto_rebuild())

    @app.put("/api/memory")
    def put_memory():
        try:
            memory = Memory.model_validate(request.get_json(silent=True) or {})
        except ValidationError as e:
            return error(f"That memory isn't valid: {e.errors()[0]['msg']} at {'.'.join(map(str, e.errors()[0]['loc']))}")
        store.save_memory(memory, source="manual", input_text="Edited memory directly", changes=["Manual edit"])
        if request.args.get("rebuild") == "0":
            # Fixing several entries shouldn't trigger a slow rebuild after each one.
            return state(notice="Saved to memory. Click 'Rebuild CV' when you've finished making changes.")
        return state(**auto_rebuild())

    @app.post("/api/settings")
    def settings():
        body = request.get_json(silent=True) or {}
        # The model is changed through /api/models/choose, which checks it first.
        store.save_settings({k: v for k, v in body.items() if k not in ("ai_backend", "ai_model")})
        return state()

    @app.get("/cv.html")
    def standalone_cv():
        cv = store.load_cv()
        name = escape(cv.name if cv else "My")
        css = (STATIC / "cv.css").read_text(encoding="utf-8")
        size = store.load_settings()["page_size"]
        html = (
            f"<!doctype html><html><head><meta charset='utf-8'><title>{name} – CV</title>"
            f"<style>{css}\n@page {{ size: {size}; }}</style></head>"
            f"<body class='standalone'><article class='cv'>{store.cv_html()}</article></body></html>"
        )
        return Response(html, mimetype="text/html")

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run the CV Maker web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--data", default=os.environ.get("CV_MAKER_DATA", "data"), help="Where memory is stored")
    parser.add_argument(
        "--ai", default=os.environ.get("CV_MAKER_AI", "auto"), choices=["auto", "claude", "ollama", "none"],
        help="Starting choice until one is picked on the page. "
             "auto = Claude if ANTHROPIC_API_KEY is set, otherwise a free local model via Ollama",
    )
    args = parser.parse_args()
    app = create_app(args.data, backend=args.ai)
    print(f"CV Maker running at http://{args.host}:{args.port}  (memory in {Path(args.data).resolve()})")
    print("Pick or change the AI model in the 'AI model' box on the page.")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
