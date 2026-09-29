"""Reviewing the memory, only when asked: suggested fixes the person accepts or ignores one by one.

Two kinds of suggestion:
- rules (no AI, so they're reliable whichever model is used): tidy dates, merge duplicates,
  move a final-year project into its degree's thesis field, set research/teaching types,
  clean up bullet points and skills;
- the AI's: clearer wording, fixing mixed-up entries, and so on (see REVIEW_SYSTEM).

Every suggestion is a set of field changes on one item, so several can be accepted together.
"""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import Field

from .schema import Achievement, BaseModel, Education, Experience, Memory, Project

SECTIONS = {"experience": Experience, "education": Education, "projects": Project, "achievements": Achievement}
LIST_FIELDS = {"highlights", "skills"}
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_ONGOING = {"present", "now", "current", "currently", "ongoing", "today", "to date"}
_RESEARCH = re.compile(r"research|\blab\b|laborator|\bRA\b|thesis|scientist|fellow", re.I)
_TEACHING = re.compile(r"teaching|tutor|\bTA\b|lecturer|instructor|demonstrator|grader", re.I)
_THESIS = re.compile(r"^(final[- ]year project|fyp|capstone( project)?|senior thesis|honou?rs thesis|thesis|dissertation)"
                     r"\b\s*[:\-–—]?\s*\S", re.I)
_SERVICE = re.compile(r"\b(reviewer|peer review|organi[sz](er|ed|ing)|committee|mentor|outreach|volunteer tutor"
                      r"|society|club (president|chair|lead)|ambassador)\b", re.I)


def _sid(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:10]


def suggestion(source: str, section: str, item, summary: str, reason: str, changes: dict,
               remove_ids: list[str] | None = None) -> dict:
    return {"id": _sid(source, section, getattr(item, "id", ""), changes, remove_ids), "source": source,
            "section": section, "item_id": getattr(item, "id", ""), "label": label(section, item),
            "summary": summary, "reason": reason, "changes": changes, "remove_ids": remove_ids or [],
            "warnings": []}


def label(section: str, item) -> str:
    if section == "experience":
        return " at ".join(x for x in (item.role, item.organization) if x) or "Job"
    if section == "education":
        return ", ".join(x for x in (item.qualification, item.field, item.institution) if x) or "Degree"
    if section == "projects":
        return item.name or "Project"
    if section == "achievements":
        return item.title or "Achievement"
    return "Skills" if section == "skills" else section.title()


# ---- rules -------------------------------------------------------------------

def tidy_date(value: str) -> str:
    """'Jan 2024', '2024/1', '01/2024' -> '2024-01'; 'currently' -> 'Present'. Unclear dates are left alone."""
    text = value.strip()
    low = text.lower().rstrip(".")
    if not text:
        return text
    if low in _ONGOING:
        return "Present"
    m = re.fullmatch(r"((?:19|20)\d{2})", text)
    if m:
        return text
    m = re.fullmatch(r"((?:19|20)\d{2})[-/.](\d{1,2})(?:[-/.]\d{1,2})?", text)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{1,2})[-/.]((?:19|20)\d{2})", text)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"([a-z]{3,9})\.?,?\s+((?:19|20)\d{2})", low)
    if m and m.group(1)[:3] in _MONTHS:
        return f"{m.group(2)}-{_MONTHS.index(m.group(1)[:3]) + 1:02d}"
    return text


def _clean_points(points: list[str]) -> list[str]:
    seen, out = set(), []
    for p in points:
        p = re.sub(r"^\s*[•\-*·–]+\s*", "", p).strip()
        p = re.sub(r"\s{2,}", " ", p)
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def rule_suggestions(memory: Memory) -> list[dict]:
    out: list[dict] = []

    for section in SECTIONS:
        items = getattr(memory, section)
        date_fields = ("date",) if section == "achievements" else ("start", "end")
        for item in items:
            changes = {f: tidy_date(getattr(item, f)) for f in date_fields if tidy_date(getattr(item, f)) != getattr(item, f)}
            if changes:
                out.append(suggestion("rule", section, item, "Tidy the dates",
                                      "One date format everywhere keeps the CV consistent and sorts entries correctly.", changes))
            for field in LIST_FIELDS & set(type(item).model_fields):
                cleaned = _clean_points(getattr(item, field))
                if cleaned != getattr(item, field):
                    out.append(suggestion("rule", section, item, f"Clean up the {field}",
                                          "Removes repeated, empty or doubled-up bullet marks.", {field: cleaned}))

    for e in memory.experience:
        kind = e.kind.strip().lower()
        if kind not in ("research", "teaching", "volunteering"):
            if _RESEARCH.search(f"{e.role} {e.organization}"):
                out.append(suggestion("rule", "experience", e, "Mark as research experience",
                                      "Academic CVs list research roles under Research Experience.", {"kind": "research"}))
            elif _TEACHING.search(e.role):
                out.append(suggestion("rule", "experience", e, "Mark as teaching experience",
                                      "Academic CVs list teaching under Teaching Experience.", {"kind": "teaching"}))

    for p in memory.projects:
        if p.kind.strip().lower() in ("", "personal", "other") and _RESEARCH.search(f"{p.name} {p.role}"):
            out.append(suggestion("rule", "projects", p, "Mark as a research project",
                                  "Research projects go under Research Experience on academic CVs.", {"kind": "research"}))

    for e in memory.education:
        if not e.thesis.strip():
            found = next((h for h in e.highlights if _THESIS.match(h.strip())), None)
            if found:
                out.append(suggestion("rule", "education", e, "Move the final-year project to its own line",
                                      "It then shows as one clear line under the degree.",
                                      {"thesis": found.strip(), "highlights": [h for h in e.highlights if h is not found]}))

    for a in memory.achievements:
        if a.kind.strip().lower() not in ("service", "publication", "talk") and _SERVICE.search(f"{a.title} {a.description}"):
            out.append(suggestion("rule", "achievements", a, "Mark as service",
                                  "Reviewing, organising, mentoring and outreach go under Professional Service.",
                                  {"kind": "service"}))

    for e in memory.education:
        # "Bachelor of Science in Data Theory from University of California, Los Angeles" in one field
        m = re.match(r"(.+?)\s+in\s+(.+?)\s+(?:from|at)\s+(.+)$", e.qualification.strip())
        if m and not e.field.strip():
            changes = {"qualification": m.group(1).strip(), "field": m.group(2).strip()}
            if not e.institution.strip() or e.institution.strip().lower() in m.group(3).lower():
                changes["institution"] = m.group(3).strip()
            out.append(suggestion("rule", "education", e, "Split the degree into its parts",
                                  "Degree, subject and university each go on their own, so the CV lays them out properly.",
                                  changes))

    for section in ("experience", "projects"):
        for item in getattr(memory, section):
            role = (getattr(item, "role", "") or "").strip()
            org = (getattr(item, "organization", "") or getattr(item, "name", "")).strip()
            repeats = [h for h in item.highlights
                       if len(role) > 8 and role.lower() in h.lower() and (not org or org.split(" (")[0].lower() in h.lower())]
            if repeats:
                out.append(suggestion("rule", section, item, "Remove a bullet that repeats the job title",
                                      "The title and organisation are already above the bullets; use the space for what you did.",
                                      {"highlights": [h for h in item.highlights if h not in repeats]}))

    out += _duplicates(memory)

    seen, groups, changed = set(), [], False
    for g in memory.skills:
        if re.fullmatch(r"soft skills?|interpersonal skills?", g.category.strip(), re.I):
            changed = True  # adjectives, not evidence: committees and recruiters skip them
            continue
        kept, category = [], g.category
        for s in g.skills:
            # A second group typed into the same line: "Data Visualization & Analysis: Matplotlib"
            embedded = re.match(r"([A-Za-z][^:,]{2,40}):\s*(.+)$", s.strip())
            if embedded:
                groups.append({"category": category, "skills": kept})
                kept, category, s = [], embedded.group(1).strip(), embedded.group(2).strip()
                changed = True
            key = s.strip().lower()
            if key and key not in seen:
                seen.add(key)
                kept.append(s.strip())
            else:
                changed = True
        groups.append({"category": category, "skills": kept})
    if changed:
        out.append({**suggestion("rule", "skills", None, "Tidy the skills",
                                 "Each skill once, one group per line, and no 'soft skills' list (show them through what you did).",
                                 {"skills": groups}), "label": "Skills"})
    return out


def _duplicates(memory: Memory) -> list[dict]:
    """The same job, degree, project or award recorded twice: merge into the first."""
    keys = {
        "experience": lambda x: (x.organization.strip().lower(), x.role.strip().lower()),
        "education": lambda x: (x.institution.strip().lower(), x.qualification.strip().lower(), x.field.strip().lower()),
        "projects": lambda x: (x.name.strip().lower(),),
        "achievements": lambda x: (x.title.strip().lower(),),
    }
    out = []
    for section, key in keys.items():
        first: dict = {}
        for item in getattr(memory, section):
            k = key(item)
            if not any(k):
                continue
            if k not in first:
                first[k] = item
                continue
            keep = first[k]
            changes = {}
            for field, info in type(keep).model_fields.items():
                if field == "id":
                    continue
                mine, theirs = getattr(keep, field), getattr(item, field)
                if isinstance(mine, list):
                    merged = mine + [x for x in theirs if x not in mine]
                    if merged != mine:
                        changes[field] = merged
                elif not str(mine).strip() and str(theirs).strip():
                    changes[field] = theirs
            out.append(suggestion("rule", section, keep, "Merge a duplicate",
                                  f"“{label(section, item)}” is recorded twice; this keeps one, with everything from both.",
                                  changes, [item.id]))
    return out


# ---- the AI's suggestions ------------------------------------------------------

class FieldChange(BaseModel):
    item_id: str = Field("", description="The id of the item to change")
    field: str = Field("", description="Which field: role, organization, kind, location, start, end, description, "
                                       "highlights, skills, qualification, field, institution, grade, thesis, name, "
                                       "title, issuer, date")
    new_text: str = Field("", description="The new value, for a text field")
    new_list: list[str] = Field(default_factory=list, description="The new list, for highlights or skills")
    reason: str = Field("", description="Why, in a few plain words")


class MemoryReview(BaseModel):
    changes: list[FieldChange] = Field(default_factory=list)


REVIEW_SYSTEM = """\
You review a person's career memory (the facts their CV is built from) and suggest specific fixes
that make it accurate, clear and ready for a strong CV. The person will accept or reject each one.

Look for, most valuable first:
- entries that mix up two roles or organisations (e.g. one job's highlights filed under another):
  fix what can be fixed field by field, and say in `reason` what they should check;
- vague or weak highlights: rewrite them to start with a strong verb and say what was done, how,
  and the result, keeping EVERY fact, number and name. Never add numbers, tools or results that
  aren't in the memory; where a number would help, write a gap like [how many] instead;
- wrong types: research roles should be kind "research", teaching or tutoring "teaching";
  research projects "research"; reviewing, organising, mentoring or outreach achievements "service";
- a final-year project, capstone or thesis listed as a highlight: move it to the degree's `thesis`;
- the same organisation or degree written different ways; typos; missing obvious details that are
  stated elsewhere in the memory.

Rules: one field per change. For `highlights` and `skills` give the complete new list in
`new_list`; for other fields give `new_text`. Use the exact item ids. At most 15 changes. If the
memory is already good, return few or none. Follow the person's preferences (e.g. UK spelling).
"""


def review_prompt(memory: Memory) -> tuple[str, str]:
    return REVIEW_SYSTEM, f"<memory>\n{memory.model_dump_json(indent=1, exclude_defaults=True)}\n</memory>"


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?%?", text))


def ai_suggestions(memory: Memory, review: MemoryReview) -> list[dict]:
    """Turn the AI's field changes into checked suggestions, one per item."""
    by_id = {x.id: (section, x) for section in SECTIONS for x in getattr(memory, section)}
    known_numbers = _numbers(memory.model_dump_json())
    grouped: dict[str, dict] = {}
    for c in review.changes:
        if c.item_id not in by_id:
            continue
        section, item = by_id[c.item_id]
        fields = type(item).model_fields
        if c.field not in fields or c.field == "id":
            continue
        if c.field in LIST_FIELDS:
            value = [x.strip() for x in c.new_list if x.strip()]
            if not value or value == getattr(item, c.field):
                continue
        else:
            value = c.new_text.strip()
            if value == str(getattr(item, c.field)).strip():
                continue
        entry = grouped.setdefault(c.item_id, suggestion("ai", section, item, "", "", {}))
        entry["changes"][c.field] = value
        if c.reason.strip() and c.reason.strip() not in entry["reason"]:
            entry["reason"] = f"{entry['reason']} {c.reason.strip()}".strip()
    out = []
    for entry in grouped.values():
        text = json.dumps(entry["changes"])
        new = sorted(_numbers(text) - known_numbers)
        if new:
            entry["warnings"].append(f"Contains numbers that aren't in your memory ({', '.join(new[:4])}). "
                                     "Only accept if they're true.")
        fields = ", ".join(entry["changes"])
        entry["summary"] = f"Improve {fields}"
        entry["id"] = _sid("ai", entry["item_id"], entry["changes"])
        out.append(entry)
    return out


# ---- applying the accepted ones ------------------------------------------------

def apply_suggestions(memory: Memory, accepted: list[dict]) -> tuple[Memory, list[str]]:
    """Apply accepted suggestions field by field (so several on one item combine)."""
    m = memory.model_copy(deep=True)
    done: list[str] = []
    removals: set[str] = set()
    for s in accepted:
        section, changes = s.get("section"), s.get("changes") or {}
        if section == "skills" and isinstance(changes.get("skills"), list):
            m.skills = type(m).model_validate({"skills": changes["skills"]}).skills
            done.append("Removed repeated skills")
            continue
        if section not in SECTIONS:
            continue
        items = getattr(m, section)
        index = next((i for i, x in enumerate(items) if x.id == s.get("item_id")), None)
        if index is None:
            continue
        data = items[index].model_dump()
        data.update({k: v for k, v in changes.items() if k in data and k != "id"})
        items[index] = SECTIONS[section].model_validate(data)
        removals |= {str(r) for r in s.get("remove_ids") or [] if r != s.get("item_id")}
        done.append(f"{s.get('summary') or 'Updated'}: {s.get('label') or label(section, items[index])}")
    if removals:
        for section in SECTIONS:
            setattr(m, section, [x for x in getattr(m, section) if x.id not in removals])
    return Memory.model_validate(m.model_dump()), done
