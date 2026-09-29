"""Models reached with an Anthropic API key.

They work like every other backend (see backend.py): the model reports what changed in the
memory and supplies the CV's wording, and the app does the merging and the layout. The one
difference is that Anthropic's API can read PDFs directly, so scanned CVs can be imported.
"""

from __future__ import annotations

import base64
import os
from datetime import date
from pathlib import Path

import anthropic

from .backend import (
    INGEST_SYSTEM,
    ChatBackend,
    CVWording,
    MemoryUpdate,
    _compact,
    apply_update,
    pdf_to_text,
)
from .common import AIError, Attachment
from .assistant import Email, InterviewPrep, LinkedInProfile, StrengthenQuestions, SupervisorEmail, TruthReport
from .schema import BaseModel, CVDocument, IngestResult, Memory
from .writing import BulletSuggestions, CoverLetter

__all__ = ["AIError", "Attachment", "ClaudeAI", "MODEL"]

MODEL = os.environ.get("CV_MAKER_MODEL", "claude-opus-5-5")

# How hard the model should think for each kind of request.
EFFORT = {MemoryUpdate: "medium", CVWording: "high", BulletSuggestions: "low", CoverLetter: "medium",
          TruthReport: "high", StrengthenQuestions: "low", InterviewPrep: "medium", Email: "low",
          LinkedInProfile: "medium", CVDocument: "medium", SupervisorEmail: "high"}


class ClaudeAI(ChatBackend):
    local = False
    provider = "anthropic"

    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL,
                 cache_path: str | Path | None = None):
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.cache_path = Path(cache_path) if cache_path else None

    def status(self) -> dict:
        return {"label": f"{self.model} (API key)", "ready": True, "message": "", "local": False}

    def _parse(self, *, system: str, content: list[dict], output_format, effort: str):
        request = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_format=output_format,
        )
        # Newer models accept an effort level and automatic fallbacks; some older ones reject them.
        extras = dict(betas=["server-side-fallback-2026-07-01"], fallbacks="default", output_config={"effort": effort})
        try:
            try:
                response = self.client.beta.messages.parse(**request, **extras)
            except anthropic.BadRequestError as e:
                if not any(word in str(e.message).lower() for word in ("effort", "fallback", "output_config", "beta")):
                    raise
                response = self.client.beta.messages.parse(**request)
        except anthropic.AuthenticationError as e:
            raise AIError("Anthropic didn't accept the API key. Check it in the AI model box.") from e
        except anthropic.RateLimitError as e:
            raise AIError("Anthropic is rate-limiting requests. Try again in a minute.") from e
        except anthropic.APIConnectionError as e:
            raise AIError("Couldn't reach Anthropic. Check your internet connection.") from e
        except anthropic.APIStatusError as e:
            raise AIError(f"Anthropic API error ({e.status_code}): {e.message}") from e

        usage = getattr(response, "usage", None)
        self._record(output_format, getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0))
        if response.stop_reason == "refusal":
            raise AIError("The model declined this request.")
        if response.stop_reason == "max_tokens":
            raise AIError("The response was cut off because it was too long.")
        if response.parsed_output is None:
            raise AIError("The model returned a response that could not be read.")
        return response.parsed_output

    def _chat(self, system: str, user: str, output: type[BaseModel]):
        return self._parse(system=system, content=[{"type": "text", "text": user}],
                           output_format=output, effort=EFFORT.get(output, "medium"))

    def ingest(self, memory: Memory, text: str, attachments: list[Attachment] | None = None) -> IngestResult:
        """Like other backends, but PDFs without extractable text (scans) are sent for the model to read."""
        content: list[dict] = [{"type": "text", "text": f"<current_memory>\n{_compact(memory)}\n</current_memory>"}]
        for a in attachments or []:
            extracted = ""
            if a.media_type == "application/pdf":
                try:
                    extracted = pdf_to_text(a.data)
                except AIError:
                    extracted = ""
                if not extracted:
                    content.append({"type": "document", "title": a.filename, "source": {
                        "type": "base64", "media_type": "application/pdf",
                        "data": base64.standard_b64encode(a.data).decode("ascii")}})
                    continue
            else:
                extracted = a.data.decode("utf-8", errors="replace")
            content.append({"type": "text", "text": f'<file name="{a.filename}">\n{extracted}\n</file>'})
        content.append({"type": "text", "text": f"<new_information>\n{text or '(see the attached file)'}\n</new_information>"})
        update = self._parse(system=INGEST_SYSTEM.format(today=date.today().isoformat()), content=content,
                             output_format=MemoryUpdate, effort=EFFORT[MemoryUpdate])
        return IngestResult(memory=apply_update(memory, update), changes=update.changes or ["Updated memory"],
                            questions=update.questions[:3])
