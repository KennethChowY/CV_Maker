"""Free, private option: a model running locally through Ollama."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from .ai import AIError
from .backend import (  # noqa: F401  (re-exported for callers and tests)
    CV_WORDING_SYSTEM,
    INGEST_SYSTEM,
    ChatBackend,
    CVWording,
    ItemWording,
    MemoryUpdate,
    apply_update,
    parse_reply,
    pdf_to_text,
)
from .schema import BaseModel

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = os.environ.get("CV_MAKER_OLLAMA_MODEL", "qwen3:4b")
DEFAULT_CONTEXT = int(os.environ.get("CV_MAKER_OLLAMA_CONTEXT", "16384"))
REQUEST_TIMEOUT = 900  # CPU-only machines can take several minutes per request
KEEP_LOADED = "30m"    # keep the model in memory between updates so it doesn't reload each time


class OllamaAI(ChatBackend):
    local = True

    def __init__(self, model: str = DEFAULT_MODEL, host: str | None = None, num_ctx: int = DEFAULT_CONTEXT,
                 cache_path: str | Path | None = None):
        self.model = model
        self.cache_path = Path(cache_path) if cache_path else None
        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        if "://" not in self.host:
            self.host = "http://" + self.host
        self.num_ctx = num_ctx
        # Ollama is local; don't send its traffic through any system HTTP proxy.
        self._http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._status_cache: tuple[float, dict] | None = None

    # ---- plumbing -----------------------------------------------------

    def _request(self, path: str, body: dict | None = None, timeout: float = REQUEST_TIMEOUT) -> dict:
        req = urllib.request.Request(
            self.host + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._http.open(req, timeout=timeout) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except ValueError:
                pass
            if e.code == 404 and "not found" in detail.lower():
                raise AIError(
                    f"The model '{self.model}' isn't downloaded yet. Download it in the AI model box."
                ) from e
            raise AIError(f"Ollama error ({e.code}): {detail}") from e
        except (urllib.error.URLError, ConnectionError) as e:
            raise AIError(
                "Can't reach Ollama. Start the Ollama app (or run `ollama serve`) and try again."
            ) from e
        except TimeoutError as e:
            raise AIError("The local model took too long to answer. Try a smaller model.") from e

    def _chat(self, system: str, user: str, output: type[BaseModel]):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": output.model_json_schema(),
            "think": False,
            "keep_alive": KEEP_LOADED,
            "options": {"num_ctx": self.num_ctx, "temperature": 0.2},
        }
        last_error = None
        for _ in range(3):  # small models sometimes produce invalid output; try again
            try:
                res = self._request("/api/chat", body)
            except AIError as e:
                if "think" in str(e).lower() and "think" in body:
                    body.pop("think")  # model has no thinking switch
                    continue
                raise
            if res.get("done_reason") == "length":
                raise AIError(
                    "The local model ran out of room. Set CV_MAKER_OLLAMA_CONTEXT higher (e.g. 32768)."
                )
            try:
                return parse_reply(res.get("message", {}).get("content", ""), output)
            except ValidationError as e:
                last_error = e
        raise AIError(
            f"The model '{self.model}' kept returning answers the app couldn't read. "
            f"Try again, or pick a bigger model. ({last_error.error_count() if last_error else 0} problems)"
        )

    # ---- Ollama-specific: installed models, downloads, status ---------

    def list_models(self) -> list[dict]:
        """Models downloaded in Ollama, as [{'name': 'qwen3:4b', 'size': bytes}]."""
        tags = self._request("/api/tags", timeout=3)
        return [{"name": m.get("name", ""), "size": m.get("size", 0)} for m in tags.get("models", [])]

    def pull(self, model: str, progress: Callable[[dict], None]) -> None:
        """Download a model, calling `progress` with each status update from Ollama."""
        req = urllib.request.Request(
            self.host + "/api/pull",
            data=json.dumps({"model": model, "stream": True}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._http.open(req, timeout=REQUEST_TIMEOUT) as res:
                for line in res:
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get("error"):
                        raise AIError(f"Download failed: {event['error']}")
                    progress(event)
        except urllib.error.HTTPError as e:
            raise AIError(f"Download failed ({e.code}): {e.read().decode(errors='replace')}") from e
        except (urllib.error.URLError, ConnectionError) as e:
            raise AIError("Can't reach Ollama. Start the Ollama app and try again.") from e
        except TimeoutError as e:
            raise AIError("The download stalled. Check your internet connection and try again.") from e
        finally:
            self._status_cache = None

    def status(self) -> dict:
        now = time.monotonic()
        if self._status_cache and now - self._status_cache[0] < 5:
            return self._status_cache[1]
        info = {"label": f"{self.model} (free, on this computer)", "ready": True, "message": "", "local": True}
        try:
            if not is_installed(self.model, [m["name"] for m in self.list_models()]):
                info.update(ready=False, message="This model isn't downloaded yet.")
        except AIError:
            info.update(ready=False, message="Ollama isn't running. Open the Ollama app.")
        self._status_cache = (now, info)
        return info



def is_installed(model: str, installed: list[str]) -> bool:
    wanted = model if ":" in model else f"{model}:latest"
    return wanted in installed or model in installed
