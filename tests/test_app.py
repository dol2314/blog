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


def test_launcher_keeps_running_while_window_connected(monkeypatch):
    monkeypatch.setenv("AUTOPOSTER_NO_WINDOW", "1")
    monkeypatch.setenv("AUTOPOSTER_PRINT_URL", "1")
    monkeypatch.setattr(launcher, "CLOSE_GRACE", 1.0)
    app = srv.App(platform_factory=lambda k, cfg: FakePlatform({}))
    monkeypatch.setattr(launcher, "App", lambda: app)
    result = {}
    urls = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: urls.append(a[0]))
    thread = threading.Thread(target=lambda: result.setdefault("code", launcher.main()))
    thread.start()
    while not urls:
        time.sleep(0.05)
    base, query = urls[0].split("/?")

    # 앱 창의 연결이 열려 있는 동안에는 꺼지지 않는다
    stream = requests.get(f"{base}/api/events?{query}", stream=True, timeout=10)
    assert stream.status_code == 200
    time.sleep(2.5)
    assert thread.is_alive() and app.clients == 1
    # 다른 주소의 토큰 없는 연결은 거절
    assert requests.get(f"{base}/api/events?t=wrong", timeout=5).status_code == 403

    # 창을 닫으면(연결이 끊기면) 잠시 뒤 종료
    stream.close()
    thread.join(15)
    assert result.get("code") == 0


def test_style_references_refine_factcheck_and_fix(client, monkeypatch):
    app = client.app
    client.job("login", answers=["", "tester"])
    app.fetch = lambda url: ("기관 자료", "개정 시행일은 3월 1일입니다")

    # 글투 학습 → 저장
    app.style_analyzer = lambda engine, text, fetch: {"guide": "- 해요체", "examples": ["좋아요!"], "samples": 2}
    job = client.job("style", {"samples": "내 글", "engine": "local:qwen3:8b"})
    assert job["state"] == "done" and job["result"]["guide"] == "- 해요체"
    state = client.get("/api/state")
    assert state["style"]["enabled"] is True and state["style"]["examples"] == ["좋아요!"]

    # 다듬기 켜고 참고 자료(글 + 주소)와 함께 글쓰기
    client.post("/api/settings", {"refine_enabled": True})
    app.refiner = lambda engine, post, style: Post(post.title + " (다듬음)", post.html, post.tags)
    job = client.job("write", {"category": "일상", "references": "직접 쓴 메모\nhttps://www.korea.kr/x"})
    assert job["state"] == "done", job
    call = fake_write.calls[-1]
    assert call["style"]["guide"] == "- 해요체"
    assert "직접 쓴 메모" in call["references"] and "개정 시행일은 3월 1일" in call["references"]
    post = job["result"]
    assert post["title"].endswith("(다듬음)") and post["styled"] is True

    # 글투 끄면 다음 글에는 반영 안 됨
    client.post("/api/settings", {"style": {"guide": "- 해요체", "enabled": False}})
    client.job("write", {"category": "일상"})
    assert fake_write.calls[-1]["style"] is None

    # 팩트체크 → 고쳐 쓰기 → 되돌리기
    seen = {}

    def fake_check(engine, p, refs, progress):
        seen["refs"] = refs
        progress("확인 중 (1/1)", 0.0)
        return {"checked_at": 1, "engine": engine, "results": [
            {"claim": "시행일은 4월 1일", "query": "", "verdict": "틀림", "correct": "3월 1일",
             "reason": "", "source_url": "https://www.korea.kr/x", "checked": []}]}

    app.fact_checker = fake_check
    job = client.job("factcheck", {"post_id": post["id"]})
    assert job["state"] == "done" and job["result"]["factcheck"]["results"][0]["verdict"] == "틀림"
    assert "https://www.korea.kr/x" in seen["refs"]

    monkeypatch.setattr("autoposter.factcheck.llm.generate_json",
                        lambda *a, **k: {"title": "고친 제목", "html": "<p>시행일은 3월 1일</p>", "tags": []})
    job = client.job("fix", {"post_id": post["id"]})
    assert job["state"] == "done", job
    fixed = job["result"]
    assert "3월 1일" in fixed["html"] and "참고한 공식 자료" in fixed["html"] and fixed["factcheck"]["fixed_at"]
    assert fixed["previous"]["title"] == post["title"]

    restored = client.post(f"/api/posts/{post['id']}/restore").json()
    assert restored["title"] == post["title"] and restored["previous"] is None


def test_review_jobs_need_a_ready_engine(client, monkeypatch):
    post = client.post("/api/posts/import", {"name": "a.md", "content": "# 제목\n\n본문"}).json()
    monkeypatch.setattr(local_ai, "status", lambda session=None: {"running": False, "installed": True, "models": []})
    job = client.job("factcheck", {"post_id": post["id"], "engine": "local:qwen3:8b"})
    assert job["state"] == "error" and "꺼져" in job["error"]
    job = client.job("fix", {"post_id": post["id"]})
    assert job["state"] == "error" and "먼저 팩트체크" in job["error"]


def test_auto_factcheck_after_writing(client):
    client.job("login", answers=["", "tester"])
    client.app.fact_checker = lambda engine, post, refs, progress: {
        "checked_at": 1, "engine": engine,
        "results": [{"claim": "c", "query": "", "verdict": "틀림", "correct": "x", "reason": "", "source_url": "", "checked": []}],
    }
    assert client.post("/api/settings", {"factcheck_auto": True}).json()["factcheck_auto"] is True
    job = client.job("write", {"category": "일상"})
    assert job["state"] == "done" and job["result"]["factcheck"]["results"][0]["verdict"] == "틀림"

    # 팩트체크가 실패해도 글은 저장된다
    def broken(*a):
        raise srv.WriterError("검색 실패")

    client.app.fact_checker = broken
    job = client.job("write", {"category": "일상"})
    assert job["state"] == "done" and "factcheck" not in job["result"]
