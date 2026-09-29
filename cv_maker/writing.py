"""Prompts and output shapes shared by every AI backend for bullet rewrites and cover letters."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from .schema import BaseModel, Memory

IMPROVE_MODES = {
    "stronger": "Make it stronger: open with a precise action verb, make the result or impact clear, "
                "and cut filler. Keep every fact and number.",
    "number": "Add a measurable result (how many, how much, how fast, what percentage). Use only numbers "
              "found in the memory. Where the number isn't known, write a placeholder in square brackets "
              "such as [X%] or [N users] for the person to fill in. Never make a number up.",
    "shorter": "Make it shorter: at most about 20 words, keeping the most important fact and any number.",
    "job": "Reword it to match the language of the job ad, where it's genuinely true for this person.",
    "custom": "Follow the person's instruction.",
}

IMPROVE_SYSTEM = """\
You rewrite one bullet point from a person's CV. Return exactly 3 different alternatives.

Rules:
- Use only facts from the bullet and the person's career memory. Never invent employers, tools,
  results or numbers.
- One sentence each, no full stop needed, no leading bullet character.
- Follow the person's CV preferences (for example UK spelling).

Today's date is {today}."""

LETTER_TONES = {
    "professional": "confident and professional",
    "warm": "warm, personable and genuine",
    "concise": "brief and direct: three short paragraphs, under 200 words",
}

LETTER_SYSTEM = """\
You write cover letters that get interviews. Write one for this person and this job.

Structure:
- `greeting`: "Dear Hiring Team," unless the job ad names the person to address.
- `paragraphs`: 3-4 short paragraphs, about 250-350 words in total.
  1. The role they're applying for and a specific, honest reason this role fits them.
  2-3. Evidence: two or three of their most relevant achievements from the memory, matched to what
     the job ad asks for, with the concrete details and numbers from the memory.
  Last. A short, confident close inviting a conversation.
- `closing`: e.g. "Kind regards,".

Rules:
- Tone: {tone}.
- Only use facts from the memory. Say nothing about the company that isn't in the job ad.
- No cliches such as "I am writing to express my interest" or "I believe I would be a great fit".
- Follow the person's CV preferences (for example UK spelling).

Today's date is {today}."""


class BulletSuggestions(BaseModel):
    suggestions: list[str] = Field(default_factory=list)


class CoverLetter(BaseModel):
    greeting: str = "Dear Hiring Team,"
    paragraphs: list[str] = Field(default_factory=list)
    closing: str = "Kind regards,"


def improve_prompt(memory_json: str, bullet: str, mode: str, target: str, instruction: str) -> tuple[str, str]:
    how = IMPROVE_MODES.get(mode, IMPROVE_MODES["stronger"])
    if mode == "custom" and instruction.strip():
        how += f" Instruction: {instruction.strip()}"
    user = (
        f"<memory>\n{memory_json}\n</memory>\n\n"
        + (f"<job_ad>\n{target}\n</job_ad>\n\n" if target.strip() else "")
        + f"<bullet>\n{bullet.strip()}\n</bullet>\n\nTask: {how}"
    )
    return IMPROVE_SYSTEM.format(today=date.today().isoformat()), user


def letter_prompt(memory_json: str, target: str, company: str, role: str, tone: str) -> tuple[str, str]:
    job = target.strip() or "(No job ad was given. Write a strong general letter for the role below.)"
    user = (
        f"<memory>\n{memory_json}\n</memory>\n\n<job_ad>\n{job}\n</job_ad>\n\n"
        f"Company: {company or 'not given'}\nRole: {role or 'not given'}"
    )
    system = LETTER_SYSTEM.format(tone=LETTER_TONES.get(tone, LETTER_TONES["professional"]),
                                  today=date.today().isoformat())
    return system, user


def clean_suggestions(result: BulletSuggestions, original: str) -> list[str]:
    seen, out = {original.strip().lower()}, []
    for s in result.suggestions:
        s = s.strip().lstrip("•-* ").strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out[:3]


def memory_for_prompt(memory: Memory) -> str:
    return memory.model_dump_json(indent=1, exclude_defaults=True)
