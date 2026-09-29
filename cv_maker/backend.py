"""What every chat-style AI backend shares: a local model (Ollama) or a hosted model reached
with an API key (OpenAI, Gemini, Groq, OpenRouter and others that speak the same protocol).

A backend only has to implement `_chat(system, user, output_model)`. On top of that, this
class provides updating the memory, writing the CV, improving a bullet and writing a letter.

The model only returns what changed in the memory and the merge is done in code, so
nothing already in memory can be lost by accident; only items the model explicitly lists in
`remove_ids` are removed. For the CV, the app does the layout and the model supplies wording.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import date
from pathlib import Path

from pydantic import Field

from .common import AIError, Attachment
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
from .writing import BulletSuggestions, CoverLetter, clean_suggestions, improve_prompt, letter_prompt
from .assistant import (
    Email,
    InterviewPrep,
    LinkedInProfile,
    StrengthenQuestions,
    SupervisorEmail,
    TruthReport,
    follow_up_prompt,
    interview_prompt,
    linkedin_prompt,
    strengthen_prompt,
    supervisor_prompt,
    translate_prompt,
    truth_prompt,
)

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
- Keep separate roles separate: a different organisation, department or lab is a different \
item, even if held at the same time. Never move highlights from one item to another.
- Personal, school and hobby projects go in `upsert_projects`, not experience. Papers, posters \
and talks go in `upsert_achievements` with kind "publication" or "talk". Research roles (research \
assistant, lab work, thesis research) get experience kind "research"; teaching assistant or \
tutoring roles get kind "teaching".
- Text in square brackets that is an unfilled template gap, like [month year] or [rating], is \
not a fact: leave it out and ask for the real value in `questions`.
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
- `items`: one entry for each id you are asked to write (listed at the end of the message),
  from the memory's experience, education, projects and achievements:
  - `include`: false only if the item is clearly irrelevant to the target. Usually true.
  - `bullets`: 2-5 strong bullet points. Start each with an action verb (Built, Led,
    Designed, Automated...). Keep every number and specific detail from the memory.
    For education and achievements, bullets can be empty.
- `skills`: skill lines like "Programming: Python, SQL", most relevant first.
- `advice`: up to 3 specific tips for making the CV stronger, such as a missing number
  for a named role.

Never invent employers, dates, numbers, tools or results that are not in the memory.
Leave out unfilled template gaps in square brackets, such as [rating].
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


def parse_reply(content: str, output: type[BaseModel]):
    """Validate a model's JSON reply, ignoring any text or ``` fences around the object."""
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        content = content[start:end + 1]
    return output.model_validate_json(content)


class ChatBackend:
    """Everything the app needs from an AI, built on one `_chat` call that returns JSON."""

    model: str = ""
    cache_path: Path | None = None
    local = False
    usage = None  # a UsageLog, set by the app, to keep track of tokens and cost
    provider = ""

    def _record(self, output: type[BaseModel], input_tokens, output_tokens) -> None:
        if self.usage is not None:
            try:
                self.usage.record(self.provider, self.model, output.__name__, input_tokens or 0, output_tokens or 0)
            except OSError:
                pass  # never fail a request because the log couldn't be written

    def _chat(self, system: str, user: str, output: type[BaseModel]):
        raise NotImplementedError

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

    def improve_bullet(self, memory: Memory, bullet: str, mode: str, target: str = "",
                       instruction: str = "") -> list[str]:
        system, user = improve_prompt(_compact(memory), bullet, mode, target, instruction)
        return clean_suggestions(self._chat(system, user, BulletSuggestions), bullet)

    def write_letter(self, memory: Memory, target: str, company: str, role: str, tone: str,
                     kind: str = "job") -> CoverLetter:
        """A cover letter, or for a PhD application a statement of purpose."""
        return self._chat(*letter_prompt(_compact(memory), target, company, role, tone, kind), CoverLetter)

    # ---- helpers beyond the CV itself (prompts in assistant.py) -----------

    def truth_check(self, memory: Memory, cv_text: str) -> TruthReport:
        return self._chat(*truth_prompt(_compact(memory), cv_text), TruthReport)

    def strengthen_questions(self, memory: Memory, target: str = "", count: int = 6) -> StrengthenQuestions:
        return self._chat(*strengthen_prompt(_compact(memory), target, count), StrengthenQuestions)

    def interview_prep(self, memory: Memory, target: str, company: str, role: str, kind: str = "job") -> InterviewPrep:
        return self._chat(*interview_prompt(_compact(memory), target, company, role, kind), InterviewPrep)

    def supervisor_email(self, memory: Memory, target: str, university: str, programme: str,
                         supervisor: str = "", interest: str = "", instruction: str = "") -> SupervisorEmail:
        return self._chat(*supervisor_prompt(_compact(memory), target, university, programme, supervisor,
                                             interest, instruction), SupervisorEmail)

    def follow_up_email(self, memory: Memory, company: str, role: str, days: int, notes: str = "") -> Email:
        return self._chat(*follow_up_prompt(_compact(memory), company, role, days, notes), Email)

    def linkedin(self, memory: Memory, target: str = "") -> LinkedInProfile:
        return self._chat(*linkedin_prompt(_compact(memory), target), LinkedInProfile)

    def translate_cv(self, cv: CVDocument, language: str) -> CVDocument:
        translated = self._chat(*translate_prompt(cv.model_dump_json(indent=1), language), CVDocument)
        translated.advice = cv.advice  # tips stay in English
        return translated

    # ---- wording cache: only rewrite what changed -----------------------

    def _load_cache(self) -> dict:
        if self.cache_path and self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return {"items": {}, "overall": {}}

    def _save_cache(self, cache: dict) -> None:
        if not self.cache_path:
            return
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        tmp.replace(self.cache_path)

    def build_cv(self, memory: Memory, target: str = "", conventions: str = "", academic: bool = False) -> CVDocument:
        """The app lays the CV out from memory; the model only improves the wording.

        Wording for entries that haven't changed since the last build (same entry, same
        target, same preferences, same model) is reused, so the model only writes new or
        edited entries. That's most of the time saved on a slow computer.
        `conventions` are the country's CV habits (spelling, length, what to leave out)."""
        context = _digest(self.model, target, conventions, memory.preferences, memory.notes, CV_WORDING_SYSTEM)
        entries = {x.id: x for section in (memory.experience, memory.education, memory.projects,
                                           memory.achievements) for x in section}
        entry_keys = {i: _digest(context, e.model_dump_json()) for i, e in entries.items()}
        overall_key = _digest(context, _compact(memory))

        cache = self._load_cache()
        to_write = [i for i, k in entry_keys.items() if k not in cache["items"]]
        overall = cache["overall"].get(overall_key)

        if to_write or overall is None:
            request = (
                f"<target>\n{target}\n</target>\nTailor the wording and selection to this target."
                if target.strip()
                else "No specific target was given; aim for the strongest general CV."
            )
            scope = (
                f"Return `items` ONLY for these ids: {', '.join(to_write)}. The other entries are already written."
                if to_write else "Every entry is already written: return an empty `items` list."
            )
            if conventions.strip():
                request += f"\n<conventions>\n{conventions.strip()}\n</conventions>"
            user = f"<memory>\n{_compact(memory)}\n</memory>\n\n{request}\n{scope}"
            wording = self._chat(CV_WORDING_SYSTEM.format(today=date.today().isoformat()), user, CVWording)
            for item in wording.items:
                if item.id in entry_keys:
                    cache["items"][entry_keys[item.id]] = {"include": item.include, "bullets": item.bullets}
            for i in to_write:  # entries the model skipped keep their own highlights
                cache["items"].setdefault(entry_keys[i], {"include": True, "bullets": []})
            overall = {"headline": wording.headline.strip(), "summary": wording.summary.strip(),
                       "skills": [x for x in wording.skills if x.strip()], "advice": wording.advice[:5]}
            cache["overall"] = {overall_key: overall}
            # Keep only what the current memory uses, so the cache doesn't grow forever.
            cache["items"] = {k: v for k, v in cache["items"].items() if k in set(entry_keys.values())}
            self._save_cache(cache)

        wordings = {i: cache["items"][k] for i, k in entry_keys.items()}
        excluded = {i for i, w in wordings.items() if not w["include"]}
        if entries and excluded == set(entries):
            excluded = set()  # never let a model empty the CV
        return assemble_cv(
            memory,
            academic=academic,
            headline=overall["headline"],
            summary=overall["summary"],
            bullets={i: w["bullets"] for i, w in wordings.items() if w["bullets"]},
            exclude=excluded,
            skills=overall["skills"],
            advice=overall["advice"],
        )



def _digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _compact(memory: Memory) -> str:
    """Memory as JSON without empty fields, so small models have less to read."""
    return memory.model_dump_json(indent=1, exclude_defaults=True)
