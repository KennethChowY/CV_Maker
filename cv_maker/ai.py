"""Claude-powered steps: folding new information into memory, and writing the CV."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from datetime import date

import anthropic

from .schema import CVDocument, IngestResult, Memory

MODEL = os.environ.get("CV_MAKER_MODEL", "claude-opus-5-5")

INGEST_SYSTEM = """\
You maintain a person's career memory: a structured, complete record of everything \
they have told you about their work, education, projects, skills and goals. It is \
the source of truth from which their CV is written, so it should hold more detail \
than any single CV would.

You receive the current memory and a new piece of information. Return the complete \
updated memory.

How to update:
- Keep everything already in the memory unless the new information corrects or \
removes it. Never drop items just because they seem minor.
- Merge instead of duplicating: if the input is about an existing job, degree or \
project, update that item and keep its id. New items get a new short, descriptive \
id (e.g. "exp-acme-2021").
- Record facts only. Do not invent employers, dates, numbers or skills. Keep the \
person's own numbers and specifics; they are what makes a CV strong.
- When a role ends because a new one starts (e.g. a promotion or new job), set the \
previous role's end date if it can be inferred.
- Keep separate roles separate. A different organisation, department or lab is a \
different item, even if the person held both roles at the same time. Never move \
highlights from one item to another.
- Personal, school and hobby projects go in `projects`, not `experience`. Papers, \
posters and conference talks are achievements of kind "publication" or "talk".
- Text in square brackets that is an unfilled template gap, such as [month year] or \
[rating], is not a fact. Don't store it; ask for the real value in `questions`.
- Put standing instructions about the CV itself (tone, length, spelling, what to \
emphasise) in `preferences`, and goals such as target roles in `notes`.
- In `changes`, list what you changed in a few words each.
- In `questions`, ask for at most three things that are missing and would most \
improve the CV, such as dates, measurable results or technologies used. Leave it \
empty if nothing important is missing.

Today's date is {today}."""

CV_SYSTEM = """\
You are an expert CV writer and recruiter. Using the person's career memory, write \
the strongest possible CV for them.

Principles:
- Truthful: use only facts present in the memory. Never invent numbers, titles, \
employers, dates or skills. You may rephrase and tighten, but not embellish.
- Relevant: if a target role or job description is given, select and order content \
for it and mirror its terminology where the person genuinely has the experience. \
Otherwise aim at the direction their career is heading, using any goals in `notes`.
- Achievement-focused: bullets start with a strong verb and say what was done and \
the result, with numbers where the memory has them. Usually 2–5 bullets per role; \
more for recent, relevant roles and fewer for old or unrelated ones.
- Concise: aim for one page for early-career profiles and at most two pages \
otherwise. Leave out weak or irrelevant material rather than padding.
- ATS-friendly: standard section headings (Experience, Education, Projects, \
Skills, and so on), reverse-chronological order, and dates like "Mar 2021 – Present".
- Summary: two or three sentences on who they are and what they offer, with no \
clichés.
- Leave out unfilled template gaps in square brackets, such as [rating]; mention them \
in `advice` instead.
- Follow every item in the memory's `preferences`; they override these defaults.

Put the sections in the order that best sells this person. Use `entries` for \
sections made of roles, degrees or projects, and `items` for list sections such as \
skills (e.g. "Languages: Python, Go, SQL"). In `advice`, give up to five specific \
suggestions for making the CV stronger, such as a missing metric for a named role. \
These are shown to the person and do not appear on the CV.

Today's date is {today}."""


class AIError(RuntimeError):
    pass


@dataclass
class Attachment:
    filename: str
    media_type: str
    data: bytes


def _attachment_blocks(attachments: list[Attachment]) -> list[dict]:
    blocks: list[dict] = []
    for a in attachments:
        if a.media_type == "application/pdf":
            blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(a.data).decode("ascii"),
                },
                "title": a.filename,
            })
        else:
            text = a.data.decode("utf-8", errors="replace")
            blocks.append({"type": "text", "text": f"<file name=\"{a.filename}\">\n{text}\n</file>"})
    return blocks


class ClaudeAI:
    local = False

    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model

    def status(self) -> dict:
        return {"label": "Claude (paid API)", "ready": True, "message": "", "local": False}

    def _parse(self, *, system: str, content: list[dict], output_format, effort: str):
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": content}],
                output_format=output_format,
                output_config={"effort": effort},
            )
        except anthropic.AuthenticationError as e:
            raise AIError("Claude rejected the API key. Check ANTHROPIC_API_KEY.") from e
        except anthropic.RateLimitError as e:
            raise AIError("Rate limited by the Claude API. Try again in a minute.") from e
        except anthropic.APIConnectionError as e:
            raise AIError("Could not reach the Claude API. Check your connection.") from e
        except anthropic.APIStatusError as e:
            raise AIError(f"Claude API error ({e.status_code}): {e.message}") from e

        if response.stop_reason == "refusal":
            raise AIError("Claude declined this request.")
        if response.stop_reason == "max_tokens":
            raise AIError("The response was cut off because it was too long.")
        if response.parsed_output is None:
            raise AIError("Claude returned a response that could not be read.")
        return response.parsed_output

    def ingest(self, memory: Memory, text: str, attachments: list[Attachment] | None = None) -> IngestResult:
        content = [
            {"type": "text", "text": f"<current_memory>\n{memory.model_dump_json(indent=2)}\n</current_memory>"},
            *_attachment_blocks(attachments or []),
            {"type": "text", "text": f"<new_information>\n{text or '(see attached file)'}\n</new_information>"},
        ]
        return self._parse(
            system=INGEST_SYSTEM.format(today=date.today().isoformat()),
            content=content,
            output_format=IngestResult,
            effort="medium",
        )

    def build_cv(self, memory: Memory, target: str = "") -> CVDocument:
        request = (
            f"<target>\n{target}\n</target>\nTailor the CV to this target."
            if target.strip()
            else "No specific target was given; write the strongest general CV."
        )
        content = [
            {"type": "text", "text": f"<memory>\n{memory.model_dump_json(indent=2)}\n</memory>"},
            {"type": "text", "text": request},
        ]
        return self._parse(
            system=CV_SYSTEM.format(today=date.today().isoformat()),
            content=content,
            output_format=CVDocument,
            effort="high",
        )
