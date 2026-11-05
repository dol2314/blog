"""앱 서버 테스트 (오프라인)."""
import json
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import server as srv  # noqa: E402
from modules import pipeline  # noqa: E402


@pytest.fixture
def running(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "OUTPUT", tmp_path / "output")
    monkeypatch.setattr(srv, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(srv, "ASSETS", tmp_path / "assets")
    monkeypatch.setenv("SCRIPT_PROVIDER", "template")
    app = srv.App()
    httpd = srv.create_server(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"

    def call(path, method="GET", body=None, token=True):
        req = urllib.request.Request(base + urllib.parse.quote(path, safe="/?=&"), method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Token": app.token if token else "x", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    yield app, call, tmp_path
    httpd.shutdown()


def wait(call, job):
    import time

    for _ in range(100):
        s, j = call(f"/api/jobs/{job['id']}")
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.1)
    raise AssertionError("job timeout")


def test_token_required(running):
    _, call, _ = running
    assert call("/api/state", token=False)[0] == 403


def test_create_edit_and_list_project(running):
    _, call, _ = running
    s, job = call("/api/projects", "POST", {"topic": "난방비 절약", "type": "shorts", "seconds": 30, "provider": "template"})
    assert s == 200
    j = wait(call, job)
    assert j["status"] == "done", j
    pid = j["result"]["project"]
    s, p = call(f"/api/projects/{pid}/script", "PUT",
                {"title": "새 제목", "tags": ["a", " ", "b"], "scenes": [{"section": "hook", "text": "첫 장면"},
                                                                         {"section": "cta", "text": "구독"}]})
    assert s == 200 and p["script"]["title"] == "새 제목" and len(p["script"]["scenes"]) == 2
    assert p["script"]["tags"] == ["a", "b"]
    s, items = call("/api/projects")
    assert items[0]["id"] == pid and items[0]["has_video"] is False
    assert call("/api/projects/../x")[0] in (400, 404)


def test_settings_keep_comments_and_hide_secrets(running):
    _, call, tmp = running
    (tmp / ".env").write_text("# 주석\nOPENAI_API_KEY=sk-old\nEDGE_RATE=+10%   # 속도\n", encoding="utf-8")
    s, items = call("/api/settings")
    key = next(i for i in items if i["key"] == "OPENAI_API_KEY")
    assert key["value"] == "" and key["set"] is True
    call("/api/settings", "PUT", {"EDGE_RATE": "+20%", "OPENAI_API_KEY": "", "BGM_VOLUME": "0.2", "NOT_ALLOWED": "x"})
    text = (tmp / ".env").read_text(encoding="utf-8")
    assert "# 주석" in text and "OPENAI_API_KEY=sk-old" in text and "EDGE_RATE=+20%" in text
    assert "BGM_VOLUME=0.2" in text and "NOT_ALLOWED" not in text


def test_render_rejects_unknown_asset(running):
    _, call, _ = running
    _, job = call("/api/projects", "POST", {"topic": "t", "provider": "template"})
    pid = wait(call, job)["result"]["project"]
    s, r = call(f"/api/projects/{pid}/render", "POST", {"bgm": "nope.mp3"})
    assert s == 400 and "소재" in r["error"]
