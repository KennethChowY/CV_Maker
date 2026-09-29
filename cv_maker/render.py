"""Turn a CVDocument into HTML, and build a plain CV from memory when no AI is available."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .schema import CVDocument, CVEntry, CVSection, Memory

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_cv(cv: CVDocument) -> str:
    return _env.get_template("cv.html.j2").render(cv=cv)


def _dates(start: str, end: str) -> str:
    if start and end:
        return f"{start} – {end}"
    return start or end


def basic_cv(memory: Memory) -> CVDocument:
    """A straight, unpolished layout of the memory. Used when Claude isn't configured."""
    p = memory.profile
    sections: list[CVSection] = []

    if memory.experience:
        sections.append(CVSection(heading="Experience", entries=[
            CVEntry(
                title=e.role, subtitle=e.organization, location=e.location,
                dates=_dates(e.start, e.end), description=e.description, bullets=e.highlights,
            )
            for e in memory.experience
        ]))
    if memory.education:
        sections.append(CVSection(heading="Education", entries=[
            CVEntry(
                title=", ".join(x for x in (e.qualification, e.field) if x),
                subtitle=e.institution, location=e.location, dates=_dates(e.start, e.end),
                description=e.grade, bullets=e.highlights,
            )
            for e in memory.education
        ]))
    if memory.projects:
        sections.append(CVSection(heading="Projects", entries=[
            CVEntry(
                title=pr.name, subtitle=pr.role, dates=_dates(pr.start, pr.end),
                description=pr.description, bullets=pr.highlights,
            )
            for pr in memory.projects
        ]))
    if memory.skills:
        sections.append(CVSection(
            heading="Skills",
            items=[f"{g.category}: {', '.join(g.skills)}" for g in memory.skills if g.skills],
        ))
    if memory.achievements:
        sections.append(CVSection(heading="Certifications & Awards", items=[
            " — ".join(x for x in (a.title, a.issuer, a.date) if x) for a in memory.achievements
        ]))
    if memory.languages:
        sections.append(CVSection(heading="Languages", items=[", ".join(memory.languages)]))
    if memory.interests:
        sections.append(CVSection(heading="Interests", items=[", ".join(memory.interests)]))

    return CVDocument(
        name=p.name or "Your Name",
        headline=p.headline,
        contact=[x for x in (p.email, p.phone, p.location) if x],
        links=p.links,
        summary=memory.summary,
        sections=sections,
        advice=["Set ANTHROPIC_API_KEY to have Claude select, order and polish this content."],
    )
