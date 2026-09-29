"""Read a job ad from a link, so it doesn't have to be copied and pasted."""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .common import AIError

MAX_BYTES = 3 * 1024 * 1024
MAX_CHARS = 15000
PASTE_INSTEAD = "Copy the job ad from the page and paste it in instead."


def _public_host(host: str) -> bool:
    """Only fetch from the internet, never from this computer or the local network."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _clean(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out, blank = [], False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


def _from_structured_data(soup: BeautifulSoup) -> str:
    """Most job sites describe the posting in JSON-LD (schema.org JobPosting); it's the cleanest source."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            if isinstance(item, dict) and "JobPosting" in str(item.get("@type", "")):
                parts = [item.get("title", "")]
                org = item.get("hiringOrganization")
                if isinstance(org, dict) and org.get("name"):
                    parts.append(org["name"])
                description = BeautifulSoup(str(item.get("description", "")), "html.parser").get_text("\n")
                parts.append(description)
                return _clean("\n\n".join(p for p in parts if p))
    return ""


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    structured = _from_structured_data(soup)
    if len(structured) > 200:
        return structured
    for tag in soup(["script", "style", "noscript", "svg", "nav", "header", "footer", "form", "iframe"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    title = soup.title.get_text(strip=True) if soup.title else ""
    text = _clean(main.get_text("\n"))
    return _clean(f"{title}\n\n{text}") if title and title not in text[:200] else text


def download(url: str, max_bytes: int = MAX_BYTES, timeout: int = 20, accept: str = "*/*") -> tuple[bytes, str]:
    """Fetch a public web address: (content, content type). Never this computer or the local network."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not _public_host(parsed.hostname):
        raise AIError("That link doesn't point to a public website.")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (CV Maker)", "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            if not _public_host(urlparse(res.geturl()).hostname or ""):
                raise AIError("That link doesn't point to a public website.")
            return res.read(max_bytes), res.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raise AIError(f"The site refused the request ({e.code}).") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise AIError("Couldn't open that link.") from e


def fetch_job_ad(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AIError("That doesn't look like a web link. It should start with https://")
    if not _public_host(parsed.hostname):
        raise AIError("That link doesn't point to a public website.")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (CV Maker; reading a job ad)",
                                               "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            if not _public_host(urlparse(res.geturl()).hostname or ""):  # redirected somewhere private
                raise AIError("That link doesn't point to a public website.")
            if "html" not in res.headers.get("Content-Type", "html"):
                raise AIError(f"That link isn't a web page. {PASTE_INSTEAD}")
            raw = res.read(MAX_BYTES)
            charset = res.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as e:
        raise AIError(f"The site refused the request ({e.code}); some job sites need you to be logged in. "
                      f"{PASTE_INSTEAD}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise AIError(f"Couldn't open that link. {PASTE_INSTEAD}") from e
    text = page_text(raw.decode(charset, errors="replace"))
    if len(text) < 200:
        raise AIError(f"That page didn't show the job ad's text (some sites only show it after you log in). "
                      f"{PASTE_INSTEAD}")
    return text[:MAX_CHARS]
