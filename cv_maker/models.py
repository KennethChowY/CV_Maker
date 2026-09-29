"""Choosing, downloading and switching the AI model from the web page."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from .ai import AIError, ClaudeAI
from .ollama import DEFAULT_MODEL, OllamaAI, is_installed
from .store import Store

# Shown in the model picker even before they're downloaded. Sizes are approximate.
RECOMMENDED = [
    {"name": "qwen3:4b", "size": "2.5 GB", "note": "Fast and good. Best for most laptops."},
    {"name": "llama3.2", "size": "2 GB", "note": "Fastest, simpler writing."},
    {"name": "qwen3:8b", "size": "5.2 GB", "note": "Best free writing. Needs 16 GB of memory."},
]

NO_AI_MESSAGE = (
    "No AI model is selected. Pick one in the AI model box, or edit the memory directly."
)


def credentials_configured() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    # A profile created with `ant auth login` is also picked up by the SDK.
    return (Path.home() / ".config" / "anthropic").exists()


def default_choice(backend: str | None = None) -> dict:
    """What to use when nothing has been picked on the page yet."""
    backend = (backend or os.environ.get("CV_MAKER_AI") or "auto").lower()
    if backend == "local":
        backend = "ollama"
    if backend == "auto":
        backend = "claude" if credentials_configured() else "ollama"
    if backend not in ("claude", "ollama", "none"):
        raise ValueError(f"Unknown AI backend '{backend}'. Use auto, claude, ollama or none.")
    return {"backend": backend, "model": DEFAULT_MODEL if backend == "ollama" else ""}


def build_ai(choice: dict):
    if choice["backend"] == "claude":
        return ClaudeAI()
    if choice["backend"] == "ollama":
        return OllamaAI(model=choice["model"] or DEFAULT_MODEL)
    return None


class ModelManager:
    """Holds the AI backend in use. The choice is saved with the other settings,
    so it survives restarts. Passing `fixed` pins one backend (used by tests)."""

    def __init__(self, store: Store, *, fixed=None, pinned: bool = False, backend: str | None = None):
        self.store = store
        self.pinned = pinned
        self._fixed = fixed
        self._default = default_choice(backend) if not pinned else {"backend": "none", "model": ""}
        self._key: tuple | None = None
        self._ai = None
        self._lock = threading.Lock()
        self.downloads: dict[str, dict] = {}

    def choice(self) -> dict:
        settings = self.store.load_settings()
        if settings.get("ai_backend"):
            return {"backend": settings["ai_backend"], "model": settings.get("ai_model", "")}
        return dict(self._default)

    def current(self):
        if self.pinned:
            return self._fixed
        choice = self.choice()
        key = (choice["backend"], choice["model"])
        with self._lock:
            if key != self._key:
                self._ai, self._key = build_ai(choice), key
            return self._ai

    def choose(self, backend: str, model: str = "") -> None:
        if self.pinned:
            raise AIError("The AI model is fixed for this run of the app.")
        backend = (backend or "").lower()
        if backend not in ("claude", "ollama", "none"):
            raise AIError("Pick a model from the list.")
        if backend == "claude" and not credentials_configured():
            raise AIError("Claude needs an API key. Set ANTHROPIC_API_KEY and restart the app.")
        if backend == "ollama" and not model.strip():
            raise AIError("Pick which local model to use.")
        self.store.save_settings({"ai_backend": backend, "ai_model": model.strip() if backend == "ollama" else ""})

    def local_client(self) -> OllamaAI:
        ai = self.current()
        return ai if isinstance(ai, OllamaAI) else OllamaAI()

    def catalog(self) -> dict:
        """Everything the model picker needs to draw itself."""
        choice = self.choice()
        installed: list[dict] = []
        ollama_running = True
        try:
            installed = self.local_client().list_models()
        except AIError:
            ollama_running = False
        names = [m["name"] for m in installed]

        local = []
        for rec in RECOMMENDED:
            local.append({**rec, "installed": is_installed(rec["name"], names), "recommended": True})
        for m in installed:
            if not any(is_installed(r["name"], [m["name"]]) for r in RECOMMENDED):
                local.append({"name": m["name"], "size": f"{m['size'] / 1e9:.1f} GB", "note": "",
                              "installed": True, "recommended": False})
        if choice["backend"] == "ollama" and not any(is_installed(choice["model"], [m["name"]]) for m in local):
            local.append({"name": choice["model"], "size": "", "note": "", "installed": False, "recommended": False})

        return {
            "choice": choice,
            "pinned": self.pinned,
            "ollama_running": ollama_running,
            "claude_available": credentials_configured(),
            "local": local,
            "downloads": self.downloads,
        }

    def start_download(self, model: str) -> None:
        model = model.strip()
        if not model:
            raise AIError("Pick a model to download.")
        current = self.downloads.get(model)
        if current and current["state"] == "downloading":
            return
        self.downloads[model] = {"state": "downloading", "status": "Starting…", "completed": 0, "total": 0}
        client = self.local_client()

        def progress(event: dict) -> None:
            entry = self.downloads[model]
            entry["status"] = event.get("status", "")
            if event.get("total"):
                entry["total"] = event["total"]
                entry["completed"] = event.get("completed", 0)

        def run() -> None:
            try:
                client.pull(model, progress)
                self.downloads[model].update(state="done", status="Downloaded")
            except AIError as e:
                self.downloads[model].update(state="error", status=str(e))
            except Exception as e:  # keep the thread from dying silently
                self.downloads[model].update(state="error", status=f"Download failed: {e}")
            finally:
                if isinstance(self._ai, OllamaAI):
                    self._ai._status_cache = None

        threading.Thread(target=run, daemon=True).start()
