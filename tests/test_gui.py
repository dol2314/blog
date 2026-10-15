"""창 화면 동작 테스트. tkinter와 화면(DISPLAY)이 있을 때만 돈다."""

import os
import time

import pytest

tk = pytest.importorskip("tkinter")
if os.name != "nt" and not os.environ.get("DISPLAY"):
    pytest.skip("화면(DISPLAY)이 없습니다", allow_module_level=True)

from autoposter import gui  # noqa: E402
from autoposter.models import Category, Post, PublishResult  # noqa: E402


class FakePlatform:
    display_name = "가짜"

    def __init__(self, settings):
        self.settings = settings
        self.published = None
        self.closed = False

    def login(self, prompt):
        self.settings["blog_id"] = prompt("블로그 아이디")

    def is_logged_in(self):
        return True

    def get_categories(self):
        return [Category("1", "일상"), Category("2", "국내", parent="여행")]

    def publish(self, post, category, draft=False):
        self.published = (post, category, draft)
        return PublishResult(url="https://blog.example/1", draft=draft)

    def close(self):
        self.closed = True


@pytest.fixture
def app(monkeypatch):
    platforms = []

    def fake_open(key, cfg):
        platforms.append(FakePlatform(cfg.setdefault(key, {})))
        return platforms[-1]

    monkeypatch.setattr(gui, "open_platform", fake_open)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: pytest.fail(f"오류 창: {a}"))
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: "tester")
    root = tk.Tk()
    application = gui.App(root)
    application.platforms = platforms
    yield application
    application.on_close()


def pump(app, until, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.root.update()
        if until():
            return
        time.sleep(0.02)
    raise AssertionError("시간 안에 끝나지 않았습니다")


def test_login_load_categories_and_publish(app, monkeypatch):
    pump(app, lambda: app.platforms)
    app.on_login()
    pump(app, lambda: app.categories)
    assert app.cfg["naver"]["blog_id"] == "tester"
    assert list(app.category_box.cget("values")) == ["일상", "여행 > 국내"]

    app.category_var.set("여행 > 국내")
    app._fill_editor(Post("제목", "<p>본문</p>", ["태그1"]))
    app.tags_var.set("태그1, #태그2")
    app.on_publish(draft=True)
    pump(app, lambda: app.last_url)
    post, category, draft = app.platforms[-1].published
    assert (post.title, post.tags, category.name, draft) == ("제목", ["태그1", "태그2"], "국내", True)
    assert str(app.open_post_button.cget("state")) == "normal"


def test_ai_write_fills_editor(app, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    calls = {}

    def fake_write(**kwargs):
        calls.update(kwargs)
        return Post("AI 제목", "<h2>소제목</h2><p>내용</p>", ["a", "b"])

    monkeypatch.setattr(gui, "write_post", fake_write)
    app._set_categories([Category("1", "일상")])
    app.topic_var.set("가을 산책")
    app.model_var.set("절약형 (Claude Sonnet 5.5)")
    app.on_write()
    pump(app, lambda: app.title_var.get())
    assert app.title_var.get() == "AI 제목"
    assert "<h2>소제목</h2>" in app.body_text.get("1.0", "end")
    assert calls["model"] == "claude-sonnet-5-5" and calls["topic"] == "가을 산책"


def test_switching_platform_closes_previous(app):
    pump(app, lambda: app.platforms)
    app.platform_var.set("tistory")
    app.on_platform_change()
    pump(app, lambda: len(app.platforms) == 2)
    pump(app, lambda: app.platforms[0].closed)


def test_errors_are_shown_not_raised(app, monkeypatch):
    shown = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, msg, **k: shown.append(msg))
    pump(app, lambda: app.platforms)
    app.platforms[-1].settings["blog_id"] = "tester"
    app.platforms[-1].get_categories = lambda: (_ for _ in ()).throw(gui.PlatformError("로그인이 풀렸습니다"))
    app.on_load_categories()
    pump(app, lambda: shown)
    assert shown == ["로그인이 풀렸습니다"]
    assert str(app.login_button.cget("state")) == "normal"
