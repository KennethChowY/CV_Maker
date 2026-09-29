"""AI services that can be used with your own API key.

Anthropic has its own client (see ai.py). The others speak the OpenAI chat format, so one
client (api_models.py) covers them all, including any other OpenAI-compatible service you
point it at with a base URL.
"""

from __future__ import annotations

PROVIDERS: dict[str, dict] = {
    "anthropic": {"name": "Anthropic", "kind": "anthropic", "base_url": "https://api.anthropic.com",
                  "prefixes": ("sk-ant-",), "prefer": ("claude-opus-5-5", "claude-sonnet-5-5")},
    "openrouter": {"name": "OpenRouter", "kind": "openai", "base_url": "https://openrouter.ai/api/v1",
                   "prefixes": ("sk-or-",), "prefer": ()},
    "groq": {"name": "Groq", "kind": "openai", "base_url": "https://api.groq.com/openai/v1",
             "prefixes": ("gsk_",), "prefer": ()},
    "google": {"name": "Google Gemini", "kind": "openai",
               "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "prefixes": ("AIza",), "prefer": ()},
    "xai": {"name": "xAI", "kind": "openai", "base_url": "https://api.x.ai/v1",
            "prefixes": ("xai-",), "prefer": ()},
    "openai": {"name": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1",
               "prefixes": ("sk-",), "prefer": ()},
    "other": {"name": "Other (OpenAI-compatible)", "kind": "openai", "base_url": "", "prefixes": (), "prefer": ()},
}

def detect_provider(key: str) -> str | None:
    """Guess the service from the key's format. Order matters: 'sk-ant-' and 'sk-or-' before 'sk-'."""
    for pid, info in PROVIDERS.items():
        if any(key.startswith(p) for p in info["prefixes"]):
            return pid
    return None


def default_model(provider: str, available: list[str]) -> str:
    """The service's usual choice if we know it, else the newest model that isn't a preview or tiny variant."""
    for name in PROVIDERS.get(provider, {}).get("prefer", ()):
        if name in available:
            return name
    steady = [m for m in available if not any(w in m.lower() for w in ("preview", "nano", "lite", "exp", "tiny", "mini-"))]
    return (steady or available or [""])[0]
