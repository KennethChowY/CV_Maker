"""Look up a professor's research in OpenAlex (openalex.org), a free, open index of
academic papers, so a first email to a potential PhD supervisor can mention their actual work.
No API key needed, and it works whichever AI model is chosen."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .common import AIError

API = "https://api.openalex.org"
_AUTHOR_ID = re.compile(r"^A\d{3,15}$")


def _get(path: str, params: dict) -> dict:
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "CV Maker (finding a professor's research)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise AIError(f"The paper index (OpenAlex) answered with an error ({e.code}). Try again in a minute.") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
        raise AIError("Couldn't reach the paper index (OpenAlex). Check your internet connection.") from e


def _short_id(openalex_id: str) -> str:
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]


def _institutions(a: dict) -> list[str]:
    names = [i.get("display_name", "") for i in a.get("last_known_institutions") or []]
    names += [(x.get("institution") or {}).get("display_name", "") for x in a.get("affiliations") or []]
    seen, out = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _topics(a: dict, limit: int = 5) -> list[str]:
    topics = [t.get("display_name", "") for t in a.get("topics") or []]
    if not topics:  # older records
        topics = [c.get("display_name", "") for c in a.get("x_concepts") or [] if c.get("level", 1) >= 1]
    return [t for t in topics if t][:limit]


_SMALL = {"of", "the", "and", "at", "de", "in", "for"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in _SMALL | {"university"}}


def _acronym(name: str) -> str:
    """'The Chinese University of Hong Kong' -> 'CUHK'; 'University of California, Los Angeles' -> 'UCLA'."""
    words = [w for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in _SMALL]
    return "".join(w[0] for w in words).upper()


def _matches(institution: str, names: list[str]) -> int:
    """How well the university typed matches where the person works."""
    typed = institution.strip()
    if not typed:
        return 0
    if typed.isupper() and any(_acronym(n) == typed for n in names):
        return 10
    return len(_words(typed) & _words(" ".join(names)))


def find_authors(name: str, institution: str = "") -> list[dict]:
    """People in the index with this name, best match for the university first."""
    name = name.strip()
    name = re.sub(r"^(prof(essor)?|dr|mr|ms|mrs)\.?\s+", "", name, flags=re.I)
    if len(name) < 3:
        raise AIError("Type the professor's full name.")
    data = _get("/authors", {"search": name, "per_page": 10})
    people = []
    for a in data.get("results") or []:
        insts = _institutions(a)
        people.append({
            "id": _short_id(a.get("id", "")),
            "name": a.get("display_name", ""),
            "institutions": insts[:3],
            "works": a.get("works_count", 0),
            "citations": a.get("cited_by_count", 0),
            "topics": _topics(a),
            "match": _matches(institution, insts),
        })
    people.sort(key=lambda p: (-p["match"], -p["works"]))
    return [p for p in people if _AUTHOR_ID.match(p["id"])][:6]


def _abstract(inverted: dict | None, limit: int = 700) -> str:
    """OpenAlex stores abstracts as {word: [positions]}; put the words back in order."""
    if not inverted:
        return ""
    slots = sorted((pos, word) for word, positions in inverted.items() for pos in positions)
    text = " ".join(word for _, word in slots)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _work(w: dict) -> dict:
    source = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
    return {"title": w.get("display_name") or w.get("title") or "", "year": w.get("publication_year") or "",
            "venue": source or "", "citations": w.get("cited_by_count", 0), "doi": w.get("doi") or "",
            "abstract": _abstract(w.get("abstract_inverted_index"))}


def research_profile(author_id: str) -> dict:
    """Their topics, recent papers and most-cited papers."""
    if not _AUTHOR_ID.match(author_id or ""):
        raise AIError("Pick one of the people found.")
    author = _get(f"/authors/{author_id}", {})
    fields = "display_name,title,publication_year,primary_location,abstract_inverted_index,cited_by_count,doi"
    recent = _get("/works", {"filter": f"author.id:{author_id}", "sort": "publication_date:desc",
                             "per_page": 8, "select": fields}).get("results") or []
    cited = _get("/works", {"filter": f"author.id:{author_id}", "sort": "cited_by_count:desc",
                            "per_page": 4, "select": fields}).get("results") or []
    recent_works = [_work(w) for w in recent if w.get("display_name") or w.get("title")]
    titles = {w["title"] for w in recent_works}
    return {
        "id": author_id,
        "name": author.get("display_name", ""),
        "institutions": _institutions(author)[:3],
        "topics": _topics(author, 8),
        "recent": recent_works,
        "cited": [w for w in (_work(x) for x in cited) if w["title"] and w["title"] not in titles],
        "source": f"https://openalex.org/{author_id}",
    }


def profile_text(p: dict) -> str:
    """The research profile as plain text for the AI."""
    lines = [f"Professor: {p.get('name', '')}", f"Institution: {', '.join(p.get('institutions', [])) or 'unknown'}"]
    if p.get("topics"):
        lines.append(f"Research topics: {', '.join(p['topics'])}")
    for heading, works in (("Recent papers", p.get("recent", [])), ("Most-cited papers", p.get("cited", []))):
        if works:
            lines.append(f"\n{heading}:")
            for w in works:
                lines.append(f"- {w['title']} ({w['year']}{', ' + w['venue'] if w['venue'] else ''})")
                if w.get("abstract"):
                    lines.append(f"  Abstract: {w['abstract']}")
    return "\n".join(lines)
