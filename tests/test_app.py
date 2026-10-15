"""앱 서버(API)와 화면 흐름 테스트. 블로그와 AI는 가짜로 바꿔 끼운다."""

import os
import threading
import time

import pytest
import requests

from autoposter import local_ai
from autoposter.app import __main__ as launcher
from autoposter.app import server as srv
from autoposter.models import Category, Post, PublishResult


class FakePlatform:
    display_name = "가짜"

    def __init__(self, settings):
        self.settings = settings
        self.published = []
        self.logged_in = bool(settings.get("blog_id"))

    def login(self, prompt):
        prompt("열린 브라우저 창에서 로그인을 마친 뒤 Enter를 누르세요", allow_empty=True)
        self.settings["blog_id"] = prompt("블로그 아이디")
        self.logged_in = True

    def is_logged_in(self):
        return self.logged_in

    def get_categories(self):
        return [Category("1", "일상"), Category("2", "국내", parent="여행")]

    def publish(self, post, category, draft=False):
        self.published.append((post, category, draft))
        return PublishResult(url=None if draft else "https://blog/1", draft=draft)

    def close(self):
        pass


def fake_write(**kwargs):
    fake_write.calls.append(kwargs)
    return Post("AI 제목", "<h2>소제목</h2><p>내용</p>", ["a", "b"])


@pytest.fixture
def client(monkeypatch):
    fake_write.calls = []
    monkeypatch.setattr(local_ai, "status", lambda session=None: {"running": True, "installed": True, "models": ["qwen3:8b"]})
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    platforms = []

    def factory(key, cfg):
        platforms.append(FakePlatform(cfg.setdefault(key, {})))
        return platforms[-1]

    app = srv.App(platform_factory=factory, writers={"local": fake_write, "claude": fake_write})
    server = srv.create_server(app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    session = requests.Session()
    session.headers["X-Token"] = app.token

    class Client:
        def get(self, path):
            return session.get(base + path).json()

        def post(self, path, body=None):
            return session.post(base + path, json=body or {})

        def job(self, name, body=None, answers=()):
            answers = list(answers)
            job = self.post(f"/api/jobs/{name}", body).json()
            deadline = time.time() + 10
            while job["state"] in ("running", "input") and time.time() < deadline:
                if job["state"] == "input":
                    self.post(f"/api/jobs/{job['id']}/answer", {"answer": answers.pop(0)})
                time.sleep(0.05)
                job = self.get(f"/api/jobs/{job['id']}")
            return job

    c = Client()
    c.app, c.base, c.platforms = app, base, platforms
    yield c
    server.shutdown()
    app.close()


def test_requires_token(client):
    assert requests.get(client.base + "/api/state").status_code == 403
    assert requests.get(client.base + "/").status_code == 200  # 화면 파일은 토큰 없이


def test_full_flow_login_write_edit_publish(client):
    state = client.get("/api/state")
    assert state["platform"] == "naver" and state["engine"] == "local:qwen3:8b"

    job = client.job("login", answers=["", "tester"])
    assert job["state"] == "done", job
    assert [c["label"] for c in job["result"]] == ["일상", "여행 > 국내"]
    assert client.get("/api/state")["platforms"][1]["target"] == "tester"

    job = client.job("write", {"category": "여행 > 국내", "topic": "단풍", "engine": "local:qwen3:8b", "length": 1500})
    assert job["state"] == "done", job
    post = job["result"]
    assert post["status"] == "draft" and post["category"]["name"] == "국내" and post["platform"] == "naver"
    assert fake_write.calls[0]["model"] == "qwen3:8b" and fake_write.calls[0]["length"] == 1500

    edited = client.post(f"/api/posts/{post['id']}", {"title": "고친 제목", "tags": "#x, y"}).json()
    assert edited["title"] == "고친 제목" and edited["tags"] == ["x", "y"]

    job = client.job("publish", {"post_id": post["id"]})
    assert job["state"] == "done", job
    assert job["result"]["status"] == "published" and job["result"]["url"] == "https://blog/1"
    sent_post, category, draft = client.platforms[-1].published[0]
    assert (sent_post.title, category.name, draft) == ("고친 제목", "국내", False)


def test_claude_needs_key_and_local_needs_model(client, monkeypatch):
    client.app.categories = [Category("1", "일상")]
    job = client.job("write", {"category": "일상", "engine": "claude:claude-sonnet-5-5"})
    assert job["state"] == "error" and "API 키" in job["error"]
    monkeypatch.setattr(local_ai, "status", lambda session=None: {"running": True, "installed": True, "models": []})
    job = client.job("write", {"category": "일상", "engine": "local:qwen3:14b"})
    assert job["state"] == "error" and "내려받기" in job["error"]


def test_publish_rejects_category_from_other_platform(client):
    client.job("login", answers=["", "tester"])
    post = client.job("write", {"category": "일상"})["result"]
    client.post("/api/platform", {"key": "tistory"})
    job = client.job("publish", {"post_id": post["id"]})
    assert job["state"] == "error" and "카테고리를 다시" in job["error"]


def test_import_settings_and_delete(client):
    created = client.post("/api/posts/import", {"name": "후기.md", "content": "# 강릉 후기\n\n좋았다"}).json()
    assert created["title"] == "강릉 후기" and created["engine"] == "file" and created["category"] is None
    state = client.post("/api/settings", {"anthropic_api_key": "sk-test"}).json()
    assert state["has_api_key"] and os.environ["ANTHROPIC_API_KEY"] == "sk-test"
    client.post("/api/settings", {"anthropic_api_key": ""})
    assert "ANTHROPIC_API_KEY" not in os.environ
    client.post(f"/api/posts/{created['id']}/delete")
    assert client.get("/api/state")["posts"] == []


def test_launcher_stops_after_window_closes(monkeypatch):
    monkeypatch.setenv("AUTOPOSTER_NO_WINDOW", "1")
    monkeypatch.setattr(launcher, "BYE_GRACE", 0.3)
    monkeypatch.setattr(launcher, "App", lambda: client_app)
    client_app = srv.App(platform_factory=lambda k, cfg: FakePlatform({}))
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("code", launcher.main()))
    thread.start()
    client_app.closing_at = time.time()  # 창의 pagehide 신호와 같은 효과
    thread.join(10)
    assert result.get("code") == 0
