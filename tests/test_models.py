import time

import pytest
from test_ollama import FakeOllama

from cv_maker.app import create_app


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CV_MAKER_AI", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    server = FakeOllama([], models=("qwen3:8b",))
    monkeypatch.setenv("OLLAMA_HOST", server.url)
    yield server
    server.close()


def test_catalog_lists_recommended_and_installed_models(fake, tmp_path):
    fake.models.append("mistral:7b")
    client = create_app(tmp_path / "data").test_client()
    cat = client.get("/api/models").get_json()
    assert cat["choice"] == {"backend": "ollama", "model": "qwen3:4b"}
    assert cat["ollama_running"] is True and cat["api_key"]["set"] is False
    by_name = {m["name"]: m for m in cat["local"]}
    assert by_name["qwen3:8b"]["installed"] and not by_name["qwen3:4b"]["installed"]
    assert by_name["mistral:7b"]["installed"] and not by_name["mistral:7b"]["recommended"]


def test_download_then_choose_a_model_and_it_is_remembered(fake, tmp_path):
    client = create_app(tmp_path / "data").test_client()
    client.post("/api/models/download", json={"model": "qwen3:4b"})
    for _ in range(50):
        cat = client.get("/api/models").get_json()
        if cat["downloads"]["qwen3:4b"]["state"] != "downloading":
            break
        time.sleep(0.05)
    assert cat["downloads"]["qwen3:4b"]["state"] == "done"
    assert next(m for m in cat["local"] if m["name"] == "qwen3:4b")["installed"]

    state = client.post("/api/models/choose", json={"backend": "ollama", "model": "qwen3:4b"}).get_json()
    assert "qwen3:4b" in state["ai_status"]["label"] and state["ai_status"]["ready"] is True

    again = create_app(tmp_path / "data").test_client()
    assert again.get("/api/models").get_json()["choice"] == {"backend": "ollama", "model": "qwen3:4b"}


def test_claude_cannot_be_chosen_without_a_key(fake, tmp_path):
    client = create_app(tmp_path / "data").test_client()
    res = client.post("/api/models/choose", json={"backend": "claude"})
    assert res.status_code >= 400 and "API key" in res.get_json()["error"]


def test_choosing_no_ai_gives_plain_layout(fake, tmp_path):
    client = create_app(tmp_path / "data").test_client()
    state = client.post("/api/models/choose", json={"backend": "none"}).get_json()
    assert state["ai_enabled"] is False
    assert client.post("/api/ingest", data={"text": "hi"}).status_code == 400
    client.put("/api/memory", json={"profile": {"name": "Grace"}})
    assert "Grace" in client.get("/api/state").get_json()["cv_html"]


def test_settings_endpoint_cannot_bypass_model_checks(fake, tmp_path):
    client = create_app(tmp_path / "data").test_client()
    client.post("/api/settings", json={"ai_backend": "claude"})
    assert client.get("/api/models").get_json()["choice"]["backend"] == "ollama"


def test_ollama_not_running_is_reported(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:1")
    client = create_app(tmp_path / "data", backend="ollama").test_client()
    assert client.get("/api/models").get_json()["ollama_running"] is False
    assert "Ollama isn't running" in client.get("/api/state").get_json()["ai_status"]["message"]


def test_api_key_is_saved_privately_and_never_sent_to_the_page(fake, tmp_path):
    app = create_app(tmp_path / "data")
    checked = []

    def verify(provider, key, base_url):
        checked.append((provider, key))
        return ["gpt-writer-2", "gpt-writer-1"]

    app.config["VERIFY_KEY"] = verify
    client = app.test_client()
    key = "sk-proj-" + "x" * 40 + "WXYZ"

    assert client.post("/api/models/key", json={"key": "short"}).status_code >= 400
    state = client.post("/api/models/key", json={"key": key})
    assert state.status_code == 200 and checked == [("openai", key)]
    assert key not in state.get_data(as_text=True)
    assert state.get_json()["ai_status"]["label"] == "gpt-writer-2 (API key)"

    cat = client.get("/api/models")
    assert key not in cat.get_data(as_text=True)
    api = cat.get_json()["api_key"]
    assert (api["set"], api["hint"], api["provider_name"], api["model"]) == (True, "…WXYZ", "OpenAI", "gpt-writer-2")
    assert api["models"] == ["gpt-writer-2", "gpt-writer-1"]
    assert cat.get_json()["choice"] == {"backend": "api", "model": "gpt-writer-2"}
    secrets = tmp_path / "data" / "secrets.json"
    assert oct(secrets.stat().st_mode & 0o777) == "0o600"

    body = client.post("/api/models/choose", json={"backend": "api", "model": "gpt-writer-1"}).get_json()
    assert body["ai_status"]["label"] == "gpt-writer-1 (API key)"

    client.delete("/api/models/key")
    assert not secrets.exists()
    cat = client.get("/api/models").get_json()
    assert cat["api_key"]["set"] is False and cat["choice"]["backend"] == "ollama"


def test_provider_is_detected_or_chosen(fake, tmp_path):
    app = create_app(tmp_path / "data")
    seen = []
    app.config["VERIFY_KEY"] = lambda provider, key, base_url: seen.append((provider, base_url)) or ["m1"]
    client = app.test_client()
    for key in ("sk-ant-api03-" + "a" * 30, "AIza" + "b" * 35, "gsk_" + "c" * 40, "sk-or-v1-" + "d" * 40):
        assert client.post("/api/models/key", json={"key": key}).status_code == 200
    assert [p for p, _ in seen] == ["anthropic", "google", "groq", "openrouter"]
    # A key with no recognisable prefix needs the service to be picked.
    res = client.post("/api/models/key", json={"key": "0123456789abcdef0123456789"})
    assert res.status_code >= 400 and "Pick the service" in res.get_json()["error"]
    res = client.post("/api/models/key", json={"key": "0123456789abcdef0123456789", "provider": "other"})
    assert "API address" in res.get_json()["error"]
    ok = client.post("/api/models/key", json={"key": "0123456789abcdef0123456789", "provider": "other",
                                              "base_url": "https://llm.example.com/v1/"})
    assert ok.status_code == 200 and seen[-1] == ("other", "https://llm.example.com/v1")


def test_anthropic_key_uses_the_anthropic_client(fake, tmp_path):
    app = create_app(tmp_path / "data")
    app.config["VERIFY_KEY"] = lambda provider, key, base_url: ["claude-opus-5-5"]
    client = app.test_client()
    body = client.post("/api/models/key", json={"key": "sk-ant-api03-" + "z" * 40}).get_json()
    assert body["ai_status"]["label"] == "claude-opus-5-5 (API key)"


def test_rejected_key_is_not_saved(fake, tmp_path):
    from cv_maker.ai import AIError

    def reject(provider, key, base_url):
        raise AIError("OpenAI didn't accept the API key.")

    app = create_app(tmp_path / "data")
    app.config["VERIFY_KEY"] = reject
    res = app.test_client().post("/api/models/key", json={"key": "sk-proj-" + "y" * 40})
    assert res.status_code >= 400 and "didn't accept" in res.get_json()["error"]
    assert not (tmp_path / "data" / "secrets.json").exists()


def test_key_saved_by_an_earlier_version_still_works(fake, tmp_path):
    import json
    data = tmp_path / "data"
    data.mkdir()
    (data / "secrets.json").write_text(json.dumps({"anthropic_api_key": "sk-ant-api03-" + "q" * 40}))
    (data / "settings.json").write_text(json.dumps({"ai_backend": "claude"}))
    cat = create_app(data).test_client().get("/api/models").get_json()
    assert cat["api_key"]["provider"] == "anthropic" and cat["choice"]["backend"] == "api"
