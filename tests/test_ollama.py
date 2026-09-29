import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cv_maker.ai import AIError, Attachment
from cv_maker.ollama import MemoryUpdate, OllamaAI, apply_update, pdf_to_text
from cv_maker.schema import Experience, Link, Memory, Profile, SkillGroup


def make_pdf(text: str) -> bytes:
    """Build a minimal one-page PDF containing `text`."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


class FakeOllama:
    """A tiny HTTP server that speaks enough of the Ollama API for the tests."""

    def __init__(self, replies, models=("qwen3:8b",), status=200):
        self.replies = list(replies)
        self.requests = []
        self.models = list(models)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code, payload):
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(200, {"models": [{"name": m, "size": 2_500_000_000} for m in fake.models]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                if self.path == "/api/pull":
                    lines = [{"status": "pulling manifest"},
                             {"status": "pulling abc", "total": 100, "completed": 50},
                             {"status": "success"}]
                    data = b"".join(json.dumps(x).encode() + b"\n" for x in lines)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    fake.models.append(body["model"])
                    return
                if status != 200:
                    self._send(status, {"error": f"model '{body['model']}' not found"})
                    return
                reply = fake.replies.pop(0)
                content = reply if isinstance(reply, str) else json.dumps(reply)
                self._send(200, {"message": {"role": "assistant", "content": content}, "done_reason": "stop"})

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def memory():
    return Memory(
        profile=Profile(name="Ada", email="ada@example.com", links=[Link(label="GitHub", url="github.com/ada")]),
        experience=[
            Experience(id="exp-acme", organization="Acme", role="Engineer", start="2020", highlights=["Built X"]),
            Experience(id="exp-old", organization="OldCo", role="Intern", start="2018", end="2019"),
        ],
        skills=[SkillGroup(category="Languages", skills=["Python"])],
        languages=["English"],
    )


def test_apply_update_merges_without_losing_anything(memory):
    update = MemoryUpdate(
        profile=Profile(name="", phone="123", links=[Link(label="GitHub", url="github.com/ada"),
                                                      Link(label="Site", url="ada.dev")]),
        upsert_experience=[
            Experience(id="exp-acme", organization="Acme", role="Engineer", start="2020", end="2024",
                       highlights=["Built X", "Cut costs 30%"]),
            Experience(id="exp-new", organization="Globex", role="Senior Engineer", start="2024", end="Present"),
        ],
        skills=[SkillGroup(category="languages", skills=["python", "Go"]), SkillGroup(category="Tools", skills=["Git"])],
        add_languages=["english", "French"],
        changes=["Promoted"],
    )
    m = apply_update(memory, update)
    assert m.profile.name == "Ada" and m.profile.email == "ada@example.com" and m.profile.phone == "123"
    assert [link.url for link in m.profile.links] == ["github.com/ada", "ada.dev"]
    assert [e.id for e in m.experience] == ["exp-acme", "exp-old", "exp-new"]
    assert m.experience[0].end == "2024" and len(m.experience[0].highlights) == 2
    assert m.skills[0].skills == ["Python", "Go"] and m.skills[1].category == "Tools"
    assert m.languages == ["English", "French"]
    assert len(memory.experience) == 2  # original untouched


def test_apply_update_matches_items_when_model_forgets_the_id(memory):
    update = MemoryUpdate(profile=Profile(), upsert_experience=[
        Experience(id="something-else", organization="acme ", role="Engineer", end="2024"),
    ])
    m = apply_update(memory, update)
    assert len(m.experience) == 2
    assert m.experience[0].id == "exp-acme" and m.experience[0].end == "2024"


def test_apply_update_only_removes_listed_ids(memory):
    m = apply_update(memory, MemoryUpdate(profile=Profile(), remove_ids=["exp-old"]))
    assert [e.id for e in m.experience] == ["exp-acme"]


def test_ingest_sends_schema_and_merges_reply(memory):
    reply = MemoryUpdate(
        profile=Profile(),
        upsert_experience=[Experience(id="exp-new", organization="Globex", role="Lead")],
        changes=["Added Globex"],
        questions=["When did you start?"],
    ).model_dump()
    fake = FakeOllama([reply])
    try:
        result = OllamaAI(host=fake.url).ingest(memory, "I joined Globex as Lead")
    finally:
        fake.close()
    assert [e.organization for e in result.memory.experience] == ["Acme", "OldCo", "Globex"]
    assert result.changes == ["Added Globex"] and result.questions == ["When did you start?"]
    req = fake.requests[0]
    assert req["model"] == "qwen3:8b" and req["stream"] is False
    assert req["format"]["title"] == "MemoryUpdate"
    assert req["options"]["num_ctx"] >= 8192
    assert "I joined Globex as Lead" in req["messages"][1]["content"]


def test_invalid_output_is_retried(memory):
    fake = FakeOllama(["not json", "still not json", {"headline": "Engineer"}])
    try:
        cv = OllamaAI(host=fake.url).build_cv(memory, "Data role")
    finally:
        fake.close()
    assert cv.name == "Ada" and cv.headline == "Engineer" and len(fake.requests) == 3
    assert "Data role" in fake.requests[0]["messages"][1]["content"]


def test_gives_up_with_a_clear_message_after_repeated_bad_output(memory):
    fake = FakeOllama(["x", "y", "z"])
    try:
        with pytest.raises(AIError, match="couldn't read"):
            OllamaAI(host=fake.url).build_cv(memory)
    finally:
        fake.close()


def test_build_cv_uses_model_wording_in_app_layout(memory):
    wording = {
        "headline": "Software Engineer",
        "summary": "Engineer who builds things.",
        "items": [
            {"id": "exp-acme", "include": True, "bullets": ["Built X used by 3 teams"]},
            {"id": "exp-old", "include": False, "bullets": []},
            {"id": "made-up", "include": True, "bullets": ["Invented item"]},
        ],
        "skills": ["Programming: Python"],
        "advice": ["Add numbers"],
    }
    # Wrapped in a code fence, as some models do.
    fake = FakeOllama(["```json\n" + json.dumps(wording) + "\n```"])
    try:
        cv = OllamaAI(host=fake.url).build_cv(memory)
    finally:
        fake.close()
    assert fake.requests[0]["format"]["title"] == "CVWording"
    assert cv.headline == "Software Engineer" and cv.summary == "Engineer who builds things."
    experience = next(s for s in cv.sections if s.heading == "Experience")
    assert [e.subtitle for e in experience.entries] == ["Acme"]  # OldCo excluded, made-up id ignored
    assert experience.entries[0].bullets == ["Built X used by 3 teams"]
    assert next(s for s in cv.sections if s.heading == "Skills").items == ["Programming: Python"]
    assert cv.advice == ["Add numbers"]


def test_model_cannot_hide_everything(memory):
    wording = {"items": [{"id": "exp-acme", "include": False}, {"id": "exp-old", "include": False}]}
    fake = FakeOllama([wording])
    try:
        cv = OllamaAI(host=fake.url).build_cv(memory)
    finally:
        fake.close()
    assert len(next(s for s in cv.sections if s.heading == "Experience").entries) == 2


def test_lenient_parsing_of_sloppy_model_output():
    update = MemoryUpdate.model_validate({
        "profile": {"name": None, "phone": 12345},
        "upsert_experience": [{"id": "e1", "role": "Dev", "highlights": "Built one thing", "end": None}],
        "changes": "Added a job",
    })
    assert update.profile.phone == "12345" and update.profile.name == ""
    assert update.upsert_experience[0].highlights == ["Built one thing"]
    assert update.changes == ["Added a job"]


def test_pull_reports_progress():
    fake = FakeOllama([], models=())
    events = []
    try:
        OllamaAI(host=fake.url).pull("qwen3:4b", events.append)
    finally:
        fake.close()
    assert events[1] == {"status": "pulling abc", "total": 100, "completed": 50}
    assert events[-1]["status"] == "success"
    assert fake.requests[0] == {"model": "qwen3:4b", "stream": True}


def test_pdf_attachment_is_converted_to_text(memory):
    reply = MemoryUpdate(profile=Profile(), changes=["Imported"]).model_dump()
    fake = FakeOllama([reply])
    try:
        OllamaAI(host=fake.url).ingest(memory, "", [Attachment("cv.pdf", "application/pdf", make_pdf("Worked at Initech"))])
    finally:
        fake.close()
    assert "Worked at Initech" in fake.requests[0]["messages"][1]["content"]


def test_pdf_to_text_reports_bad_files():
    assert "Hello" in pdf_to_text(make_pdf("Hello"))
    with pytest.raises(AIError):
        pdf_to_text(b"not a pdf")


def test_helpful_errors_when_ollama_missing_or_model_not_pulled(memory):
    with pytest.raises(AIError, match="Start the Ollama app"):
        OllamaAI(host="http://127.0.0.1:1").build_cv(memory)
    assert OllamaAI(host="http://127.0.0.1:1").status()["ready"] is False

    fake = FakeOllama([], models=("llama3.2:latest",), status=404)
    try:
        ai = OllamaAI(host=fake.url)
        assert "isn't downloaded" in ai.status()["message"]
        with pytest.raises(AIError, match="qwen3:8b' isn't downloaded"):
            ai.build_cv(memory)
    finally:
        fake.close()


def test_status_ready_when_model_present():
    fake = FakeOllama([], models=("qwen3:8b",))
    try:
        status = OllamaAI(host=fake.url).status()
    finally:
        fake.close()
    assert status["ready"] is True and status["local"] is True and "free" in status["label"]
