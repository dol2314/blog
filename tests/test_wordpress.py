import json
from urllib.parse import urlparse

import pytest

from autoposter.models import Category, Post
from autoposter.platforms.base import PlatformError
from autoposter.platforms.wordpress import WordPress


class FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = body if isinstance(body, str) else json.dumps(body)

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class FakeWordPress:
    """워드프레스 REST API를 흉내 내는 가짜 HTTP 세션."""

    def __init__(self, pretty=True, password="abcd efgh"):
        self.pretty = pretty
        self.password = password.replace(" ", "")
        self.tags = [{"id": 7, "name": "여행"}]
        self.posts = []
        self.calls = []

    def request(self, method, url, params=None, auth=None, timeout=None, json=None):
        params = dict(params or {})
        path = urlparse(url).path
        if "rest_route" in params:
            if self.pretty:
                return FakeResponse(404, "<html>not found</html>")
            route = params.pop("rest_route").removeprefix("/wp/v2/")
        elif path.startswith("/wp-json/wp/v2/"):
            if not self.pretty:
                return FakeResponse(404, "<html>not found</html>")
            route = path.removeprefix("/wp-json/wp/v2/")
        else:
            return FakeResponse(404, "<html>not found</html>")
        self.calls.append((method, route, params, json))
        if auth != ("admin", self.password):
            return FakeResponse(401, {"code": "rest_not_logged_in", "message": "로그인 필요"})
        return self.route(method, route, params, json)

    def route(self, method, route, params, body):
        if route == "users/me":
            return FakeResponse(200, {"id": 1})
        if route == "categories":
            pages = {
                1: [{"id": 1, "name": "일상", "parent": 0}],
                2: [{"id": 5, "name": "국내여행", "parent": 3}, {"id": 3, "name": "여행", "parent": 0}],
            }
            return FakeResponse(200, pages[params["page"]], {"X-WP-TotalPages": "2"})
        if route == "tags" and method == "GET":
            return FakeResponse(200, [t for t in self.tags if params["search"] in t["name"]])
        if route == "tags" and method == "POST":
            if any(t["name"] == body["name"] for t in self.tags):
                return FakeResponse(400, {"code": "term_exists", "data": {"term_id": 99}})
            tag = {"id": 100 + len(self.tags), "name": body["name"]}
            self.tags.append(tag)
            return FakeResponse(201, tag)
        if route == "posts" and method == "POST":
            self.posts.append(body)
            return FakeResponse(201, {"id": 42, "link": "https://example.com/?p=42"})
        return FakeResponse(404, {"code": "rest_no_route", "message": "없음"})


def make(pretty=True):
    fake = FakeWordPress(pretty=pretty)
    wp = WordPress({"site": "https://example.com", "username": "admin", "app_password": "abcd efgh"}, session=fake)
    return wp, fake


@pytest.mark.parametrize("pretty", [True, False])
def test_categories_across_pages_with_parent_names(pretty):
    wp, _ = make(pretty)
    labels = [c.label for c in wp.get_categories()]
    assert labels == ["일상", "여행 > 국내여행", "여행"]


def test_publish_sends_category_and_reuses_or_creates_tags():
    wp, fake = make()
    result = wp.publish(Post("제목", "<p>본문</p>", ["여행", "맛집"]), Category("3", "여행"))
    assert result.url == "https://example.com/?p=42"
    sent = fake.posts[0]
    assert sent["status"] == "publish"
    assert sent["categories"] == [3]
    assert sent["tags"][0] == 7  # 기존 태그 재사용
    assert {"id": sent["tags"][1], "name": "맛집"} in fake.tags  # 새 태그 생성


def test_draft_status():
    wp, fake = make()
    assert wp.publish(Post("t", "<p>b</p>"), Category("1", "일상"), draft=True).draft
    assert fake.posts[0]["status"] == "draft"


def test_login_with_wrong_password_raises():
    wp, _ = make()
    answers = iter(["example.com", "admin", "wrong"])
    with pytest.raises(PlatformError):
        wp.login(lambda *a, **k: next(answers))
    assert wp.settings["site"] == "https://example.com"


def test_login_success_and_api_errors_are_reported():
    wp, fake = make()
    answers = iter(["https://example.com/", "admin", "abcd efgh"])
    wp.login(lambda *a, **k: next(answers))
    assert wp.is_logged_in()
    fake.route = lambda *a: FakeResponse(500, {"code": "x", "message": "서버 오류"})
    with pytest.raises(PlatformError, match="서버 오류"):
        wp.get_categories()
