"""Making emails good even with a small AI model.

- `check_email` finds what weak drafts get wrong (stock phrases, wrong length, no mention of the
  paper, numbers that aren't anywhere in the memory), so the draft can be sent back once with
  those exact problems to fix, and whatever remains is shown to the person.
- The guided email: the app writes the parts it can get right by itself (greeting, who the student
  is, the ask, the sign-off) from the memory, and the AI only writes the few sentences that need
  judgement. Small local models do much better at a small, focused task.
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import Field

from .schema import BaseModel, Memory

BANNED = [
    "aligns with", "aligned with", "align with", "i am writing to inquire", "i am writing to express",
    "i am writing to", "provides a direct foundation", "passionate", "for your review", "esteemed",
    "i hope this email finds you well", "leverage", "synergy", "deeply fascinated", "keen interest",
    "i am confident that", "perfect fit", "great fit", "cutting-edge", "delve",
]
MIN_WORDS, MAX_WORDS = 110, 260
_STOP = {"with", "from", "that", "this", "their", "using", "based", "study", "analysis", "approach", "towards"}


def _numbers(text: str) -> set[str]:
    return {n.rstrip(".,") for n in re.findall(r"\d+(?:[.,]\d+)?%?", text) if len(n.rstrip(".,%")) >= 2}


def check_email(subject: str, body: str, *, name: str = "", paper_title: str = "", context: str = "") -> list[str]:
    """Problems with a draft, in plain words. `context` is everything the email may draw facts from."""
    problems = []
    low = body.lower()
    used = [p for p in BANNED if p in low]
    if used:
        problems.append(f"Uses stock phrases: {', '.join(repr(p) for p in used[:4])}.")
    words = len(body.split())
    if words < MIN_WORDS:
        problems.append(f"Too short ({words} words); aim for {MIN_WORDS}-{MAX_WORDS - 40}.")
    elif words > MAX_WORDS:
        problems.append(f"Too long ({words} words); professors skim, so keep it under {MAX_WORDS - 40}.")
    if not low.lstrip().startswith("dear"):
        problems.append("Doesn't start with a greeting like \"Dear Professor …,\".")
    if name and name.split()[0].lower() not in low[-200:]:
        problems.append("Isn't signed with the student's name.")
    if paper_title:
        keys = {w for w in re.findall(r"[a-z]{5,}", paper_title.lower()) if w not in _STOP}
        if keys and len(keys & set(re.findall(r"[a-z]{5,}", low))) < min(2, len(keys)):
            problems.append("Doesn't clearly mention the chosen paper.")
    new = sorted(_numbers(body) - _numbers(context) - {str(date.today().year), str(date.today().year + 1)})
    if new:
        problems.append(f"Has numbers that aren't in the memory or the paper ({', '.join(new[:4])}); "
                        f"they may be made up.")
    if not subject.strip():
        problems.append("Has no subject line.")
    return problems


# ---- the guided email ---------------------------------------------------------

def _is_ongoing(end: str) -> bool:
    return end.strip().lower().rstrip(".") in ("", "present", "now", "current", "currently", "ongoing", "today", "to date")


def _year(value: str) -> str:
    m = re.search(r"(19|20)\d{2}", value)
    return m.group(0) if m else ""


def intro_sentence(memory: Memory) -> str:
    """Who the student is, straight from the memory, so no model can garble it."""
    today = date.today().isoformat()[:7]
    degrees = sorted(memory.education, key=lambda e: (e.end or e.start or ""), reverse=True)
    parts = []
    if degrees:
        e = degrees[0]
        degree = " in ".join(x for x in (e.qualification, e.field) if x) or "degree"
        if e.end and not _is_ongoing(e.end) and e.end[:7] <= today:
            year = _year(e.end)
            parts.append(f"I graduated from {e.institution}{f' in {year}' if year else ''} with a {degree}")
        elif e.institution:
            parts.append(f"I'm completing a {degree} at {e.institution}")
    current = [x for x in memory.experience if x.start and _is_ongoing(x.end)]
    current.sort(key=lambda x: (x.kind != "research", x.start), reverse=False)
    if current:
        c = current[0]
        role = " at ".join(x for x in (c.role, c.organization) if x)
        a = "an" if role[:1].lower() in "aeiou" else "a"
        parts.append(f"{'and now' if parts else 'I'} work as {a} {role}")
    if not parts:
        return "I'm [your current position]."
    return " ".join(parts) + "."


def surname(full_name: str) -> str:
    name = re.sub(r"^(prof(essor)?|dr|mr|ms|mrs)\.?\s+", "", full_name.strip(), flags=re.I)
    return name.split()[-1] if name.split() else "[name]"


class EmailPieces(BaseModel):
    """What the AI writes for the guided email; the app writes everything else."""
    paper_sentences: str = Field("", description="1-2 sentences in the student's voice about the chosen paper: what it "
                                                 "did or found, and what they found interesting or would ask")
    link_sentences: str = Field("", description="1-2 sentences: one concrete thing the student did (with a real detail "
                                                "or number from the memory) and how it connects, honestly")
    learn: str = Field("", description="Optional, a short clause: what they'd like to learn or explore in the lab")
    subject: str = Field("", description="Short, specific subject line")


PIECES_SYSTEM = """\
Write three short pieces for a prospective PhD student's first email to a professor. The app writes
the greeting, who the student is, the question about PhD places and the sign-off; you write only:
- `paper_sentences`: 1-2 sentences in the student's voice (first person) about the chosen paper:
  what it did or found, and what the student found interesting or would like to ask. Be specific
  and accurate; claim only what the paper details show.
- `link_sentences`: 1-2 sentences about ONE concrete thing the student has done (with a real
  detail or number from their memory) and how it connects to this work. Be honest: if the
  connection is only a shared method or skill, say that plainly.
- `learn`: optional, a short phrase about what they'd like to learn or explore in the lab.
- `subject`: short and specific, e.g. "Prospective PhD student: exposome data and your cohort work".
Plain, warm words. Never use: {banned}.
{extra}"""


def pieces_prompt(memory_json: str, research: str, paper: str, interest: str, instruction: str) -> tuple[str, str]:
    extra = f"The student's instruction: {instruction.strip()}" if instruction.strip() else ""
    user = f"<memory>\n{memory_json}\n</memory>\n\n<professor_research>\n{research}\n</professor_research>"
    if paper.strip():
        user += f"\n\n<chosen_paper>\n{paper.strip()}\n</chosen_paper>"
    if interest.strip():
        user += f"\n\nWhat draws the student to this professor's work, in their own words: {interest.strip()}"
    return PIECES_SYSTEM.format(banned=", ".join(f'"{b}"' for b in BANNED), extra=extra), user


def assemble_email(memory: Memory, professor: str, pieces: EmailPieces) -> tuple[str, str]:
    name = memory.profile.name or "[your name]"
    learn = pieces.learn.strip().rstrip(".")
    ask = ("Are you taking new PhD students for the coming intake? If so, I'd be glad to have a short "
           f"call{f' about joining your group and {learn}' if learn else ' about joining your group'}. "
           "My CV is attached.")
    paragraphs = [f"Dear Professor {surname(professor)},", intro_sentence(memory),
                  pieces.paper_sentences.strip(), pieces.link_sentences.strip(), ask, f"Best regards,\n{name}"]
    body = "\n\n".join(p for p in paragraphs if p)
    return pieces.subject.strip() or "Prospective PhD student", body
