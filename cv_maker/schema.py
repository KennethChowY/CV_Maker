"""Data models for the memory (everything known about you) and the generated CV.

The memory is the long-lived source of truth: it holds every fact ever given,
including things that don't make it onto the current CV. The CV is a curated,
polished view of the memory, rebuilt whenever the memory changes.
"""

from __future__ import annotations

from typing import Any, get_origin

from pydantic import BaseModel as _PydanticModel
from pydantic import Field, model_validator


class BaseModel(_PydanticModel):
    """Tolerates the small slips local AI models make: null instead of a value,
    a number where text was expected, or a single string instead of a list."""

    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        fixed = {}
        for key, value in data.items():
            if value is None:
                continue  # fall back to the field's default
            field = cls.model_fields.get(key)
            if field is not None:
                if get_origin(field.annotation) is list and isinstance(value, str):
                    value = [value] if value.strip() else []
                elif field.annotation is str and isinstance(value, (int, float)) and not isinstance(value, bool):
                    value = str(value)
            fixed[key] = value
        return fixed


class Link(BaseModel):
    label: str = Field("", description="e.g. LinkedIn, GitHub, Portfolio")
    url: str = ""


class Profile(BaseModel):
    name: str = ""
    headline: str = Field("", description="Short professional title, e.g. 'Backend Engineer'")
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[Link] = Field(default_factory=list)


class Experience(BaseModel):
    id: str = Field("", description="Stable unique id, e.g. 'exp-acme-2021'. Never change an existing id.")
    kind: str = Field("work", description="work | internship | research | teaching | volunteering | freelance | other")
    organization: str = ""
    role: str = ""
    location: str = ""
    start: str = Field("", description="As precise as known, e.g. '2021-03' or '2021'")
    end: str = Field("", description="'Present' if ongoing, otherwise like start")
    supervisor: str = Field("", description="PI or supervisor for research roles, e.g. 'Prof. Jane Wong'")
    description: str = ""
    highlights: list[str] = Field(
        default_factory=list,
        description="Concrete achievements and responsibilities, with numbers where known",
    )
    skills: list[str] = Field(default_factory=list)


class Education(BaseModel):
    id: str = ""
    institution: str = ""
    qualification: str = Field("", description="e.g. 'BSc', 'A-Levels', 'MBA'")
    field: str = ""
    location: str = ""
    start: str = ""
    end: str = ""
    grade: str = ""
    thesis: str = Field("", description="Final-year project, capstone or thesis: its title, and supervisor if known")
    highlights: list[str] = Field(default_factory=list)


class Project(BaseModel):
    id: str = ""
    kind: str = Field("personal", description="research | personal | course | other")
    name: str = ""
    role: str = ""
    link: str = ""
    start: str = ""
    end: str = ""
    description: str = ""
    highlights: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class SkillGroup(BaseModel):
    category: str = Field("", description="e.g. 'Languages', 'Frameworks', 'Tools', 'Soft skills'")
    skills: list[str] = Field(default_factory=list)


class Achievement(BaseModel):
    """Certifications, awards, publications, talks and similar one-line items."""

    id: str = ""
    kind: str = Field("award", description="certification | award | publication | talk | service | other")
    title: str = ""
    issuer: str = Field("", description="Issuer, or for papers and talks the journal, conference or venue")
    date: str = ""
    authors: str = Field("", description="For papers and talks: the author list as in a citation, e.g. 'Chow K, Wong J'")
    status: str = Field("", description="For papers: published | accepted | under review | in preparation")
    link: str = Field("", description="DOI or link")
    description: str = ""


class Referee(BaseModel):
    id: str = ""
    name: str = Field("", description="e.g. 'Prof. Jane Wong'")
    title: str = Field("", description="e.g. 'Associate Professor, JC School of Public Health'")
    organization: str = ""
    email: str = ""
    phone: str = ""
    relationship: str = Field("", description="How they know the person, e.g. 'Supervisor, C-FIST Lab (2025–)'")


class Memory(BaseModel):
    profile: Profile = Field(default_factory=Profile)
    summary: str = Field("", description="The person's own professional summary or pitch, if given")
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[SkillGroup] = Field(default_factory=list)
    achievements: list[Achievement] = Field(default_factory=list)
    research_interests: list[str] = Field(default_factory=list, description="Research interests, short keywords")
    referees: list[Referee] = Field(default_factory=list, description="People who will write references")
    languages: list[str] = Field(default_factory=list, description="Spoken languages with level")
    interests: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(
        default_factory=list,
        description="Standing instructions for how the CV should be written, e.g. 'UK spelling', 'max 1 page'",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Other facts worth remembering that don't fit elsewhere (career goals, target roles, etc.)",
    )


class IngestResult(BaseModel):
    memory: Memory = Field(description="The complete updated memory, including everything unchanged")
    changes: list[str] = Field(
        default_factory=list, description="Short human-readable list of what was added, changed or removed"
    )
    questions: list[str] = Field(
        default_factory=list,
        description="Follow-up questions whose answers would make the CV stronger (missing dates, metrics...)",
    )


class CVEntry(BaseModel):
    title: str = Field("", description="Main line, e.g. role or degree")
    subtitle: str = Field("", description="Organization or institution")
    location: str = ""
    dates: str = Field("", description="Display form, e.g. 'Mar 2021 – Present'")
    description: str = ""
    bullets: list[str] = Field(default_factory=list)


class CVSection(BaseModel):
    heading: str = ""
    entries: list[CVEntry] = Field(default_factory=list)
    items: list[str] = Field(
        default_factory=list,
        description="For list-style sections such as skills: each item is one display line",
    )


class CVDocument(BaseModel):
    name: str = ""
    headline: str = ""
    contact: list[str] = Field(default_factory=list, description="Email, phone, location as display strings")
    links: list[Link] = Field(default_factory=list)
    summary: str = ""
    summary_title: str = Field("", description="Heading for the summary; empty means 'Summary'")
    sections: list[CVSection] = Field(default_factory=list)
    advice: list[str] = Field(
        default_factory=list,
        description="Tips for the user to strengthen the CV (not shown on the CV itself)",
    )
