import pytest
from test_app import FakeAI

from cv_maker.app import create_app


@pytest.fixture
def ai():
    return FakeAI()


@pytest.fixture
def client(tmp_path, ai):
    c = create_app(tmp_path, ai=ai).test_client()
    c.post("/api/ingest", data={"text": "Engineer"})
    return c


def test_new_application_gets_its_own_tailored_cv(client, ai):
    general_html = client.get("/api/state").get_json()["cv_html"]
    body = client.post("/api/versions", json={"company": "HSBC", "role": "Data Scientist",
                                              "target": "Python, SQL, stakeholder reporting"}).get_json()
    assert body["active"]["name"] == "Data Scientist – HSBC" and body["active"]["status"] == "Draft"
    assert body["target"] == "Python, SQL, stakeholder reporting"
    assert ai.targets[-1] == "Python, SQL, stakeholder reporting"
    assert len(body["versions"]) == 1

    # Editing the application's CV leaves the general CV alone.
    client.post("/api/cv", json={"html": "<p>tailored for HSBC</p>"})
    general = client.post("/api/versions/active", json={"id": "general"}).get_json()
    assert general["cv_html"] == general_html and general["target"] == ""
    back = client.post("/api/versions/active", json={"id": body["active"]["id"]}).get_json()
    assert back["cv_html"] == "<p>tailored for HSBC</p>"


def test_rebuild_uses_the_open_versions_job_ad(client, ai):
    vid = client.post("/api/versions", json={"company": "Acme", "target": "old ad"}).get_json()["active"]["id"]
    client.post("/api/build", json={"target": "new ad"})
    assert ai.targets[-1] == "new ad"
    client.post("/api/versions/active", json={"id": "general"})
    client.post("/api/build", json={})
    assert ai.targets[-1] == ""
    assert client.post("/api/versions/active", json={"id": vid}).get_json()["target"] == "new ad"


def test_tracking_status_and_notes(client):
    vid = client.post("/api/versions", json={"company": "Acme"}).get_json()["active"]["id"]
    body = client.patch(f"/api/versions/{vid}", json={"status": "Applied", "applied": "2026-09-30", "notes": "Emailed Sam"}).get_json()
    v = body["versions"][0]
    assert (v["status"], v["applied"], v["notes"]) == ("Applied", "2026-09-30", "Emailed Sam")
    assert client.patch(f"/api/versions/{vid}", json={"status": "Hired!!"}).status_code == 400


def test_sent_applications_are_not_rebuilt_automatically(client, ai):
    vid = client.post("/api/versions", json={"company": "Acme"}).get_json()["active"]["id"]
    client.patch(f"/api/versions/{vid}", json={"status": "Applied"})
    builds = len(ai.targets)
    body = client.post("/api/ingest", data={"text": "Manager"}).get_json()
    assert len(ai.targets) == builds and "kept as it was sent" in body["notice"]


def test_delete_application_returns_to_general(client):
    vid = client.post("/api/versions", json={"company": "Acme"}).get_json()["active"]["id"]
    body = client.delete(f"/api/versions/{vid}").get_json()
    assert body["active"]["id"] == "general" and body["versions"] == []
    assert client.delete("/api/versions/general").status_code == 404
    assert client.post("/api/versions/active", json={"id": "../../etc"}).status_code == 404


def test_application_needs_company_or_role(client):
    assert client.post("/api/versions", json={"target": "ad"}).status_code == 400


def test_cover_letter_is_written_per_application(client, ai):
    vid = client.post("/api/versions", json={"company": "HSBC", "role": "Analyst", "target": "Python, SQL"}).get_json()["active"]["id"]
    body = client.post("/api/letter", json={"tone": "warm"}).get_json()
    assert ai.letter_args == ("Python, SQL", "HSBC", "Analyst", "warm")
    html = body["letter"]["html"]
    assert "Hiring Team<br>HSBC" in html and "Re: Analyst" in html and "At Acme I built X for 3 teams." in html
    assert body["letter"]["tone"] == "warm" and body["letter"]["edited"] is False

    client.post("/api/letter/edits", json={"html": html.replace("3 teams", "four teams")})
    general = client.post("/api/versions/active", json={"id": "general"}).get_json()
    assert general["letter"] == {}  # the general CV has its own (empty) letter
    back = client.post("/api/versions/active", json={"id": vid}).get_json()
    assert "four teams" in back["letter"]["html"] and back["letter"]["edited"] is True

    res = client.get("/api/export/letter.docx")
    assert res.status_code == 200 and "Cover%20Letter%20%E2%80%93%20HSBC.docx" in res.headers["Content-Disposition"]
    import io
    import docx
    text = "\n".join(p.text for p in docx.Document(io.BytesIO(res.data)).paragraphs)
    assert "Ada Lovelace" in text and "four teams" in text and "Dear Hiring Team," in text


def test_letter_rejects_unknown_tone_and_needs_ai(client, tmp_path):
    assert client.post("/api/letter", json={"tone": "sarcastic"}).status_code == 400
    assert client.get("/api/export/letter.pdf").status_code == 400  # nothing written yet
    no_ai = create_app(tmp_path / "other", ai=None).test_client()
    assert no_ai.post("/api/letter", json={}).status_code == 400


def test_edits_are_saved_to_the_cv_they_were_made_on(client):
    vid = client.post("/api/versions", json={"company": "Acme"}).get_json()["active"]["id"]
    client.post("/api/versions/active", json={"id": "general"})
    # A save that was still pending when the person switched to the general CV:
    client.post("/api/cv", json={"html": "<p>edit made on Acme</p>", "version": vid})
    assert "edit made on Acme" not in client.get("/api/state").get_json()["cv_html"]
    assert client.post("/api/versions/active", json={"id": vid}).get_json()["cv_html"] == "<p>edit made on Acme</p>"
    assert client.post("/api/cv", json={"html": "x", "version": "gone-123"}).status_code == 404
