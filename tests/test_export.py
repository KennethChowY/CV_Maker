import io
from pathlib import Path

import docx
import pytest
from test_app import FakeAI

from cv_maker.app import create_app
from cv_maker.export import find_browser

CHROMIUM = next(iter(sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))), None) \
    if Path("/opt/pw-browsers").exists() else None


@pytest.fixture
def client(tmp_path):
    c = create_app(tmp_path, ai=FakeAI()).test_client()
    c.post("/api/ingest", data={"text": "Engineer"})
    return c


def test_word_download_follows_the_cv_page(client):
    client.post("/api/cv", json={"html": (
        "<header class='cv-header'><h1 class='cv-name'>Ada Lovelace</h1><p class='cv-contact'><span>ada@x.com</span></p></header>"
        "<section class='cv-section' data-section='experience'><h2>Experience</h2>"
        "<div class='cv-entry'><div class='cv-entry-head'><span class='cv-entry-title'>Engineer</span>"
        "<span class='cv-entry-dates'>2020 – Present</span></div>"
        "<div class='cv-entry-sub'><span class='cv-entry-org'>Acme</span><span class='cv-entry-loc'>London</span></div>"
        "<ul><li>Built X for 3 teams</li></ul></div></section>"
        "<section class='cv-section' data-section='skills'><h2>Skills</h2><ul class='cv-items'><li><strong>Languages:</strong> Python</li></ul></section>"
        "<section class='cv-section' data-section='interests' hidden><h2>Interests</h2><ul class='cv-items'><li>Chess</li></ul></section>"
    )})
    res = client.get("/api/export/cv.docx")
    assert res.status_code == 200 and "Ada%20Lovelace%20CV.docx" in res.headers["Content-Disposition"]
    text = [p.text for p in docx.Document(io.BytesIO(res.data)).paragraphs]
    assert text[0] == "Ada Lovelace"
    assert "Engineer\t2020 – Present" in text and "Acme\tLondon" in text
    assert "Built X for 3 teams" in text and "Languages: Python" in text
    assert not any("Chess" in t for t in text)  # hidden sections stay hidden


def test_pdf_reports_when_no_browser_is_available(client, monkeypatch):
    monkeypatch.setenv("CV_MAKER_BROWSER", "/nonexistent/chrome")
    assert find_browser() is None
    res = client.get("/api/export/cv.pdf")
    assert res.status_code == 501 and "No Chrome" in res.get_json()["error"]


@pytest.mark.skipif(CHROMIUM is None, reason="no Chromium available to print with")
def test_pdf_download_is_a_real_pdf_without_browser_headers(client, monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    monkeypatch.setenv("CV_MAKER_BROWSER", str(CHROMIUM))
    res = client.get("/api/export/cv.pdf?scale=0.9")
    assert res.status_code == 200 and res.data.startswith(b"%PDF")
    text = "".join(page.get_text() for page in pymupdf.open(stream=res.data, filetype="pdf"))
    assert "Engineer" in text and "file://" not in text


def test_application_downloads_are_named_after_the_company(client):
    client.post("/api/versions", json={"company": "HSBC", "role": "Analyst"})
    res = client.get("/api/export/cv.docx")
    assert "CV%20%E2%80%93%20HSBC.docx" in res.headers["Content-Disposition"]
