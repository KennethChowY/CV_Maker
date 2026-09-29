"""The helpers beyond the CV itself: truth check, strengthening questions, interview prep,
follow-up emails, LinkedIn text, job ads from links, countries, translation and the photo."""

import io
from datetime import date, timedelta

import pytest

from cv_maker.app import create_app
from cv_maker.assistant import basic_questions
from cv_maker.jobads import fetch_job_ad, page_text
from cv_maker.common import AIError
from cv_maker.render import with_photo
from cv_maker.schema import Experience, Memory
from test_app import FakeAI

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


@pytest.fixture
def ai():
    return FakeAI()


@pytest.fixture
def client(tmp_path, ai):
    c = create_app(tmp_path, ai=ai).test_client()
    c.post("/api/ingest", data={"text": "Engineer"})
    return c


def new_app(client, **extra):
    return client.post("/api/versions", json={"company": "HSBC", "role": "Analyst", "target": "Data job", **extra})


def test_truth_check_returns_real_issues_only(client, ai):
    res = client.post("/api/truth-check", json={"text": "Led 40 people"})
    assert res.status_code == 200
    assert res.get_json()["issues"] == [{"quote": "Led 40 people", "problem": "The memory says you led 4.",
                                         "suggestion": "Led 4 people"}]
    assert ai.checked == "Led 40 people"
    assert client.post("/api/truth-check", json={"text": " "}).status_code == 400


def test_strengthen_questions_with_and_without_ai(client, tmp_path):
    body = client.post("/api/strengthen").get_json()
    assert body == {"questions": [{"entry_id": "", "about": "Acme", "question": "How many users?"}], "ai": True}

    memory = Memory(experience=[Experience(id="e1", role="Analyst", organization="Acme",
                                           highlights=["Cut costs by 20%", "Built dashboards"])])
    questions = basic_questions(memory).questions
    assert questions[0].about == "Analyst at Acme"
    assert "Built dashboards" in questions[0].question
    assert any("start" in q.question for q in questions) and any("tools" in q.question for q in questions)
    no_ai = create_app(tmp_path / "plain", ai=None).test_client()
    assert no_ai.post("/api/strengthen").get_json()["ai"] is False


def test_interview_prep_is_saved_per_application(client, ai):
    assert client.post("/api/interview").status_code == 400  # general CV
    new_app(client)
    body = client.post("/api/interview").get_json()
    assert body["prep"]["questions"][0]["question"] == "Why HSBC?"
    assert body["prep"]["ask_them"] == ["What does success look like?"]
    assert ai.prep_args == ("Data job", "HSBC", "Analyst")
    assert client.get("/api/state").get_json()["prep"]["questions"]
    client.post("/api/versions/active", json={"id": "general"})
    assert client.get("/api/state").get_json()["prep"] == {}


def test_follow_up_email_uses_days_since_applying(client, ai):
    vid = new_app(client).get_json()["active"]["id"]
    applied = (date.today() - timedelta(days=9)).isoformat()
    client.patch(f"/api/versions/{vid}", json={"status": "Applied", "applied": applied, "notes": "Met Jo"})
    body = client.post(f"/api/versions/{vid}/follow-up").get_json()
    assert body == {"subject": "Analyst application", "body": "Dear HSBC, it's been 9 days."}
    assert ai.follow_up_args == ("HSBC", "Analyst", 9, "Met Jo")
    client.patch(f"/api/versions/{vid}", json={"followed_up": date.today().isoformat()})
    assert client.get("/api/state").get_json()["versions"][0]["followed_up"] == date.today().isoformat()
    assert client.post("/api/versions/nope/follow-up").status_code == 404


def test_linkedin_text_is_saved(client):
    body = client.post("/api/linkedin").get_json()
    assert body["linkedin"]["headline"] == "Data scientist"
    assert body["linkedin"]["experience"][0]["company"] == "Acme"


def test_helpers_need_an_ai(tmp_path):
    c = create_app(tmp_path, ai=None).test_client()
    for url in ("/api/truth-check", "/api/linkedin"):
        res = c.post(url, json={"text": "x"})
        assert res.status_code == 502 and "AI" in res.get_json()["error"]


def test_country_conventions_and_translation(client, ai):
    assert new_app(client, region="mars").status_code == 400
    body = new_app(client, region="hk", language="zh-Hant").get_json()
    assert body["active"]["region"] == "hk" and body["active"]["language"] == "zh-Hant"
    assert "Hong Kong" in ai.conventions
    assert ai.translated_to == "zh-Hant"
    assert "工作經驗" in body["cv_html"]
    # The translation is reused while the English CV hasn't changed.
    ai.translated_to = None
    client.post("/api/build")
    assert ai.translated_to is None
    # The general CV's country is a setting.
    client.post("/api/versions/active", json={"id": "general"})
    client.post("/api/settings", json={"region": "us"})
    client.post("/api/build")
    assert "American" in ai.conventions
    assert client.post("/api/settings", json={"language": "xx"}).status_code == 400


def test_photo_is_shown_only_where_expected(client):
    res = client.post("/api/photo", data={"photo": (io.BytesIO(JPEG), "me.jpg")}, content_type="multipart/form-data")
    body = res.get_json()
    assert body["has_photo"] and body["settings"]["show_photo"]
    assert 'class="cv-photo" src="data:image/jpeg;base64,' in body["cv_html"]
    # US and UK CVs leave the photo out.
    body = client.post("/api/settings", json={"region": "uk"}).get_json()
    assert "cv-photo" not in body["cv_html"]
    body = client.post("/api/settings", json={"region": "hk"}).get_json()
    assert "cv-photo" in body["cv_html"]
    # Hand edits are kept when the photo is switched off.
    client.post("/api/cv", json={"html": body["cv_html"].replace("Engineer", "Chief Engineer")})
    body = client.post("/api/settings", json={"show_photo": False}).get_json()
    assert "cv-photo" not in body["cv_html"] and "Chief Engineer" in body["cv_html"]
    body = client.post("/api/photo", data={"photo": (io.BytesIO(PNG), "me.png")}, content_type="multipart/form-data").get_json()
    assert "data:image/png" in body["cv_html"]
    body = client.delete("/api/photo").get_json()
    assert not body["has_photo"] and "cv-photo" not in body["cv_html"]
    bad = client.post("/api/photo", data={"photo": (io.BytesIO(b"GIF89a"), "me.gif")}, content_type="multipart/form-data")
    assert bad.status_code == 400


def test_with_photo_swaps_and_removes():
    html = '<header class="cv-header">\n  <div class="cv-header-text">'
    once = with_photo(html, "data:image/png;base64,AA")
    assert once.count("cv-photo") == 1 and "has-photo" in once
    assert with_photo(once, "data:image/png;base64,BB").count("cv-photo") == 1
    assert with_photo(once, None) == html


def test_job_ad_from_a_link(client, tmp_path):
    app = create_app(tmp_path / "x", ai=None)
    app.config["FETCH_JOB_AD"] = lambda url: f"Job ad from {url}"
    c = app.test_client()
    assert c.post("/api/job-ad", json={"url": "https://jobs.example/1"}).get_json() == {"text": "Job ad from https://jobs.example/1"}
    for url in ("file:///etc/passwd", "http://127.0.0.1:5000/api/state", "http://localhost/", "http://10.0.0.1/", "nonsense"):
        with pytest.raises(AIError):
            fetch_job_ad(url)


def test_job_ad_text_prefers_structured_data():
    description = "<p>We need a data scientist.</p>" + "<p>Python, SQL and statistics.</p>" * 10
    html = ('<html><head><title>Jobs</title><script type="application/ld+json">'
            '{"@type": "JobPosting", "title": "Data Scientist", "hiringOrganization": {"name": "HSBC"}, '
            f'"description": "{description}"}}</script></head><body><nav>Menu</nav><main>Other</main></body></html>')
    text = page_text(html)
    assert text.startswith("Data Scientist\n\nHSBC") and "Menu" not in text and "Python, SQL" in text
    plain = page_text("<html><head><title>Analyst</title></head><body><nav>Menu</nav><main><h1>Analyst</h1>"
                      "<p>Do analysis</p></main><script>x()</script></body></html>")
    assert "Menu" not in plain and "x()" not in plain and "Do analysis" in plain
