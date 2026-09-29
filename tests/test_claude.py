import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic

from cv_maker.ai import ClaudeAI
from cv_maker.schema import Memory


class FakeAnthropic:
    """Rejects requests with an effort setting (like an older model would), accepts the rest."""

    def __init__(self, reply=None):
        self.bodies = []
        self.reply = reply or {"headline": "Analyst"}
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.bodies.append(body)
                if "effort" in body.get("output_config", {}):
                    code, payload = 400, {"type": "error", "error": {"type": "invalid_request_error",
                                                                     "message": "effort is not supported on this model"}}
                else:
                    out = fake.reply
                    code, payload = 200, {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                                          "content": [{"type": "text", "text": json.dumps(out)}],
                                          "stop_reason": "end_turn", "stop_sequence": None,
                                          "usage": {"input_tokens": 1, "output_tokens": 1}}
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


def test_older_models_are_retried_without_optional_settings(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    fake = FakeAnthropic()
    try:
        client = anthropic.Anthropic(api_key="sk-ant-test", base_url=fake.url, max_retries=0)
        cv = ClaudeAI(client, model="claude-older-model").build_cv(Memory(), "")
    finally:
        fake.server.shutdown()
    assert cv.headline == "Analyst" and len(fake.bodies) == 2
    assert "fallbacks" in fake.bodies[0] and "fallbacks" not in fake.bodies[1]
    assert fake.bodies[1]["model"] == "claude-older-model"


def test_scanned_pdfs_are_sent_for_the_model_to_read(monkeypatch):
    from test_ollama import make_pdf
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    from cv_maker.common import Attachment
    fake = FakeAnthropic(reply={"profile": {"name": "Ada"}, "changes": ["Imported CV"]})
    try:
        client = anthropic.Anthropic(api_key="sk-ant-test", base_url=fake.url, max_retries=0)
        ai = ClaudeAI(client, model="claude-older-model")
        result = ai.ingest(Memory(), "", [Attachment("scan.pdf", "application/pdf", b"%PDF-1.4 no text"),
                                          Attachment("cv.pdf", "application/pdf", make_pdf("Worked at Initech"))])
    finally:
        fake.server.shutdown()
    assert result.memory.profile.name == "Ada" and result.changes == ["Imported CV"]
    content = fake.bodies[-1]["messages"][0]["content"]
    kinds = [c["type"] for c in content]
    assert kinds == ["text", "document", "text", "text"]
    assert "Worked at Initech" in content[2]["text"]
