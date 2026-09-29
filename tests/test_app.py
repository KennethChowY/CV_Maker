import io

import pytest

from cv_maker.ai import AIError, ClaudeAI
from cv_maker.app import clean_html, create_app, select_ai
from cv_maker.ollama import OllamaAI
from cv_maker.schema import CVDocument, CVEntry, CVSection, Experience, IngestResult, Memory
from cv_maker.store import Store, ensure_ids


class FakeAI:
    """Stands in for Claude: appends each input as a new job and renders a simple CV."""

    def __init__(self):
        self.ingested = []
        self.targets = []

    def ingest(self, memory, text, attachments=None):
        self.ingested.append((text, [a.filename for a in attachments or []]))
        updated = memory.model_copy(deep=True)
        updated.profile.name = "Ada Lovelace"
        updated.experience.append(Experience(id="exp-new", role=text[:40] or "Imported", organization="Acme"))
        return IngestResult(memory=updated, changes=[f"Added {text[:20]}"], questions=["What was the impact?"])

    def build_cv(self, memory, target=""):
        self.targets.append(target)
        return CVDocument(
            name=memory.profile.name or "Nobody",
            sections=[CVSection(heading="Experience", entries=[
                CVEntry(title=e.role, subtitle=e.organization) for e in memory.experience
            ])],
            advice=["Add numbers"],
        )


@pytest.fixture
def ai():
    return FakeAI()


@pytest.fixture
def client(tmp_path, ai):
    return create_app(tmp_path, ai=ai).test_client()


def test_ingest_updates_memory_and_rebuilds_cv(client, ai):
    res = client.post("/api/ingest", data={"text": "Senior Engineer"})
    assert res.status_code == 200
    body = res.get_json()
    assert body["memory"]["experience"][0]["role"] == "Senior Engineer"
    assert body["changes"] == ["Added Senior Engineer"]
    assert body["questions"] == ["What was the impact?"]
    assert "Senior Engineer" in body["cv_html"]
    assert body["advice"] == ["Add numbers"]
    assert body["history"][0]["input"] == "Senior Engineer"


def test_memory_persists_between_app_instances(tmp_path, ai):
    create_app(tmp_path, ai=ai).test_client().post("/api/ingest", data={"text": "Engineer"})
    body = create_app(tmp_path, ai=ai).test_client().get("/api/state").get_json()
    assert body["memory"]["profile"]["name"] == "Ada Lovelace"
    assert len(body["history"]) == 1


def test_file_upload_is_passed_to_ai(client, ai):
    data = {"text": "", "files": (io.BytesIO(b"%PDF-1.4 fake"), "old_cv.pdf", "application/pdf")}
    res = client.post("/api/ingest", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    assert ai.ingested[-1][1] == ["old_cv.pdf"]


def test_unsupported_upload_is_rejected(client):
    data = {"files": (io.BytesIO(b"PK..."), "cv.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    res = client.post("/api/ingest", data=data, content_type="multipart/form-data")
    assert res.status_code == 400
    assert "PDF" in res.get_json()["error"]


def test_empty_input_is_rejected(client):
    assert client.post("/api/ingest", data={"text": "  "}).status_code == 400


def test_auto_rebuild_can_be_turned_off(client, ai):
    client.post("/api/settings", json={"auto_rebuild": False})
    body = client.post("/api/ingest", data={"text": "Engineer"}).get_json()
    assert body["cv_html"] == ""
    assert ai.targets == []


def test_manual_edits_are_not_overwritten_by_auto_rebuild(client):
    client.post("/api/ingest", data={"text": "Engineer"})
    client.post("/api/cv", json={"html": "<h1>My own wording</h1>"})
    body = client.post("/api/ingest", data={"text": "Manager"}).get_json()
    assert body["cv_html"] == "<h1>My own wording</h1>"
    assert "manual edits" in body["notice"]
    assert body["cv_meta"]["edited"] is True


def test_learning_from_edits_updates_memory_and_clears_flag(client, ai):
    client.post("/api/ingest", data={"text": "Engineer"})
    client.post("/api/cv", json={"html": "<p>edited</p>"})
    body = client.post("/api/cv/learn", json={"text": "Engineer at Acme, 2020-2024"}).get_json()
    assert body["cv_meta"]["edited"] is False
    assert "edited their CV by hand" in ai.ingested[-1][0]


def test_build_uses_and_saves_target(client, ai):
    client.post("/api/ingest", data={"text": "Engineer"})
    body = client.post("/api/build", json={"target": "Staff engineer at a fintech"}).get_json()
    assert ai.targets[-1] == "Staff engineer at a fintech"
    assert body["settings"]["target"] == "Staff engineer at a fintech"
    assert body["cv_meta"]["target"] == "Staff engineer at a fintech"


def test_undo_restores_previous_memory(client):
    client.post("/api/ingest", data={"text": "First"})
    client.post("/api/ingest", data={"text": "Second"})
    body = client.post("/api/undo").get_json()
    assert [e["role"] for e in body["memory"]["experience"]] == ["First"]
    assert "First" in body["cv_html"] and "Second" not in body["cv_html"]
    client.post("/api/undo")
    assert client.post("/api/undo").status_code == 400


def test_manual_memory_edit_is_validated(client):
    assert client.put("/api/memory", json={"experience": "not a list"}).status_code == 400
    body = client.put("/api/memory", json={"profile": {"name": "Grace"}}).get_json()
    assert body["memory"]["profile"]["name"] == "Grace"


def test_without_ai_builds_plain_cv_and_refuses_ingest(tmp_path):
    client = create_app(tmp_path / "data", ai=None).test_client()
    state = client.get("/api/state").get_json()
    assert state["ai_enabled"] is False
    assert state["ai_status"]["ready"] is False
    assert client.post("/api/ingest", data={"text": "hi"}).status_code == 400
    client.put("/api/memory", json={"profile": {"name": "Grace"}, "skills": [{"category": "Languages", "skills": ["COBOL"]}]})
    html = client.get("/api/state").get_json()["cv_html"]
    assert "Grace" in html and "COBOL" in html


def test_auto_backend_uses_free_local_model_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert isinstance(select_ai("auto"), OllamaAI)
    assert select_ai("none") is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert isinstance(select_ai("auto"), ClaudeAI)
    assert isinstance(select_ai("ollama"), OllamaAI)


def test_failed_auto_rebuild_still_saves_memory(tmp_path, ai):
    def broken(*args, **kwargs):
        raise AIError("Can't reach Ollama.")

    ai.build_cv = broken
    client = create_app(tmp_path, ai=ai).test_client()
    body = client.post("/api/ingest", data={"text": "Engineer"}).get_json()
    assert body["memory"]["experience"][0]["role"] == "Engineer"
    assert "couldn't be rebuilt" in body["notice"]


def test_standalone_cv_page_escapes_name(client, ai):
    client.put("/api/memory", json={"profile": {"name": "<b>x</b>"}})
    page = client.get("/cv.html").get_data(as_text=True)
    assert "<title>&lt;b&gt;x&lt;/b&gt; – CV</title>" in page


def test_clean_html_strips_scripts_and_handlers():
    dirty = '<p onclick="x()">Hi</p><script>alert(1)</script><a href="javascript:bad()">l</a>'
    cleaned = clean_html(dirty)
    assert "script" not in cleaned and "onclick" not in cleaned and "javascript" not in cleaned
    assert "<p>Hi</p>" in cleaned


def test_ensure_ids_fills_and_dedupes():
    memory = Memory(experience=[Experience(id="Acme Job"), Experience(id="acme-job"), Experience(id="")])
    ids = [e.id for e in ensure_ids(memory).experience]
    assert ids == ["acme-job", "acme-job-2", "exp-3"]


def test_store_history_is_newest_first(tmp_path):
    store = Store(tmp_path)
    store.save_memory(Memory(), source="input", input_text="one")
    store.save_memory(Memory(), source="input", input_text="two")
    assert [h["input"] for h in store.history()] == ["two", "one"]
