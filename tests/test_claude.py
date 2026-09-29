import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic

from cv_maker.ai import ClaudeAI
from cv_maker.schema import Memory


class FakeAnthropic:
    """Rejects requests with an effort setting (like an older model would), accepts the rest."""

    def __init__(self):
        self.bodies = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.bodies.append(body)
                if "effort" in body.get("output_config", {}):
                    code, payload = 400, {"type": "error", "error": {"type": "invalid_request_error",
                                                                     "message": "effort is not supported on this model"}}
                else:
                    out = {"name": "Ada", "sections": []}
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
    assert cv.name == "Ada" and len(fake.bodies) == 2
    assert "fallbacks" in fake.bodies[0] and "fallbacks" not in fake.bodies[1]
    assert fake.bodies[1]["model"] == "claude-older-model"
