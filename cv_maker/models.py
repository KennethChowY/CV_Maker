"""Choosing, downloading and switching the AI model from the web page."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import anthropic

from .ai import MODEL as ANTHROPIC_DEFAULT_MODEL
from .ai import AIError, ClaudeAI
from .api_models import OpenAICompatibleAI
from .ollama import DEFAULT_MODEL, OllamaAI, is_installed
from .providers import PROVIDERS, default_model, detect_provider
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


def _env_anthropic() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    # A profile created with `ant auth login` is also picked up by the SDK.
    return (Path.home() / ".config" / "anthropic").exists()


def api_config(store: Store | None = None) -> dict:
    """The API key to use: one saved on the page, else an Anthropic key from the environment."""
    saved = store.load_api_config() if store is not None else {}
    if saved.get("key"):
        return {**saved, "source": "saved"}
    if _env_anthropic():
        return {"key": "", "provider": "anthropic", "base_url": "", "models": [], "source": "environment"}
    return {}


def credentials_configured(store: Store | None = None) -> bool:
    """True if an API key is available (saved on the page, or an Anthropic key in the environment)."""
    return bool(api_config(store))


def check_api_key(provider: str, key: str, base_url: str = "") -> list[str]:
    """Confirm the service accepts the key (a free request) and return the models it can use."""
    if PROVIDERS[provider]["kind"] == "anthropic":
        try:
            page = anthropic.Anthropic(api_key=key, max_retries=0, timeout=20).models.list(limit=100)
            return [m.id for m in page.data]
        except anthropic.AuthenticationError as e:
            raise AIError("Anthropic didn't accept that key. Check you copied all of it.") from e
        except anthropic.PermissionDeniedError as e:
            raise AIError("That key doesn't have permission to use these models.") from e
        except anthropic.APIConnectionError as e:
            raise AIError("Couldn't reach Anthropic to check the key. Check your internet connection.") from e
        except anthropic.APIStatusError as e:
            raise AIError(f"Anthropic couldn't check the key right now ({e.status_code}). Try again.") from e
    models = OpenAICompatibleAI(base_url or PROVIDERS[provider]["base_url"], key, provider=provider).list_models()
    if not models:
        raise AIError("The key works, but the service didn't list any models it can use.")
    return models


def default_choice(backend: str | None = None, store: Store | None = None) -> dict:
    """What to use when nothing has been picked on the page yet."""
    backend = (backend or os.environ.get("CV_MAKER_AI") or "auto").lower()
    if backend == "local":
        backend = "ollama"
    if backend in ("claude", "anthropic"):
        backend = "api"
    if backend == "auto":
        backend = "api" if credentials_configured(store) else "ollama"
    if backend not in ("api", "ollama", "none"):
        raise ValueError(f"Unknown AI backend '{backend}'. Use auto, api, ollama or none.")
    return {"backend": backend, "model": DEFAULT_MODEL if backend == "ollama" else ""}


def build_ai(choice: dict, api: dict | None = None, cache_dir: Path | None = None):
    cache = cache_dir / "wording_cache.json" if cache_dir else None
    if choice["backend"] in ("api", "claude"):
        if not api:
            return None
        provider = api.get("provider") or "anthropic"
        if PROVIDERS.get(provider, {}).get("kind") == "anthropic":
            client = anthropic.Anthropic(api_key=api["key"]) if api.get("key") else None
            return ClaudeAI(client, model=choice["model"] or ANTHROPIC_DEFAULT_MODEL, cache_path=cache)
        return OpenAICompatibleAI(api.get("base_url") or PROVIDERS[provider]["base_url"], api["key"],
                                  model=choice["model"], provider=provider, cache_path=cache)
    if choice["backend"] == "ollama":
        return OllamaAI(model=choice["model"] or DEFAULT_MODEL, cache_path=cache)
    return None


class ModelManager:
    """Holds the AI backend in use. The choice is saved with the other settings,
    so it survives restarts. Passing `fixed` pins one backend (used by tests)."""

    def __init__(self, store: Store, *, fixed=None, pinned: bool = False, backend: str | None = None):
        self.store = store
        self.pinned = pinned
        self._fixed = fixed
        self._default = default_choice(backend, store) if not pinned else {"backend": "none", "model": ""}
        self._key: tuple | None = None
        self._ai = None
        self._lock = threading.Lock()
        self.downloads: dict[str, dict] = {}

    def choice(self) -> dict:
        settings = self.store.load_settings()
        if settings.get("ai_backend"):
            backend = "api" if settings["ai_backend"] == "claude" else settings["ai_backend"]
            return {"backend": backend, "model": settings.get("ai_model", "")}
        return dict(self._default)

    def current(self):
        if self.pinned:
            return self._fixed
        choice = self.choice()
        api = api_config(self.store)
        key = (choice["backend"], choice["model"], hash((api.get("key"), api.get("provider"), api.get("base_url"))))
        with self._lock:
            if key != self._key:
                self._ai, self._key = build_ai(choice, api, self.store.dir), key
            return self._ai

    def choose(self, backend: str, model: str = "") -> None:
        if self.pinned:
            raise AIError("The AI model is fixed for this run of the app.")
        backend = (backend or "").lower()
        if backend == "claude":
            backend = "api"
        if backend not in ("api", "ollama", "none"):
            raise AIError("Pick a model from the list.")
        if backend == "api" and not credentials_configured(self.store):
            raise AIError("Add an API key in the AI model box first.")
        if backend == "ollama" and not model.strip():
            raise AIError("Pick which local model to use.")
        if backend == "api" and not model.strip():
            model = self.key_status()["model"]
        self.store.save_settings({"ai_backend": backend, "ai_model": model.strip() if backend != "none" else ""})

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
            "api_key": self.key_status(),
            "providers": [{"id": pid, "name": p["name"]} for pid, p in PROVIDERS.items()],
            "local": local,
            "downloads": self.downloads,
        }

    def key_status(self) -> dict:
        """Whether an API key is set, for which service, and its models. Never includes the key itself."""
        api = api_config(self.store)
        if not api:
            return {"set": False, "source": "", "hint": "", "provider": "", "provider_name": "", "models": [], "model": ""}
        provider = api.get("provider") or "anthropic"
        choice = self.choice()
        models = api.get("models") or ([ANTHROPIC_DEFAULT_MODEL] if provider == "anthropic" else [])
        model = choice["model"] if choice["backend"] == "api" and choice["model"] else default_model(provider, models)
        if provider == "anthropic" and not choice["model"]:
            model = ANTHROPIC_DEFAULT_MODEL
        return {"set": True, "source": api["source"], "hint": f"…{api['key'][-4:]}" if api.get("key") else "",
                "provider": provider, "provider_name": PROVIDERS.get(provider, {}).get("name", provider),
                "models": models, "model": model}

    def save_key(self, key: str, provider: str = "auto", base_url: str = "", verify=check_api_key) -> None:
        key = (key or "").strip()
        base_url = (base_url or "").strip().rstrip("/")
        if len(key) < 20 or any(c.isspace() for c in key):
            raise AIError("That doesn't look like a complete API key. Copy the whole key and paste it again.")
        if provider in ("", "auto"):
            provider = detect_provider(key)
            if not provider:
                raise AIError("Couldn't tell which service this key is for. Pick the service from the list.")
        if provider not in PROVIDERS:
            raise AIError("Unknown service.")
        if provider == "other" and not base_url.startswith(("http://", "https://")):
            raise AIError("For another service, enter its API address, e.g. https://api.example.com/v1.")
        models = verify(provider, key, base_url)
        model = ANTHROPIC_DEFAULT_MODEL if PROVIDERS[provider]["kind"] == "anthropic" else default_model(provider, models)
        self.store.save_api_config({"key": key, "provider": provider, "base_url": base_url, "models": models[:200]})
        if not self.pinned:
            self.store.save_settings({"ai_backend": "api", "ai_model": model})

    def remove_key(self) -> None:
        self.store.save_api_config(None)
        if not self.pinned and self.choice()["backend"] == "api" and not credentials_configured(self.store):
            self.store.save_settings({"ai_backend": "ollama", "ai_model": DEFAULT_MODEL})

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
