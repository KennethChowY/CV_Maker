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
S2_API = "https://api.semanticscholar.org/graph/v1"
CROSSREF_API = "https://api.crossref.org"
MAX_PDF_BYTES = 20 * 1024 * 1024
EXCERPT_CHARS = 2500
_AUTHOR_ID = re.compile(r"^A\d{3,15}$")


def _get(path: str, params: dict, base: str = API, body: dict | None = None) -> dict:
    url = f"{base}{path}?{urllib.parse.urlencode(params)}" if params else f"{base}{path}"
    headers = {"User-Agent": "CV Maker (finding a professor's research)"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
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


def _abstract(inverted: dict | None, limit: int = 1500) -> str:
    """OpenAlex stores abstracts as {word: [positions]}; put the words back in order."""
    if not inverted:
        return ""
    slots = sorted((pos, word) for word, positions in inverted.items() for pos in positions)
    text = " ".join(word for _, word in slots)
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _work(w: dict) -> dict:
    source = ((w.get("primary_location") or {}).get("source") or {}).get("display_name", "")
    best = w.get("best_oa_location") or {}
    abstract = _abstract(w.get("abstract_inverted_index"))
    return {"id": _short_id(w.get("id", "")), "title": w.get("display_name") or w.get("title") or "",
            "year": w.get("publication_year") or "", "venue": source or "", "citations": w.get("cited_by_count", 0),
            "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
            "abstract": abstract, "abstract_source": "OpenAlex" if abstract else "", "tldr": "",
            "pdf_url": best.get("pdf_url") or "",
            "oa_url": best.get("landing_page_url") or (w.get("open_access") or {}).get("oa_url") or ""}


def research_profile(author_id: str) -> dict:
    """Their topics, recent papers and most-cited papers."""
    if not _AUTHOR_ID.match(author_id or ""):
        raise AIError("Pick one of the people found.")
    author = _get(f"/authors/{author_id}", {})
    fields = ("id,display_name,title,publication_year,primary_location,abstract_inverted_index,cited_by_count,doi,"
              "best_oa_location,open_access")
    recent = _get("/works", {"filter": f"author.id:{author_id}", "sort": "publication_date:desc",
                             "per_page": 8, "select": fields}).get("results") or []
    cited = _get("/works", {"filter": f"author.id:{author_id}", "sort": "cited_by_count:desc",
                            "per_page": 4, "select": fields}).get("results") or []
    recent_works = [_work(w) for w in recent if w.get("display_name") or w.get("title")]
    titles = {w["title"] for w in recent_works}
    profile = {
        "id": author_id,
        "name": author.get("display_name", ""),
        "institutions": _institutions(author)[:3],
        "topics": _topics(author, 8),
        "recent": recent_works,
        "cited": [w for w in (_work(x) for x in cited) if w["title"] and w["title"] not in titles],
        "source": f"https://openalex.org/{author_id}",
    }
    fill_abstracts(profile["recent"] + profile["cited"])
    return profile


def _clean_markup(text: str) -> str:
    text = re.sub(r"<(jats:)?title>.*?</(jats:)?title>", " ", text or "", flags=re.S)  # the "Abstract" heading
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def fill_abstracts(works: list[dict]) -> None:
    """Many publishers don't share abstracts with OpenAlex. Fill the gaps from Semantic Scholar
    (which also has a one-sentence summary and open-access PDF links), then from Crossref."""
    with_doi = [w for w in works if w.get("doi")]
    if with_doi:
        try:
            found = _get("/paper/batch", {"fields": "abstract,tldr,openAccessPdf"}, base=S2_API,
                         body={"ids": [f"DOI:{w['doi']}" for w in with_doi]})
        except AIError:
            found = []
        for w, paper in zip(with_doi, found if isinstance(found, list) else []):
            if not paper:
                continue
            if not w["abstract"] and paper.get("abstract"):
                w["abstract"], w["abstract_source"] = _abstract_cut(paper["abstract"]), "Semantic Scholar"
            w["tldr"] = ((paper.get("tldr") or {}).get("text") or "").strip()
            if not w["pdf_url"]:
                w["pdf_url"] = (paper.get("openAccessPdf") or {}).get("url") or ""
    for w in [w for w in with_doi if not w["abstract"]][:6]:
        try:
            message = _get(f"/works/{urllib.parse.quote(w['doi'])}", {}, base=CROSSREF_API).get("message") or {}
        except AIError:
            continue
        if message.get("abstract"):
            w["abstract"], w["abstract_source"] = _abstract_cut(_clean_markup(message["abstract"])), "Crossref"


def _abstract_cut(text: str, limit: int = 1500) -> str:
    text = re.sub(r"^\s*abstract\s*[:.]\s*", "", text.strip(), flags=re.I)  # a leading "Abstract:" label
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def all_works(profile: dict) -> list[dict]:
    return (profile.get("recent") or []) + (profile.get("cited") or [])


def find_work(profile: dict, work_id: str) -> dict | None:
    return next((w for w in all_works(profile) if w.get("id") == work_id), None)


_INTRO = re.compile(r"\n\s*(?:\d{1,2}\.?|I\.)?\s*(introduction|background)\s*\n", re.I)
_CLOSING = re.compile(r"\n\s*(?:\d{1,2}\.?|[IVX]{1,4}\.)?\s*(conclusions?|concluding remarks|discussion"
                      r"|summary and outlook|limitations and future work)\s*\n", re.I)
_REFERENCES = re.compile(r"\n\s*(references|bibliography|acknowledge?ments)\s*\n", re.I)


def key_passages(text: str) -> dict:
    """The introduction and the conclusion (or discussion): what the paper set out to do, what it
    found, and what the authors say is still open."""
    text = "\n" + re.sub(r"[ \t]+", " ", text) + "\n"
    refs = _REFERENCES.search(text, len(text) // 3)
    body = text[:refs.start()] if refs else text
    intro = _INTRO.search(body)
    closings = list(_CLOSING.finditer(body))
    start = intro.end() if intro else 0
    introduction = body[start:start + EXCERPT_CHARS]
    if closings:
        c = closings[-1]
        conclusion = body[c.end():c.end() + EXCERPT_CHARS]
    else:
        conclusion = body[-EXCERPT_CHARS:]
    tidy = lambda t: re.sub(r"\s*\n\s*", " ", t).strip()  # noqa: E731
    return {"introduction": tidy(introduction), "conclusion": tidy(conclusion)}


def read_paper(work: dict) -> dict:
    """Download an open-access copy and pull out its key passages. {} when there's no free copy
    or it can't be read (paywalled papers stay title-and-abstract only)."""
    from .backend import pdf_to_text
    from .jobads import download, page_text

    for url in dict.fromkeys(u for u in (work.get("pdf_url"), work.get("oa_url")) if u):
        try:
            data, kind = download(url, MAX_PDF_BYTES, timeout=30, accept="application/pdf,text/html")
        except AIError:
            continue
        try:
            if data[:5] == b"%PDF-" or "pdf" in kind:
                text = pdf_to_text(data)
            elif "html" in kind:
                text = page_text(data.decode("utf-8", errors="replace"))
            else:
                continue
        except AIError:
            continue
        if len(text) > 3000:  # a real article, not a landing page or a login wall
            return {**key_passages(text), "url": url}
    return {}


def paper_text(work: dict, passages: dict | None = None) -> str:
    """One paper, with whatever is known about it, for the AI."""
    lines = [f"Title: {work['title']}", f"Year: {work.get('year', '')}"]
    if work.get("venue"):
        lines.append(f"Published in: {work['venue']}")
    if work.get("tldr"):
        lines.append(f"One-sentence summary: {work['tldr']}")
    if work.get("abstract"):
        lines.append(f"Abstract: {work['abstract']}")
    if passages:
        lines.append(f"From the introduction: {passages.get('introduction', '')}")
        lines.append(f"From the conclusion or discussion: {passages.get('conclusion', '')}")
    return "\n".join(lines)


def profile_text(p: dict) -> str:
    """The research profile as plain text for the AI."""
    lines = [f"Professor: {p.get('name', '')}", f"Institution: {', '.join(p.get('institutions', [])) or 'unknown'}"]
    if p.get("topics"):
        lines.append(f"Research topics: {', '.join(p['topics'])}")
    for heading, works in (("Recent papers", p.get("recent", [])), ("Most-cited papers", p.get("cited", []))):
        if works:
            lines.append(f"\n{heading}:")
            for w in works:
                lines.append(f"- [{w.get('id', '')}] {w['title']} ({w['year']}{', ' + w['venue'] if w['venue'] else ''})")
                if w.get("abstract"):
                    lines.append(f"  Abstract: {w['abstract']}")
    return "\n".join(lines)
