"""Turn a CVDocument into HTML, and lay out a CV directly from memory.

`assemble_cv` builds a consistent, well-ordered CV from the memory. It is used
as-is when no AI is configured, and with a local model supplying improved
wording, because small models are unreliable at producing a whole layout.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from .schema import CVDocument, CVEntry, CVSection, Memory

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_ONGOING = {"present", "now", "current", "currently", "ongoing", "today", "to date"}

# Unfilled template gaps like "[month year]" or "[N replays]", but not labels like "[Programming]".
PLACEHOLDER = re.compile(
    r"\[[^\]\n]{0,60}\b(?:month|year|date|rating|number|N|X|link|url|your|insert|tbd|todo|e\.g\.|"
    r"percent|amount|name|company|role|title)\b[^\]\n]{0,60}\]",
    re.IGNORECASE,
)
_DEGREE = re.compile(
    r"^(bachelor|master|doctor|associate|diploma|ph\.?d|b\.?sc|m\.?sc|b\.?a\b|m\.?a\b|b\.?eng|m\.?eng|mphil|mba|higher diploma)",
    re.IGNORECASE,
)


_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _bold(text: str) -> Markup:
    """Escape text, turning **name** into bold (used for the person's own name in citations)."""
    out, last = [], 0
    for m in _BOLD.finditer(text):
        out.append(escape(text[last:m.start()]))
        out.append(Markup("<strong>{}</strong>").format(m.group(1)))
        last = m.end()
    out.append(escape(text[last:]))
    return Markup("").join(out)


def _mark_placeholders(text: str) -> Markup:
    """Escape text and highlight unfilled placeholders so they're easy to spot on screen."""
    out, last = [], 0
    for m in PLACEHOLDER.finditer(text):
        out.append(_bold(text[last:m.start()]))
        out.append(Markup('<mark class="placeholder">{}</mark>').format(m.group(0)))
        last = m.end()
    out.append(_bold(text[last:]))
    return Markup("").join(out)


_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["mark"] = _mark_placeholders


def order_sections(cv: CVDocument, order: list[str]) -> CVDocument:
    """Sections the person has arranged come first, in their order; any others keep their place after."""
    rank = {h.strip().lower(): i for i, h in enumerate(order)}
    cv = cv.model_copy(deep=True)
    cv.sections = sorted(cv.sections, key=lambda s: rank.get(s.heading.strip().lower(), len(rank)))
    return cv


def render_letter(memory: Memory, letter, company: str = "", role: str = "", kind: str = "job") -> str:
    """HTML for a cover letter (or a PhD statement of purpose), headed with the person's name and contact details."""
    from datetime import date

    p = memory.profile
    contact = [x for x in (p.email, p.phone, p.location) if x] + [link.url for link in p.links[:2]]
    today = date.today()
    return _env.get_template("letter.html.j2").render(
        profile=p, contact=contact, company=company, role=role, letter=letter, kind=kind,
        today=f"{today.day} {today.strftime('%B %Y')}",
    )


def render_cv(cv: CVDocument, order: list[str] = (), hidden: list[str] = (), photo: str | None = None) -> str:
    """HTML for the CV. Hidden sections stay in the page (so they can be shown again) but aren't displayed.
    `photo` is a data: URI, so the image travels with the page into PDFs."""
    hidden_keys = {h.strip().lower() for h in hidden}
    return _env.get_template("cv.html.j2").render(cv=order_sections(cv, list(order)), hidden=hidden_keys, photo=photo)


_PHOTO_IMG = re.compile(r'\s*<img class="cv-photo"[^>]*>')


def with_photo(html: str, photo: str | None) -> str:
    """Add, swap or remove the photo in CV HTML, keeping any hand edits."""
    html = _PHOTO_IMG.sub("", html).replace('class="cv-header has-photo"', 'class="cv-header"')
    if photo and '<header class="cv-header"' in html:
        html = html.replace('<header class="cv-header">',
                            f'<header class="cv-header has-photo">\n  <img class="cv-photo" src="{escape(photo)}" alt="">', 1)
    return html


def section_list(cv: CVDocument, order: list[str] = (), hidden: list[str] = ()) -> list[dict]:
    """The CV's sections in display order, for the section arranger on the page."""
    hidden_keys = {h.strip().lower() for h in hidden}
    rows = [{"key": "summary", "heading": cv.summary_title or "Summary", "hidden": "summary" in hidden_keys,
             "fixed": True}] \
        if cv.summary else []
    for sec in order_sections(cv, list(order)).sections:
        key = sec.heading.strip().lower()
        rows.append({"key": key, "heading": sec.heading, "hidden": key in hidden_keys, "fixed": False})
    return rows


def placeholders(cv: CVDocument) -> list[str]:
    texts = [cv.headline, cv.summary]
    for s in cv.sections:
        texts += s.items
        for e in s.entries:
            texts += [e.title, e.subtitle, e.location, e.dates, e.description, *e.bullets]
    found: list[str] = []
    for t in texts:
        for m in PLACEHOLDER.findall(t):
            if m not in found:
                found.append(m)
    return found


def date_key(value: str) -> tuple[int, int]:
    """Sortable (year, month) for free-form dates such as '2021-03', 'Mar 2021' or 'Present'."""
    text = value.strip().lower()
    if not text:
        return (0, 0)
    if text.rstrip(".") in _ONGOING:
        return (9999, 12)
    year = re.search(r"(19|20)\d{2}", text)
    if not year:
        return (0, 0)
    month = 0
    numeric = re.search(r"(?:19|20)\d{2}[-/.](\d{1,2})\b|\b(\d{1,2})[-/.](?:19|20)\d{2}", text)
    if numeric:
        month = int(numeric.group(1) or numeric.group(2))
    else:
        month = next((i + 1 for i, m in enumerate(_MONTHS) if m in text), 0)
    return (int(year.group(0)), month if 1 <= month <= 12 else 0)


def pretty_date(value: str) -> str:
    """'2021-03' -> 'Mar 2021'; other formats are left as written."""
    value = value.strip()
    if value.lower().rstrip(".") in _ONGOING:
        return "Present"
    m = re.fullmatch(r"((?:19|20)\d{2})[-/.](\d{1,2})(?:[-/.]\d{1,2})?", value)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{_MONTHS[int(m.group(2)) - 1].title()} {m.group(1)}"
    return value


def date_range(start: str, end: str) -> str:
    start, end = pretty_date(start), pretty_date(end)
    if start and end and start != end:
        return f"{start} – {end}"
    return start or end


def _newest_first(items: list) -> list:
    return sorted(items, key=lambda x: (date_key(x.end or x.start), date_key(x.start)), reverse=True)


def _own_name(authors: str, name: str) -> str:
    """Bold the person's own name in an author list ('Chow K', 'K. Chow', 'Kenneth CHOW'), but not
    co-authors who share the surname (so 'Alex Chow' stays plain for Kenneth Chow)."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]+", name) if len(w) > 1]
    if not words:
        return authors
    surname, first = words[-1], words[0] if len(words) > 1 else ""

    def mine(author: str) -> bool:
        if not re.search(rf"\b{re.escape(surname)}\b", author, re.I):
            return False
        if not first:
            return True
        rest = re.sub(rf"\b{re.escape(surname)}\b", " ", author, flags=re.I)
        rest = re.sub(r"\([^)]*\)", " ", rest)  # e.g. "(presenter)"
        return bool(re.search(rf"\b{re.escape(first)}\b", rest, re.I)
                    or re.search(rf"(?<![A-Za-z]){first[0]}(?![a-z])", rest, re.I) and not re.search(r"[A-Za-z]{2,}", rest))

    out = []
    for part in re.split(r"(,\s*|;\s*|\s+and\s+|\s*&\s*)", authors):
        lead = re.match(r"(and\s+|&\s*)?", part).group(0)
        body = part[len(lead):]
        out.append(f"{lead}**{body.strip()}**" if body.strip() and mine(body) else part)
    return "".join(out)


def citation(a, name: str = "") -> str:
    """A paper, poster or talk as a citation, with the person's own name in bold."""
    year = date_key(a.date)[0] if a.date else 0
    status = a.status.strip().lower()
    when = f"({year})" if year and status not in ("in preparation", "under review") else f"({status or 'n.d.'})"
    kind = a.kind.strip().lower()
    venue = a.issuer.strip()
    title = a.title.strip()
    labelled = re.match(r"(poster|talk|presentation)\s*[:\-–]\s*", title, re.I)
    if labelled:  # "Poster: X" -> "X. Poster at <venue>."
        kind, title = labelled.group(1).lower(), title[labelled.end():]
    if kind in ("talk", "presentation", "poster") and venue:
        venue = f"{'Poster' if kind == 'poster' else 'Talk'} at {venue}"
    parts = [f"{_own_name(a.authors.strip(), name)} {when}.", f"{title.rstrip('.')}."]
    if venue:
        parts.append(f"{venue.rstrip('.')}.")
    if status == "accepted":
        parts.append("Accepted.")
    if a.link.strip():
        parts.append(a.link.strip())
    return " ".join(parts)


def referee_line(r) -> str:
    who = ", ".join(x for x in (r.name, r.title, r.organization) if x)
    how = " · ".join(x for x in (r.email, r.phone) if x)
    return " — ".join(x for x in (who, how, r.relationship) if x)


_THESIS_LINE = re.compile(r"(final[- ]year project|fyp|capstone|senior thesis|honou?rs thesis|thesis|dissertation)"
                          r"\b\s*[:\-–—]", re.I)

ACADEMIC_ORDER = ["Education", "Research Experience", "Research Projects", "Publications & Presentations",
                  "Teaching Experience", "Awards & Scholarships", "Professional Service", "Projects",
                  "Other Projects", "Other Experience", "Experience",
                  "Volunteering", "Skills", "Certifications", "Achievements", "Languages", "Interests", "References"]
_RESEARCH = re.compile(r"research|\blab\b|laborator|\bRA\b|thesis|scientist|fellow", re.I)
_TEACHING = re.compile(r"teaching|tutor|\bTA\b|lecturer|instructor|demonstrator|grader", re.I)


def _is_research(e) -> bool:
    return e.kind.strip().lower() == "research" or bool(_RESEARCH.search(f"{e.role} {e.organization}"))


def _is_teaching(e) -> bool:
    return e.kind.strip().lower() == "teaching" or bool(_TEACHING.search(e.role))


def assemble_cv(
    memory: Memory,
    *,
    headline: str = "",
    summary: str = "",
    bullets: dict[str, list[str]] | None = None,
    exclude: set[str] | frozenset[str] = frozenset(),
    skills: list[str] | None = None,
    advice: list[str] | None = None,
    academic: bool = False,
    references: bool = True,
) -> CVDocument:
    """Lay out the memory as a CV. Optional arguments replace wording (by item id) or hide items.
    `academic` lays it out for PhD and research applications: education first, then research
    experience, publications and presentations, teaching, and awards."""
    bullets = bullets or {}
    p = memory.profile

    def keep(item) -> bool:
        return item.id not in exclude

    def points(item, fallback: list[str]) -> list[str]:
        return [b for b in bullets.get(item.id) or fallback if b.strip()]

    jobs = [e for e in _newest_first(memory.experience) if keep(e) and e.kind != "volunteering"]
    volunteering = [e for e in _newest_first(memory.experience) if keep(e) and e.kind == "volunteering"]

    def organisation(e) -> str:
        """On academic CVs, research roles name the PI: committees often know them."""
        org = e.organization if e.role else ""
        sup = e.supervisor.strip()
        if academic and sup:
            sup = sup if re.match(r"(pi|supervisor|advis[eo]r)\b", sup, re.I) else f"PI: {sup}"
            return " · ".join(x for x in (org, sup) if x)
        return org

    def experience_section(heading: str, items) -> CVSection:
        return CVSection(heading=heading, entries=[
            CVEntry(
                title=e.role or e.organization,
                subtitle=organisation(e),
                location=e.location,
                dates=date_range(e.start, e.end),
                description="" if bullets.get(e.id) else e.description,
                bullets=points(e, e.highlights),
            )
            for e in items
        ])

    sections: list[CVSection] = []
    research, teaching = [], []
    if academic:
        research = [e for e in jobs if _is_research(e)]
        teaching = [e for e in jobs if e not in research and _is_teaching(e)]
        jobs = [e for e in jobs if e not in research and e not in teaching]
    experience = experience_section("Other Experience" if research else "Experience", jobs) if jobs else None

    def education_entry(e) -> CVEntry:
        degree = ", ".join(x for x in (e.qualification, e.field) if x)
        details = points(e, e.highlights)
        if not degree:
            # Models sometimes file the degree name as a highlight; promote it to the title.
            named = next((d for d in details if _DEGREE.match(d.strip())), "")
            if named:
                degree, details = named.strip(), [d for d in details if d is not named]
        thesis = e.thesis.strip()
        if thesis:  # one line under the degree, whatever the AI wrote for the other details
            labelled = re.match(r"(thesis|dissertation|capstone|final[- ]year|honou?rs|senior)\b", thesis, re.I)
            details = [thesis if labelled else f"Final-year project: {thesis}"] + \
                      [d for d in details if thesis.lower() not in d.lower() and not _THESIS_LINE.match(d.strip())]
        grade = e.grade.strip()
        if grade and re.fullmatch(r"[\d.]+\s*/\s*[\d.]+", grade):
            grade = f"GPA {grade}"
        return CVEntry(
            title=degree or e.institution,
            subtitle=e.institution if degree else "",
            location=e.location,
            dates=date_range(e.start, e.end),
            description=grade,
            bullets=details,
        )

    education_items = [e for e in _newest_first(memory.education) if keep(e)]
    education = CVSection(heading="Education", entries=[education_entry(e) for e in education_items]) \
        if education_items else None

    # Early-career CVs lead with education; everyone else leads with experience.
    # Academic CVs always lead with education.
    has_full_jobs = not academic and any(e.kind in ("work", "freelance") for e in jobs)
    for section in ((experience, education) if has_full_jobs else (education, experience)):
        if section:
            sections.append(section)

    project_items = [pr for pr in _newest_first(memory.projects) if keep(pr)]

    def project_entry(pr) -> CVEntry:
        return CVEntry(
            title=pr.name,
            subtitle=pr.role,
            location=pr.link,
            dates=date_range(pr.start, pr.end),
            description="" if bullets.get(pr.id) else pr.description,
            bullets=points(pr, pr.highlights),
        )

    research_projects = []
    if academic:  # academic CVs file research projects with research experience, not with side projects
        research_projects = [pr for pr in project_items if pr.kind.strip().lower() == "research"]
        project_items = [pr for pr in project_items if pr not in research_projects]
    if project_items:
        sections.append(CVSection(heading="Projects", entries=[project_entry(pr) for pr in project_items]))
    if volunteering:
        sections.append(experience_section("Volunteering", volunteering))

    skill_lines = skills if skills else [f"{g.category}: {', '.join(g.skills)}" if g.category else ", ".join(g.skills)
                                         for g in memory.skills if g.skills]
    if skill_lines:
        sections.append(CVSection(heading="Skills", items=skill_lines))

    achievements = sorted((a for a in memory.achievements if keep(a)), key=lambda a: date_key(a.date), reverse=True)
    groups = [
        ("Publications & Presentations", ("publication", "paper", "talk", "presentation", "poster", "conference")),
        ("Certifications", ("certification", "certificate", "license", "course")),
        ("Awards", ("award", "honour", "honor", "scholarship", "prize")),
        ("Professional Service" if academic else "Leadership & Service",
         ("service", "reviewing", "reviewer", "committee", "outreach", "mentoring", "membership", "organising",
          "organizing", "leadership")),
    ]
    placed: set[int] = set()
    for heading, kinds in groups:
        members = [a for a in achievements if a.kind.strip().lower() in kinds]
        placed |= {id(a) for a in members}
        if members:
            sections.append(CVSection(heading=heading, items=[
                citation(a, p.name) if heading.startswith("Publications") and a.authors.strip()
                else " — ".join(x for x in (a.title, a.issuer, pretty_date(a.date)) if x) for a in members
            ]))
    others = [a for a in achievements if id(a) not in placed]
    if others:
        sections.append(CVSection(heading="Achievements", items=[
            " — ".join(x for x in (a.title, a.issuer, pretty_date(a.date)) if x) for a in others
        ]))
    if memory.languages:
        sections.append(CVSection(heading="Languages", items=[", ".join(memory.languages)]))
    if memory.interests:
        sections.append(CVSection(heading="Interests", items=[", ".join(memory.interests)]))

    if academic and references and memory.referees:
        sections.append(CVSection(heading="References", items=[referee_line(r) for r in memory.referees if r.name]))
    if academic:
        if research or research_projects:
            section = experience_section("Research Experience", research)
            section.entries += [project_entry(pr) for pr in research_projects]
            sections.append(section)
        if teaching:
            sections.append(experience_section("Teaching Experience", teaching))
        for s in sections:
            if s.heading == "Awards":
                s.heading = "Awards & Scholarships"
            elif s.heading == "Projects":
                s.heading = "Other Projects" if research or research_projects else "Projects"
        rank = {h: i for i, h in enumerate(ACADEMIC_ORDER)}
        sections.sort(key=lambda s: rank.get(s.heading, len(rank)))  # stable: unknown sections keep their order

    if academic:  # a line of research interests instead of a sales-pitch summary, and no job title
        summary = summary or " · ".join(memory.research_interests)
        headline = "-"
    return CVDocument(
        name=p.name or "Your Name",
        headline="" if headline == "-" else headline or p.headline,
        contact=[x for x in (p.email, p.phone, p.location) if x],
        links=p.links,
        summary_title="Research Interests" if academic else "",
        summary=summary or ("" if academic else memory.summary),
        sections=sections,
        advice=advice or [],
    )


def basic_cv(memory: Memory, academic: bool = False, references: bool = True) -> CVDocument:
    """The memory laid out without any AI polishing."""
    cv = assemble_cv(memory, academic=academic, references=references)
    cv.advice = ["Choose an AI model to have your CV's wording polished and tailored."]
    return cv


def tidy_cv(cv: CVDocument) -> CVDocument:
    """Remove empty or duplicated parts that models sometimes produce."""
    sections = []
    seen_headings = set()
    for s in cv.sections:
        heading = s.heading.strip()
        if cv.summary and heading.lower() in ("summary", "profile", "professional summary", "about me"):
            continue
        entries = []
        for e in s.entries:
            e.bullets = [b.strip().lstrip("•-* ").strip() for b in e.bullets if b.strip().lstrip("•-* ").strip()]
            if e.title.strip() or e.subtitle.strip():
                entries.append(e)
        items = [i.strip() for i in s.items if i.strip()]
        if not heading or not (entries or items) or heading.lower() in seen_headings:
            continue
        seen_headings.add(heading.lower())
        sections.append(CVSection(heading=heading, entries=entries, items=items))
    cv.sections = sections
    cv.contact = [c.strip() for c in cv.contact if c.strip()]
    cv.links = [link for link in cv.links if link.url.strip()]
    cv.name = cv.name.strip() or "Your Name"
    gaps = placeholders(cv)
    if gaps:
        note = "Fill in the highlighted gaps still on your CV: " + ", ".join(gaps[:6]) + \
               ". Tell the app the real details, or fix them in the Memory tab."
        cv.advice = [note] + [a for a in cv.advice if not a.startswith("Fill in the highlighted gaps")]
    return cv
