import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from autoposter import local_ai


class FakeOllama(BaseHTTPRequestHandler):
    models = ["qwen3:8b"]
    replies: list = []
    requests: list = []

    def log_message(self, *a):
        pass

    def _json(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/version":
            self._json(200, {"version": "0.12.0"})
        elif self.path == "/api/tags":
            self._json(200, {"models": [{"name": m} for m in self.models]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.requests.append((self.path, body))
        if self.path == "/api/pull":
            self.send_response(200)
            self.end_headers()
            for event in [
                {"status": "pulling manifest"},
                {"status": "pulling abc", "total": 200, "completed": 50},
                {"status": "pulling abc", "total": 200, "completed": 200},
                {"status": "success"},
            ]:
                self.wfile.write((json.dumps(event) + "\n").encode())
        elif self.path == "/api/chat":
            if body["model"] not in self.models:
                return self._json(404, {"error": "model not found"})
            self._json(200, {"message": {"content": FakeOllama.replies.pop(0)}})


@pytest.fixture
def ollama(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(local_ai, "OLLAMA_URL", f"http://127.0.0.1:{server.server_port}")
    FakeOllama.requests = []
    FakeOllama.replies = []
    yield FakeOllama
    server.shutdown()


def test_status_and_pull_progress(ollama):
    st = local_ai.status()
    assert st["running"] and st["models"] == ["qwen3:8b"]
    assert local_ai.has_model("qwen3:8b", st["models"])
    progress = []
    local_ai.pull("qwen3:14b", lambda f, text: progress.append((f, text)))
    assert progress[1] == (0.25, "내려받는 중 25%")
    assert progress[-1][1] == "완료"


def test_status_when_not_running(monkeypatch):
    monkeypatch.setattr(local_ai, "OLLAMA_URL", "http://127.0.0.1:9")
    assert local_ai.status()["running"] is False


def test_write_retries_bad_format_and_converts_markdown(ollama):
    ollama.replies = [
        "죄송합니다 형식을 못 맞췄어요",
        "<think>생각</think>" + json.dumps({"title": "가을 산책", "html": "## 소제목\n\n본문 **강조**", "tags": "#가을, 산책"}),
    ]
    post = local_ai.write_post_local("일상", topic="가을")
    assert post.title == "가을 산책"
    assert "<h2>소제목</h2>" in post.html and "<strong>강조</strong>" in post.html
    assert post.tags == ["가을", "산책"]
    path, body = ollama.requests[-1]
    assert path == "/api/chat" and body["think"] is False and body["format"]["required"] == ["title", "html", "tags"]


def test_missing_model_message(ollama):
    with pytest.raises(local_ai.LocalAIError, match="내려받아"):
        local_ai.write_post_local("일상", model="qwen3:14b")


def test_ignores_system_proxy(ollama, monkeypatch):
    # PC에 프록시가 설정돼 있어도 내 PC의 Ollama에는 바로 접속해야 한다
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    assert local_ai.status()["running"] is True


def test_not_running_reports_reason(monkeypatch):
    monkeypatch.setattr(local_ai, "OLLAMA_URL", "http://127.0.0.1:9")
    assert "ConnectionError" in local_ai.status()["reason"]
