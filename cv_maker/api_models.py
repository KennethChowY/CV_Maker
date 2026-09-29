"""Hosted AI models reached with your own API key through the OpenAI chat format.

Covers OpenAI, Google Gemini, Groq, OpenRouter, xAI and any other service that offers an
OpenAI-compatible endpoint. (Anthropic keys use the Anthropic client in ai.py instead.)
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import ValidationError

from .ai import AIError
from .backend import ChatBackend, parse_reply
from .providers import PROVIDERS
from .schema import BaseModel

REQUEST_TIMEOUT = 240
_NOT_WRITING = ("embed", "whisper", "tts", "audio", "image", "dall-e", "moderation", "transcribe", "realtime",
                "search", "guard", "aqa", "imagen", "veo", "computer-use", "codex", "learnlm")


class APIError(AIError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class OpenAICompatibleAI(ChatBackend):
    local = False

    def __init__(self, base_url: str, api_key: str, model: str = "", provider: str = "openai",
                 cache_path: str | Path | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.cache_path = Path(cache_path) if cache_path else None
        self._json_schema_ok = True  # switched off if the service doesn't support schema-constrained output

    # ---- HTTP ------------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float = REQUEST_TIMEOUT) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.provider == "openrouter":
            headers["X-Title"] = "CV Maker"
        req = urllib.request.Request(self.base_url + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        name = PROVIDERS.get(self.provider, {}).get("name", "The AI service")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                detail = json.loads(raw)
                detail = detail[0] if isinstance(detail, list) and detail else detail
                err = detail.get("error", detail) if isinstance(detail, dict) else detail
                message = err.get("message", raw) if isinstance(err, dict) else str(err)
            except ValueError:
                message = raw[:300]
            if e.code in (401, 403):
                raise APIError(f"{name} didn't accept the API key. Check it, or remove it and add it again.", e.code) from e
            if e.code == 402:
                raise APIError(f"{name} says the account is out of credit.", e.code) from e
            if e.code == 429:
                raise APIError(f"{name} is rate-limiting requests or the account is out of credit. "
                               f"Wait a minute and try again. ({message[:160]})", e.code) from e
            if e.code == 404:
                raise APIError(f"{name} couldn't find that model or address. ({message[:160]})", e.code) from e
            raise APIError(f"{name} returned an error ({e.code}): {message[:300]}", e.code) from e
        except (urllib.error.URLError, ConnectionError) as e:
            raise APIError(f"Couldn't reach {name}. Check your internet connection.") from e
        except TimeoutError as e:
            raise APIError(f"{name} took too long to answer. Try again.") from e

    # ---- what the app calls ------------------------------------------------

    def list_models(self) -> list[str]:
        """Models this key can use for writing, newest first. Also confirms the key works."""
        data = self._request("GET", "/models", timeout=20).get("data", [])
        models = []
        for m in data:
            mid = str(m.get("id", "")).removeprefix("models/")
            if mid and not any(bad in mid.lower() for bad in _NOT_WRITING):
                models.append((m.get("created") or 0, mid))
        models.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return list(dict.fromkeys(mid for _, mid in models))

    def status(self) -> dict:
        return {"label": f"{self.model or 'model'} (API key)", "ready": bool(self.model),
                "message": "" if self.model else "Pick a model in the AI model box.", "local": False}

    def _chat(self, system: str, user: str, output: type[BaseModel]):
        if not self.model:
            raise AIError("Pick a model for your API key in the AI model box.")
        schema = output.model_json_schema()
        last_error = None
        for _ in range(3):
            if self._json_schema_ok:
                messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
                fmt = {"type": "json_schema", "json_schema": {"name": output.__name__, "schema": schema}}
            else:
                # Older or simpler services: ask for JSON and describe the shape in the instructions.
                messages = [{"role": "system", "content": f"{system}\n\nReply with only a JSON object that "
                                                          f"matches this JSON Schema:\n{json.dumps(schema)}"},
                            {"role": "user", "content": user}]
                fmt = {"type": "json_object"}
            try:
                res = self._request("POST", "/chat/completions",
                                    {"model": self.model, "messages": messages, "response_format": fmt})
            except APIError as e:
                if self._json_schema_ok and e.status in (400, 422):
                    self._json_schema_ok = False
                    continue
                raise
            choice = (res.get("choices") or [{}])[0]
            if choice.get("finish_reason") == "length":
                raise AIError("The model's answer was cut off. Try again, or pick another model.")
            content = (choice.get("message") or {}).get("content") or ""
            try:
                return parse_reply(content, output)
            except ValidationError as e:
                last_error = e
        raise AIError(f"The model '{self.model}' kept returning answers the app couldn't read. "
                      f"Try again or pick another model. ({last_error.error_count() if last_error else 0} problems)")
