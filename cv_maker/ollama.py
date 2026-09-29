"""Free, private alternative to Claude: a model running locally through Ollama.

Small local models are less reliable than Claude at rewriting a whole memory
document, so here the model only returns what changed and the merge is done in
code. Nothing already in memory can be lost by accident; only items the model
explicitly lists in `remove_ids` are removed.
"""

from __future__ import annotations

import io
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date

from pydantic import Field, ValidationError

from .ai import AIError, Attachment
from .render import assemble_cv
from .schema import (
    Achievement,
    BaseModel,
    CVDocument,
    Education,
    Experience,
    IngestResult,
    Memory,
    Profile,
    Project,
    SkillGroup,
)

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = os.environ.get("CV_MAKER_OLLAMA_MODEL", "qwen3:8b")
DEFAULT_CONTEXT = int(os.environ.get("CV_MAKER_OLLAMA_CONTEXT", "16384"))
REQUEST_TIMEOUT = 900  # CPU-only machines can take several minutes per request

INGEST_SYSTEM = """\
You keep a structured record ("memory") of a person's career, used to write their CV.
You receive the current memory and some new information. Return ONLY what changes.

Rules:
- Record facts only. Never invent employers, dates, numbers or skills.
- `profile`: the full profile with any new details filled in. Keep existing values unless corrected.
- `summary`: a new professional summary only if the person gave or changed one, otherwise "".
- `upsert_*` lists: items that are new or changed. To change an existing item, repeat it IN FULL \
with the SAME id and the change applied. New items get a new short id like "exp-acme-2021". \
Leave a list empty if nothing in it changed.
- When a new role replaces an old one (a promotion or new job), also upsert the old role with its end date.
- `skills`: only skill groups with new skills to add.
- `add_preferences`: instructions about how the CV should be written (tone, length, spelling).
- `add_notes`: goals such as target roles, or other facts that fit nowhere else.
- `remove_ids`: ids of items the person asked to delete. Usually empty.
- `changes`: a few words for each thing you changed.
- `questions`: up to three questions about missing details (dates, results, numbers) that would \
most improve the CV. Can be empty.

Today's date is {today}."""


CV_WORDING_SYSTEM = """\
You are an expert CV writer. Improve the wording of a person's CV using ONLY facts from
their career memory. The layout is handled separately; you only supply the words.

Return:
- `headline`: a short professional title for the top of the CV (e.g. "Data Analyst"),
  based on their roles and any target.
- `summary`: 2-3 sentences on who they are and what they offer. No cliches.
- `items`: one entry for EVERY id in the memory's experience, education, projects and
  achievements:
  - `include`: false only if the item is clearly irrelevant to the target. Usually true.
  - `bullets`: 2-5 strong bullet points. Start each with an action verb (Built, Led,
    Designed, Automated...). Keep every number and specific detail from the memory.
    For education and achievements, bullets can be empty.
- `skills`: skill lines like "Programming: Python, SQL", most relevant first.
- `advice`: up to 3 specific tips for making the CV stronger, such as a missing number
  for a named role.

Never invent employers, dates, numbers, tools or results that are not in the memory.
Follow every item in the memory's `preferences`.

Today's date is {today}."""


class ItemWording(BaseModel):
    id: str = ""
    include: bool = True
    bullets: list[str] = Field(default_factory=list)


class CVWording(BaseModel):
    headline: str = ""
    summary: str = ""
    items: list[ItemWording] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)


class MemoryUpdate(BaseModel):
    profile: Profile
    summary: str = ""
    upsert_experience: list[Experience] = Field(default_factory=list)
    upsert_education: list[Education] = Field(default_factory=list)
    upsert_projects: list[Project] = Field(default_factory=list)
    upsert_achievements: list[Achievement] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    add_languages: list[str] = Field(default_factory=list)
    add_interests: list[str] = Field(default_factory=list)
    add_preferences: list[str] = Field(default_factory=list)
    add_notes: list[str] = Field(default_factory=list)
    remove_ids: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


def _norm(*parts: str) -> str:
    return "|".join(p.strip().lower() for p in parts)


_SAME_ITEM = {
    "experience": lambda x: _norm(x.organization, x.role),
    "education": lambda x: _norm(x.institution, x.qualification, x.field),
    "projects": lambda x: _norm(x.name),
    "achievements": lambda x: _norm(x.title),
}


def _add_unique(existing: list[str], new: list[str]) -> list[str]:
    seen = {s.strip().lower() for s in existing}
    out = list(existing)
    for item in new:
        if item.strip() and item.strip().lower() not in seen:
            out.append(item.strip())
            seen.add(item.strip().lower())
    return out


def apply_update(memory: Memory, update: MemoryUpdate) -> Memory:
    """Merge a MemoryUpdate into a copy of memory."""
    m = memory.model_copy(deep=True)

    for field in ("name", "headline", "email", "phone", "location"):
        value = getattr(update.profile, field).strip()
        if value:
            setattr(m.profile, field, value)
    known_urls = {link.url.strip().lower() for link in m.profile.links}
    m.profile.links += [link for link in update.profile.links if link.url.strip().lower() not in known_urls]
    if update.summary.strip():
        m.summary = update.summary.strip()

    for section in ("experience", "education", "projects", "achievements"):
        items = getattr(m, section)
        same = _SAME_ITEM[section]
        for new in getattr(update, f"upsert_{section}"):
            match = next(
                (i for i, old in enumerate(items)
                 if (new.id and old.id == new.id) or (same(new).strip("|") and same(old) == same(new))),
                None,
            )
            if match is None:
                items.append(new)
            else:
                new.id = items[match].id
                items[match] = new

    for group in update.skills:
        existing = next((g for g in m.skills if g.category.strip().lower() == group.category.strip().lower()), None)
        if existing:
            existing.skills = _add_unique(existing.skills, group.skills)
        elif group.skills:
            m.skills.append(group)

    m.languages = _add_unique(m.languages, update.add_languages)
    m.interests = _add_unique(m.interests, update.add_interests)
    m.preferences = _add_unique(m.preferences, update.add_preferences)
    m.notes = _add_unique(m.notes, update.add_notes)

    if update.remove_ids:
        drop = set(update.remove_ids)
        for section in ("experience", "education", "projects", "achievements"):
            setattr(m, section, [x for x in getattr(m, section) if x.id not in drop])
    return m


def pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as e:  # pypdf raises many different error types for bad files
        raise AIError(f"Couldn't read that PDF: {e}") from e


def _attachments_as_text(attachments: list[Attachment]) -> str:
    parts = []
    for a in attachments:
        if a.media_type == "application/pdf":
            text = pdf_to_text(a.data)
            if not text:
                raise AIError(f"{a.filename} has no readable text (is it a scanned image?).")
        else:
            text = a.data.decode("utf-8", errors="replace")
        parts.append(f'<file name="{a.filename}">\n{text}\n</file>')
    return "\n\n".join(parts)


class OllamaAI:
    local = True

    def __init__(self, model: str = DEFAULT_MODEL, host: str | None = None, num_ctx: int = DEFAULT_CONTEXT):
        self.model = model
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
            content = res.get("message", {}).get("content", "")
            # Some models wrap the JSON in extra text or ``` fences; keep just the object.
            start, end = content.find("{"), content.rfind("}")
            if start != -1 and end > start:
                content = content[start:end + 1]
            try:
                return output.model_validate_json(content)
            except ValidationError as e:
                last_error = e
        raise AIError(
            f"The model '{self.model}' kept returning answers the app couldn't read. "
            f"Try again, or pick a bigger model. ({last_error.error_count() if last_error else 0} problems)"
        )

    # ---- interface used by the app -----------------------------------

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

    def ingest(self, memory: Memory, text: str, attachments: list[Attachment] | None = None) -> IngestResult:
        files = _attachments_as_text(attachments or [])
        user = (
            f"<current_memory>\n{_compact(memory)}\n</current_memory>\n\n"
            + (f"{files}\n\n" if files else "")
            + f"<new_information>\n{text or '(see the attached file)'}\n</new_information>"
        )
        update = self._chat(INGEST_SYSTEM.format(today=date.today().isoformat()), user, MemoryUpdate)
        return IngestResult(
            memory=apply_update(memory, update),
            changes=update.changes or ["Updated memory"],
            questions=update.questions[:3],
        )

    def build_cv(self, memory: Memory, target: str = "") -> CVDocument:
        """The app lays the CV out from memory; the model only improves the wording."""
        request = (
            f"<target>\n{target}\n</target>\nTailor the wording and selection to this target."
            if target.strip()
            else "No specific target was given; aim for the strongest general CV."
        )
        user = f"<memory>\n{_compact(memory)}\n</memory>\n\n{request}"
        wording = self._chat(CV_WORDING_SYSTEM.format(today=date.today().isoformat()), user, CVWording)

        known_ids = {x.id for section in (memory.experience, memory.education, memory.projects,
                                          memory.achievements) for x in section}
        items = [i for i in wording.items if i.id in known_ids]
        excluded = {i.id for i in items if not i.include}
        if excluded == known_ids:
            excluded = set()  # never let a model empty the CV
        return assemble_cv(
            memory,
            headline=wording.headline.strip(),
            summary=wording.summary.strip(),
            bullets={i.id: i.bullets for i in items if i.bullets},
            exclude=excluded,
            skills=[s for s in wording.skills if s.strip()],
            advice=wording.advice[:5],
        )


def is_installed(model: str, installed: list[str]) -> bool:
    wanted = model if ":" in model else f"{model}:latest"
    return wanted in installed or model in installed


def _compact(memory: Memory) -> str:
    """Memory as JSON without empty fields, so small models have less to read."""
    return memory.model_dump_json(indent=1, exclude_defaults=True)
