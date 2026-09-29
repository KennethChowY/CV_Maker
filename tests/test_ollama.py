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
                self._send(200, {"models": [{"name": m} for m in models]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
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


def test_invalid_output_is_retried_once(memory):
    fake = FakeOllama(["not json", {"name": "Ada", "sections": []}])
    try:
        cv = OllamaAI(host=fake.url).build_cv(memory, "Data role")
    finally:
        fake.close()
    assert cv.name == "Ada" and len(fake.requests) == 2
    assert "Data role" in fake.requests[0]["messages"][1]["content"]


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
        assert "ollama pull qwen3:8b" in ai.status()["message"]
        with pytest.raises(AIError, match="ollama pull qwen3:8b"):
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
