"""Prompts and answer shapes for the AI helpers beyond writing the CV itself:
truth check, strengthening questions, interview prep, follow-up emails, LinkedIn text,
regional conventions and translation. Every backend gets them through ChatBackend.
"""

from __future__ import annotations

from datetime import date

from pydantic import Field

from .schema import BaseModel, Memory

TODAY = "Today's date is {today}."


def _today() -> str:
    return date.today().isoformat()


# ---- regional conventions ------------------------------------------------

REGIONS = {
    "": {"name": "No particular country", "guidance": "", "photo": True},
    "hk": {"name": "Hong Kong", "photo": True, "guidance": (
        "Write for Hong Kong employers: British spelling; make the languages the person speaks "
        "(e.g. English, Cantonese, Mandarin) easy to find; concise, at most two pages.")},
    "us": {"name": "United States (résumé)", "photo": False, "guidance": (
        "Write a US-style résumé: American spelling; aim for one page for early-career people; "
        "no photo, age, marital status or nationality; results-focused bullets with numbers.")},
    "uk": {"name": "United Kingdom", "photo": False, "guidance": (
        "Write for UK employers: British spelling; at most two pages; no photo or date of birth.")},
}

LANGUAGES = {"en": "English", "zh-Hant": "Traditional Chinese (Hong Kong)", "zh-Hans": "Simplified Chinese"}


# ---- truth check ---------------------------------------------------------

class TruthIssue(BaseModel):
    quote: str = Field("", description="The exact words from the CV that aren't supported")
    problem: str = Field("", description="What isn't backed up by the memory, in plain words")
    suggestion: str = Field("", description="A truthful replacement, or empty to remove it")


class TruthReport(BaseModel):
    issues: list[TruthIssue] = Field(default_factory=list)


TRUTH_SYSTEM = """\
You check a CV for claims that the person's career memory doesn't support, before they send it
to an employer. The memory is everything they have said about themselves.

List only real problems:
- numbers, results, dates, job titles, employers or qualifications that differ from the memory
  or appear nowhere in it;
- tools, skills or responsibilities that the memory doesn't mention;
- exaggerations, e.g. "led" where the memory says "helped", or "all" where it says "some".
Rewording that keeps the same meaning is fine; don't list it. Quote the CV exactly in `quote`.
If everything is supported, return an empty `issues` list.

""" + TODAY


def truth_prompt(memory_json: str, cv_text: str) -> tuple[str, str]:
    return (TRUTH_SYSTEM.format(today=_today()),
            f"<memory>\n{memory_json}\n</memory>\n\n<cv>\n{cv_text}\n</cv>")


# ---- strengthening interview ---------------------------------------------

class StrengthenQuestion(BaseModel):
    entry_id: str = ""
    about: str = Field("", description="Which job, project or degree the question is about, e.g. 'Data Analyst at Acme'")
    question: str = ""


class StrengthenQuestions(BaseModel):
    questions: list[StrengthenQuestion] = Field(default_factory=list)


STRENGTHEN_SYSTEM = """\
You are a CV coach interviewing someone to make their CV stronger. Read their career memory and
ask up to {count} short, specific questions whose answers would most improve it: above all the
numbers behind their achievements (how many, how much, how often, what changed, for whom), then
missing tools, scope (team size, users, budget) and missing dates.

Rules:
- One question per item, about one concrete thing, answerable in a sentence.
- Refer to their actual work, e.g. "How many samples a month did the C-FIST data system handle?"
- Most important first. Don't ask about things the memory already answers.
{focus}
""" + TODAY


def strengthen_prompt(memory_json: str, target: str, count: int = 6) -> tuple[str, str]:
    focus = (f"- Prefer questions that help with this job ad:\n{target.strip()[:3000]}" if target.strip() else "")
    return (STRENGTHEN_SYSTEM.format(count=count, focus=focus, today=_today()),
            f"<memory>\n{memory_json}\n</memory>")


def basic_questions(memory: Memory, count: int = 6) -> StrengthenQuestions:
    """Without an AI model: ask for the numbers behind bullet points that have none."""
    def job(e) -> str:
        return " at ".join(x for x in (e.role, e.organization) if x)

    questions = []
    groups = [(e.id, job(e), e.highlights) for e in memory.experience]
    groups += [(p.id, p.name, p.highlights) for p in memory.projects]
    for entry_id, about, highlights in groups:
        for h in highlights:
            if not any(ch.isdigit() for ch in h):
                questions.append(StrengthenQuestion(
                    entry_id=entry_id, about=about,
                    question=f"Can you put a number on this: \"{h}\"? (How many, how much, how often, "
                             f"or what improved and by how much?)"))
                break  # one per job, so the questions cover more of the CV
    for e in memory.experience:
        if not e.start:
            questions.append(StrengthenQuestion(entry_id=e.id, about=job(e),
                                                question="When did you start and finish this role (month and year)?"))
    if not memory.skills:
        questions.append(StrengthenQuestion(question="Which tools, programming languages and software do you use?"))
    return StrengthenQuestions(questions=questions[:count])


# ---- interview prep ------------------------------------------------------

class InterviewQuestion(BaseModel):
    question: str = ""
    why: str = Field("", description="Why they're likely to ask it, in one sentence")
    answer: list[str] = Field(default_factory=list,
                              description="3-5 talking points for a STAR answer, from the person's real experience")


class InterviewPrep(BaseModel):
    questions: list[InterviewQuestion] = Field(default_factory=list)
    ask_them: list[str] = Field(default_factory=list, description="Good questions for the candidate to ask")


INTERVIEW_SYSTEM = """\
You prepare someone for a job interview. Using the job ad and their career memory, list the
8-10 questions they're most likely to be asked for this role: a mix of motivation, technical and
behavioural questions, most likely first. For each, give short talking points for a strong answer
in the STAR shape (situation, task, action, result), using ONLY real experience from the memory,
with its specific details and numbers. If the memory has no good example for a question, say so
in the talking points and suggest how to answer honestly. Then suggest 3-4 thoughtful questions
they could ask the interviewer.

""" + TODAY


def interview_prompt(memory_json: str, target: str, company: str, role: str) -> tuple[str, str]:
    job = target.strip() or "(No job ad was given; prepare for a typical interview for the role below.)"
    return (INTERVIEW_SYSTEM.format(today=_today()),
            f"<memory>\n{memory_json}\n</memory>\n\n<job_ad>\n{job}\n</job_ad>\n\n"
            f"Company: {company or 'not given'}\nRole: {role or 'not given'}")


# ---- follow-up email -----------------------------------------------------

class Email(BaseModel):
    subject: str = ""
    body: str = ""


FOLLOW_UP_SYSTEM = """\
Write a short, polite follow-up email from a job applicant who applied {days} days ago and hasn't
heard back. At most 120 words: restate interest in the specific role, add one concrete reason
they fit (from their memory), and ask about next steps. No pleading, no cliches. Sign off with
their name. {notes}

""" + TODAY


def follow_up_prompt(memory_json: str, company: str, role: str, days: int, notes: str) -> tuple[str, str]:
    extra = f"Their notes about this application: {notes.strip()}" if notes.strip() else ""
    return (FOLLOW_UP_SYSTEM.format(days=days, notes=extra, today=_today()),
            f"<memory>\n{memory_json}\n</memory>\n\nCompany: {company or 'not given'}\nRole: {role or 'not given'}")


# ---- LinkedIn ------------------------------------------------------------

class LinkedInRole(BaseModel):
    title: str = ""
    company: str = ""
    description: str = ""


class LinkedInProfile(BaseModel):
    headline: str = Field("", description="At most 220 characters")
    about: str = Field("", description="The About section, at most 2,000 characters")
    experience: list[LinkedInRole] = Field(default_factory=list)


LINKEDIN_SYSTEM = """\
Write LinkedIn profile text from this person's career memory, so their profile matches their CV:
- `headline`: at most 220 characters: who they are and what they do, with key skills.
- `about`: 3 short paragraphs in the first person, warm and specific, at most 2,000 characters,
  ending with what they're looking for (from their goals, if any).
- `experience`: for each job, a 2-4 sentence description in the first person with the key results.
Use only facts from the memory. Follow their preferences (for example UK spelling).
{focus}
""" + TODAY


def linkedin_prompt(memory_json: str, target: str) -> tuple[str, str]:
    focus = f"They're aiming for roles like this:\n{target.strip()[:2000]}" if target.strip() else ""
    return (LINKEDIN_SYSTEM.format(focus=focus, today=_today()), f"<memory>\n{memory_json}\n</memory>")


# ---- translation ---------------------------------------------------------

TRANSLATE_SYSTEM = """\
Translate this CV into {language}. Keep the exact same structure and fields. Translate section
headings, job titles, descriptions and bullet points naturally and professionally, as a native
speaker would write a CV. Keep names of people, companies, universities and products as they are
(you may add the official local name in brackets if it's well known). Keep numbers, dates and
email addresses unchanged. Leave `advice` in English.
"""


def translate_prompt(cv_json: str, language: str) -> tuple[str, str]:
    return (TRANSLATE_SYSTEM.format(language=LANGUAGES.get(language, language)), f"<cv>\n{cv_json}\n</cv>")
