import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from cv_maker.ai import AIError
from cv_maker.api_models import OpenAICompatibleAI
from cv_maker.backend import MemoryUpdate
from cv_maker.providers import default_model, detect_provider
from cv_maker.schema import Experience, Memory, Profile


class FakeOpenAI:
    """Just enough of the OpenAI chat API for the tests."""

    def __init__(self, replies, schema_ok=True, status=200):
        self.replies, self.requests = list(replies), []
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
                fake.requests.append(("GET", self.path, dict(self.headers), None))
                if status != 200:
                    return self._send(status, {"error": {"message": "Incorrect API key provided"}})
                self._send(200, {"data": [
                    {"id": "text-embedding-3-small", "created": 3}, {"id": "writer-large", "created": 2},
                    {"id": "models/writer-small", "created": 1}, {"id": "whisper-1", "created": 4}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(("POST", self.path, dict(self.headers), body))
                if body["response_format"]["type"] == "json_schema" and not schema_ok:
                    return self._send(400, {"error": {"message": "response_format json_schema not supported"}})
                reply = fake.replies.pop(0)
                self._send(200, {"choices": [{"finish_reason": "stop", "message": {
                    "role": "assistant", "content": reply if isinstance(reply, str) else json.dumps(reply)}}]})

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()


@pytest.fixture(autouse=True)
def no_proxy(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(var, raising=False)


def test_models_are_listed_newest_first_without_non_writing_models():
    fake = FakeOpenAI([])
    try:
        models = OpenAICompatibleAI(fake.url, "sk-test").list_models()
    finally:
        fake.close()
    assert models == ["writer-large", "writer-small"]
    assert fake.requests[0][2]["Authorization"] == "Bearer sk-test"


def test_rejected_key_gives_a_clear_message():
    fake = FakeOpenAI([], status=401)
    try:
        with pytest.raises(AIError, match="didn't accept the API key"):
            OpenAICompatibleAI(fake.url, "bad", provider="openai").list_models()
    finally:
        fake.close()


def test_memory_update_uses_json_schema_output():
    reply = MemoryUpdate(profile=Profile(), upsert_experience=[Experience(id="e1", role="Analyst")],
                         changes=["Added analyst role"]).model_dump()
    fake = FakeOpenAI([reply])
    try:
        result = OpenAICompatibleAI(fake.url, "k", model="writer-large").ingest(Memory(), "I became an analyst")
    finally:
        fake.close()
    assert result.memory.experience[0].role == "Analyst" and result.changes == ["Added analyst role"]
    body = fake.requests[0][3]
    assert body["model"] == "writer-large" and body["response_format"]["type"] == "json_schema"


def test_falls_back_to_plain_json_when_schemas_are_not_supported():
    fake = FakeOpenAI(["```json\n{\"suggestions\": [\"Led X\", \"Built Y\"]}\n```"], schema_ok=False)
    try:
        ai = OpenAICompatibleAI(fake.url, "k", model="writer-small")
        out = ai.improve_bullet(Memory(), "Did X", "stronger")
    finally:
        fake.close()
    assert out == ["Led X", "Built Y"]
    fallback = fake.requests[-1][3]
    assert fallback["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in fallback["messages"][0]["content"]


def test_needs_a_model():
    with pytest.raises(AIError, match="Pick a model"):
        OpenAICompatibleAI("http://127.0.0.1:1", "k").improve_bullet(Memory(), "x", "stronger")


def test_provider_detection_and_default_model():
    assert detect_provider("sk-ant-api03-x") == "anthropic"
    assert detect_provider("sk-or-v1-x") == "openrouter"
    assert detect_provider("sk-proj-x") == "openai"
    assert detect_provider("AIzaSyX") == "google"
    assert detect_provider("gsk_x") == "groq"
    assert detect_provider("xai-x") == "xai"
    assert detect_provider("abc") is None
    assert default_model("openai", ["gpt-new-preview", "gpt-new-nano", "gpt-new"]) == "gpt-new"
    assert default_model("anthropic", ["claude-x", "claude-opus-5-5"]) == "claude-opus-5-5"
