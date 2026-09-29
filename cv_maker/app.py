"""Local web app: add information in plain words, and the CV rebuilds itself."""

from __future__ import annotations

import os
import re
from html import escape
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory
from flask.testing import FlaskClient
from pydantic import ValidationError

from urllib.parse import quote

from .ai import AIError, Attachment
from .export import ExportError, docx_to_text, html_to_docx, html_to_pdf, letter_to_docx, page_document
from .models import (
    NO_AI_MESSAGE,
    ModelManager,
    api_config,
    build_ai,
    check_api_key,
    credentials_configured,
    default_choice,
)
from .render import basic_cv, render_cv, render_letter, section_list, tidy_cv
from .schema import Memory
from .store import GENERAL, STATUSES, Store
from .writing import IMPROVE_MODES, LETTER_TONES

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
TEMPLATES = ("classic", "modern", "minimal")
EDIT_CONFLICT = (
    "Your CV has manual edits, so it wasn't rebuilt automatically. Use "
    "'Save edits to memory' to keep them, or 'Rebuild CV' to replace them."
)

__all__ = ["create_app", "select_ai", "credentials_configured", "clean_html", "main"]


def select_ai(backend: str | None = None):
    """Build the default backend: 'api', 'ollama', 'none', or 'auto' (an API key if one is set, else Ollama)."""
    return build_ai(default_choice(backend), api_config())


def ai_status(ai) -> dict:
    if ai is None:
        return {"label": "No AI model", "ready": False, "message": NO_AI_MESSAGE, "local": False}
    status = getattr(ai, "status", None)
    return status() if status else {"label": "AI", "ready": True, "message": "", "local": False}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def attachment(filename: str) -> str:
    """Content-Disposition value that works for names with accents or dashes."""
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def clean_html(html: str) -> str:
    """Strip anything executable from CV HTML edited in the browser."""
    html = re.sub(r"<(script|style|iframe|object|embed)\b.*?</\1\s*>", "", html, flags=re.I | re.S)
    html = re.sub(r"<(script|iframe|object|embed)\b[^>]*>", "", html, flags=re.I)
    html = re.sub(r"\s+on\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.I)
    html = re.sub(r"(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2", r'\1="#"', html, flags=re.I)
    return html


_UNSET = object()
PAGE_HEADER = "X-CV-Maker"  # set by the app's own page; other websites can't add it without being blocked
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


class _PageClient(FlaskClient):
    """Test client that behaves like the app's own page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.environ_base["HTTP_X_CV_MAKER"] = "1"


def create_app(data_dir: str | Path | None = None, ai=_UNSET, backend: str | None = None) -> Flask:
    """Create the app. Pass `ai` to pin a specific backend object (None for no AI);
    otherwise the model is picked on the page, defaulting to `backend` / CV_MAKER_AI."""
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    app.config["VERIFY_KEY"] = check_api_key
    app.config["ALLOWED_HOSTS"] = set(LOCAL_HOSTS)
    app.test_client_class = _PageClient
    store = Store(data_dir or os.environ.get("CV_MAKER_DATA", "data"))
    models = ModelManager(store, fixed=ai, pinned=True) if ai is not _UNSET else ModelManager(store, backend=backend)

    def layout() -> tuple[list[str], list[str]]:
        settings = store.load_settings()
        return settings["section_order"], settings["hidden_sections"]

    def build(vid: str | None = None) -> list[str]:
        """Rebuild a version's CV (the one open on the page by default) for its job ad."""
        vid = vid or store.active_version()
        target = store.version_info(vid)["target"]
        memory = store.load_memory()
        ai = models.current()
        cv = tidy_cv(ai.build_cv(memory, target) if ai else basic_cv(memory))
        store.save_cv(cv, render_cv(cv, *layout()), target, vid)
        return cv.advice

    def state(**extra) -> Response:
        vid = store.active_version()
        cv = store.load_cv(vid)
        ai = models.current()
        info = store.version_info(vid)
        payload = {
            "memory": store.load_memory().model_dump(),
            "history": store.history(),
            "can_undo": store.can_undo(),
            "settings": store.load_settings(),
            "active": info,
            "target": info["target"],
            "versions": store.list_versions(),
            "statuses": STATUSES,
            "cv_html": store.cv_html(vid),
            "cv_meta": store.cv_meta(vid),
            "advice": cv.advice if cv else [],
            "sections": section_list(cv, *layout()) if cv else [],
            "letter": store.load_letter(vid),
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
        vid = store.active_version()
        if vid != GENERAL and store.version_info(vid)["status"] != "Draft":
            return {"notice": "This application's CV is kept as it was sent. "
                              "Click 'Rebuild CV' if you want it to include the new information."}
        if store.cv_meta(vid).get("edited"):
            return {"notice": EDIT_CONFLICT}
        try:
            build(vid)
        except AIError as e:
            return {"notice": f"Memory saved, but the CV couldn't be rebuilt: {e}"}
        return {}

    @app.before_request
    def only_this_page():
        """Refuse requests another website makes to this app from your browser.

        Changes must carry a custom header, which browsers only let the app's own page
        send, and the Host must be this computer (which also stops DNS-rebinding tricks)."""
        host = (request.host or "").rsplit(":", 1)[0] if not (request.host or "").startswith("[") \
            else (request.host or "").split("]")[0] + "]"
        if host not in app.config["ALLOWED_HOSTS"]:
            return error("This app only answers on this computer (127.0.0.1).", 403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(PAGE_HEADER) != "1":
            return error("Request blocked: it didn't come from the CV Maker page.", 403)
        return None

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

    @app.post("/api/models/key")
    def save_key():
        body = request.get_json(silent=True) or {}
        models.save_key(str(body.get("key", "")), str(body.get("provider", "auto")), str(body.get("base_url", "")),
                        verify=app.config["VERIFY_KEY"])
        return state()

    @app.delete("/api/models/key")
    def remove_key():
        models.remove_key()
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
        attachments = []
        for f in request.files.getlist("files"):
            if not f.filename:
                continue
            name, data = f.filename, f.read()
            if name.lower().endswith(".docx"):
                try:  # Word files are turned into text here, so every model can read them
                    attachments.append(Attachment(name, "text/plain", docx_to_text(data).encode()))
                except ExportError as e:
                    return error(str(e))
            elif f.mimetype == "application/pdf" or name.lower().endswith(".pdf"):
                attachments.append(Attachment(name, "application/pdf", data))
            elif (f.mimetype or "").startswith("text/") or name.lower().endswith((".md", ".txt", ".json")):
                attachments.append(Attachment(name, "text/plain", data))
            else:
                return error(f"{name}: upload a PDF, Word (.docx) or text file.")
        if not text and not attachments:
            return error("Type something or attach a file first.")

        result = ai.ingest(store.load_memory(), text, attachments)
        label = text or ", ".join(a.filename for a in attachments)
        store.save_memory(result.memory, source="input", input_text=label, changes=result.changes)
        return state(changes=result.changes, questions=result.questions, **auto_rebuild())

    @app.post("/api/build")
    def rebuild():
        body = request.get_json(silent=True) or {}
        if isinstance(body.get("target"), str):
            store.update_version(store.active_version(), {"target": body["target"]})
        build()
        return state()

    @app.post("/api/cv")
    def save_cv_edits():
        body = request.get_json(silent=True) or {}
        html = body.get("html")
        if not isinstance(html, str):
            return error("Missing CV HTML.")
        vid = str(body.get("version") or store.active_version())  # the CV these edits were made on
        if not store.has_version(vid):
            return error("That CV no longer exists.", 404)
        store.save_cv_edits(clean_html(html), vid)
        return state()

    @app.post("/api/cv/reset")
    def discard_cv_edits():
        """Go back to the CV as it was last generated, dropping hand edits."""
        vid = store.active_version()
        cv = store.load_cv(vid)
        if not cv:
            return error("There's no generated CV to go back to.")
        store.save_cv_html(render_cv(cv, *layout()), vid)
        store.mark_cv_edits_learned(vid)
        return state()

    @app.get("/api/export/backup.zip")
    def export_backup():
        """Everything in the data folder except the API key, as one zip file."""
        import io
        import zipfile
        from datetime import date

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(store.dir.rglob("*")):
                rel = path.relative_to(store.dir)
                if path.is_file() and path.name not in ("secrets.json",) and not path.name.endswith(".tmp"):
                    z.write(path, f"data/{rel.as_posix()}")
        return Response(buffer.getvalue(), mimetype="application/zip",
                        headers={"Content-Disposition": attachment(f"CV Maker backup {date.today().isoformat()}.zip")})

    @app.post("/api/cv/layout")
    def save_layout():
        body = request.get_json(silent=True) or {}
        order, hidden = body.get("order"), body.get("hidden")
        if not (isinstance(order, list) and isinstance(hidden, list)):
            return error("Missing section order.")
        store.save_settings({"section_order": [str(x) for x in order], "hidden_sections": [str(x) for x in hidden]})
        vid = store.active_version()
        cv = store.load_cv(vid)
        if cv and store.cv_meta(vid).get("edited") and isinstance(body.get("html"), str):
            store.save_cv_edits(clean_html(body["html"]), vid)  # keep hand edits; the page already moved the sections
        elif cv:
            store.save_cv_html(render_cv(cv, *layout()), vid)
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
        store.mark_cv_edits_learned(store.active_version())
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
        body = {k: v for k, v in body.items() if k not in ("ai_backend", "ai_model", "active_version")}
        if "template" in body and body["template"] not in TEMPLATES:
            return error("Unknown template.")
        if "accent" in body and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(body["accent"])):
            return error("Accent must be a colour like #1f4e79.")
        if "fit_one_page" in body:
            body["fit_one_page"] = bool(body["fit_one_page"])
        store.save_settings(body)
        return state()

    # ---- AI writing help ------------------------------------------------

    @app.post("/api/improve")
    def improve():
        ai = models.current()
        if not ai:
            return error(NO_AI_MESSAGE)
        body = request.get_json(silent=True) or {}
        text = str(body.get("text", "")).strip()
        mode = str(body.get("mode", "stronger"))
        if not text:
            return error("Pick a bullet point first.")
        if len(text) > 1000:
            return error("That's too long for one bullet point.")
        if mode not in IMPROVE_MODES:
            return error("Unknown kind of improvement.")
        target = store.version_info(store.active_version())["target"]
        suggestions = ai.improve_bullet(store.load_memory(), text, mode, target, str(body.get("instruction", "")))
        if not suggestions:
            return error("The AI didn't come up with anything different. Try another option.", 502)
        return jsonify({"suggestions": suggestions})

    # ---- cover letter (one per version) ---------------------------------

    @app.post("/api/letter")
    def write_letter():
        ai = models.current()
        if not ai:
            return error(NO_AI_MESSAGE)
        tone = str((request.get_json(silent=True) or {}).get("tone", "professional"))
        if tone not in LETTER_TONES:
            return error("Unknown tone.")
        vid = store.active_version()
        info = store.version_info(vid)
        memory = store.load_memory()
        letter = ai.write_letter(memory, info["target"], info["company"], info["role"], tone)
        if not letter.paragraphs:
            return error("The AI didn't write a letter. Try again.", 502)
        html = render_letter(memory, letter, info["company"], info["role"])
        store.save_letter({"html": html, "tone": tone, "edited": False, "generated_at": _now_iso()}, vid)
        return state()

    @app.post("/api/letter/edits")
    def save_letter_edits():
        body = request.get_json(silent=True) or {}
        html = body.get("html")
        if not isinstance(html, str):
            return error("Missing letter.")
        vid = str(body.get("version") or store.active_version())
        if not store.has_version(vid):
            return error("That application no longer exists.", 404)
        letter = store.load_letter(vid)
        letter.update({"html": clean_html(html), "edited": True})
        store.save_letter(letter, vid)
        return jsonify({"ok": True})

    @app.get("/api/export/letter.pdf")
    def export_letter_pdf():
        body = store.load_letter(store.active_version()).get("html", "")
        if not body:
            return error("There's no cover letter to download yet.")
        d = design()
        doc = page_document(body, title=file_name("Cover Letter", "pdf"), scale=1.0, **d,
                            extra_css=".cv { padding: 20mm 22mm; }")
        doc = doc.replace("<article class='cv ", "<article class='cv cover ", 1)
        try:
            pdf = html_to_pdf(doc)
        except ExportError as e:
            return error(str(e), 501)
        return Response(pdf, mimetype="application/pdf",
                        headers={"Content-Disposition": attachment(file_name("Cover Letter", "pdf"))})

    @app.get("/api/export/letter.docx")
    def export_letter_docx():
        body = store.load_letter(store.active_version()).get("html", "")
        if not body:
            return error("There's no cover letter to download yet.")
        data = letter_to_docx(body, **design())
        return Response(data, mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": attachment(file_name("Cover Letter", "docx"))})

    # ---- job applications (each has its own tailored CV) -------------

    @app.post("/api/versions")
    def create_version():
        body = request.get_json(silent=True) or {}
        company, role = str(body.get("company", "")).strip(), str(body.get("role", "")).strip()
        if not company and not role:
            return error("Add the company or the role.")
        info = store.create_version(company=company, role=role, target=str(body.get("target", "")),
                                    link=str(body.get("link", "")))
        store.save_settings({"active_version": info["id"]})
        try:
            build(info["id"])
        except AIError as e:
            return state(notice=f"Saved the application, but its CV couldn't be tailored yet: {e}")
        return state()

    @app.patch("/api/versions/<vid>")
    def update_version(vid: str):
        if not store.has_version(vid):
            return error("That application no longer exists.", 404)
        body = request.get_json(silent=True) or {}
        if "status" in body and body["status"] not in STATUSES:
            return error("Unknown status.")
        store.update_version(vid, body)
        return state()

    @app.delete("/api/versions/<vid>")
    def delete_version(vid: str):
        if vid == GENERAL or not store.has_version(vid):
            return error("That application no longer exists.", 404)
        store.delete_version(vid)
        return state()

    @app.post("/api/versions/active")
    def open_version():
        vid = str((request.get_json(silent=True) or {}).get("id", GENERAL))
        if not store.has_version(vid):
            return error("That application no longer exists.", 404)
        store.save_settings({"active_version": vid})
        return state()

    # ---- downloads ---------------------------------------------------

    def design() -> dict:
        settings = store.load_settings()
        return {
            "template": settings["template"] if settings["template"] in TEMPLATES else "classic",
            "accent": settings["accent"] if re.fullmatch(r"#[0-9a-fA-F]{6}", settings["accent"]) else "#1f4e79",
            "page_size": settings["page_size"],
        }

    def file_name(kind: str, ext: str) -> str:
        vid = store.active_version()
        name = store.load_memory().profile.name.strip() or "My"
        company = store.version_info(vid)["company"] if vid != GENERAL else ""
        return f"{name} {kind}{f' – {company}' if company else ''}.{ext}"

    def scale_arg() -> float:
        try:
            return min(1.0, max(0.7, float(request.args.get("scale", 1))))
        except ValueError:
            return 1.0

    @app.get("/api/export/cv.pdf")
    def export_cv_pdf():
        body = store.cv_html(store.active_version())
        if not body:
            return error("There's no CV to download yet.")
        doc = page_document(body, title=file_name("CV", "pdf"), scale=scale_arg(), **design())
        try:
            pdf = html_to_pdf(doc)
        except ExportError as e:
            return error(str(e), 501)
        return Response(pdf, mimetype="application/pdf",
                        headers={"Content-Disposition": attachment(file_name("CV", "pdf"))})

    @app.get("/api/export/cv.docx")
    def export_cv_docx():
        body = store.cv_html(store.active_version())
        if not body:
            return error("There's no CV to download yet.")
        data = html_to_docx(body, **design())
        return Response(data, mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": attachment(file_name("CV", "docx"))})

    @app.get("/cv.html")
    def standalone_cv():
        cv = store.load_cv(store.active_version())
        name = escape(cv.name if cv else "My")
        css = (STATIC / "cv.css").read_text(encoding="utf-8")
        settings = store.load_settings()
        template = settings["template"] if settings["template"] in TEMPLATES else "classic"
        accent = settings["accent"] if re.fullmatch(r"#[0-9a-fA-F]{6}", settings["accent"]) else "#1f4e79"
        html = (
            f"<!doctype html><html><head><meta charset='utf-8'><title>{name} – CV</title>"
            f"<style>{css}\n@page {{ size: {settings['page_size']}; }}</style></head>"
            f"<body class='standalone'><article class='cv t-{template}'"
            f"{f' style=--cv-accent:{accent}' if template == 'modern' else ''}>"
            f"{store.cv_html(store.active_version())}</article></body></html>"
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
        "--ai", default=os.environ.get("CV_MAKER_AI", "auto"), choices=["auto", "api", "ollama", "none"],
        help="Starting choice until one is picked on the page. "
             "auto = your API key if one is set, otherwise a free local model via Ollama",
    )
    args = parser.parse_args()
    app = create_app(args.data, backend=args.ai)
    if args.host not in ("127.0.0.1", "localhost", "0.0.0.0", "::"):
        app.config["ALLOWED_HOSTS"].add(args.host)
    print(f"CV Maker running at http://{args.host}:{args.port}  (memory in {Path(args.data).resolve()})")
    print("Pick or change the AI model in the 'AI model' box on the page.")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
