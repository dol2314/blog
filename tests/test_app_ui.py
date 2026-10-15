"""실제 브라우저로 앱 화면을 눌러 보는 테스트 (크로미움이 있을 때만)."""

import os
import shutil
import threading
import time

import pytest

from autoposter import local_ai
from autoposter.app import server as srv
from tests.test_app import FakePlatform, fake_write

BROWSER_PATH = os.environ.get("AUTOPOSTER_BROWSER_PATH") or shutil.which("chromium") or "/opt/pw-browsers/chromium"
pytestmark = pytest.mark.skipif(not os.path.exists(BROWSER_PATH), reason="크로미움이 없습니다")


def test_write_and_publish_through_ui(monkeypatch):
    from playwright.sync_api import sync_playwright

    fake_write.calls = []
    monkeypatch.setattr(local_ai, "status", lambda session=None: {"running": True, "installed": True, "models": ["qwen3:8b"]})
    platforms = []

    def factory(key, cfg):
        settings = cfg.setdefault(key, {})
        settings.setdefault("blog_id", "tester")
        platforms.append(FakePlatform(settings))
        return platforms[-1]

    app = srv.App(platform_factory=factory, writers={"local": fake_write, "claude": fake_write})
    server = srv.create_server(app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/?t={app.token}"
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=BROWSER_PATH)
            page = browser.new_page(viewport={"width": 1360, "height": 860})
            page.route("https://cdn.jsdelivr.net/**", lambda r: r.abort())  # 글꼴 CDN은 테스트에서 생략
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_selector("#empty:not([hidden])")
            page.click("#cat-btn")
            page.wait_for_function("document.querySelectorAll('#category option').length === 2")
            page.select_option("#category", "여행 > 국내")
            page.fill("#topic", "단풍")
            page.click("#write-btn")
            page.wait_for_selector("#drawer.open")
            assert page.input_value("#d-title") == "AI 제목"
            page.fill("#d-title", "UI에서 고친 제목")
            time.sleep(0.8)  # 자동 저장
            page.click("#d-publish")
            page.click("#modal-ok")
            page.wait_for_function("document.querySelector('#d-publish').textContent === '다시 발행'")
            assert page.inner_text("#post-rows tr:first-child .status") == "발행"
            browser.close()
    finally:
        server.shutdown()
        app.close()
    assert not errors
    assert fake_write.calls[0]["topic"] == "단풍"
    post, category, draft = platforms[-1].published[0]
    assert (post.title, category.label, draft) == ("UI에서 고친 제목", "여행 > 국내", False)
