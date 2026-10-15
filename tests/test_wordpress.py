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
        self.app_passwords = True
        self.posts = []
        self.calls = []

    def get(self, url, params=None, timeout=None):
        # 사이트 첫 화면 정보 (앱 연결 승인 주소 포함)
        params = params or {}
        if (urlparse(url).path == "/wp-json/" and self.pretty) or (params.get("rest_route") == "/" and not self.pretty):
            auth = {"application-passwords": {"endpoints": {"authorization": "https://example.com/wp-admin/authorize-application.php"}}}
            return FakeResponse(200, {"namespaces": ["wp/v2"], "authentication": auth if self.app_passwords else []})
        return FakeResponse(404, "<html>not found</html>")

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
    wp.open_url = lambda url: None
    answers = iter(["example.com", "admin", "wrong"])
    with pytest.raises(PlatformError, match="새 비밀번호"):
        wp.login(lambda *a, **k: next(answers))
    assert wp.settings["site"] == "https://example.com"


@pytest.mark.parametrize("pretty", [True, False])
def test_login_opens_authorize_screen(pretty):
    wp, fake = make(pretty)
    opened, questions = [], []
    wp.open_url = opened.append
    answers = iter(["example.com", "admin", "abcd efgh"])

    def prompt(question, **kw):
        questions.append(question)
        return next(answers)

    wp.login(prompt)
    assert opened == ["https://example.com/wp-admin/authorize-application.php?app_name=%EB%B8%94%EB%A1%9C%EA%B7%B8%20%EC%9E%90%EB%8F%99%20%ED%8F%AC%EC%8A%A4%ED%8C%85"]
    assert "승인합니다" in questions[-1]
    assert wp.is_logged_in()


def test_login_without_app_password_support_opens_profile():
    wp, fake = make()
    fake.app_passwords = False
    opened = []
    wp.open_url = opened.append
    answers = iter(["example.com", "admin", "abcd efgh"])
    wp.login(lambda *a, **k: next(answers))
    assert opened == ["https://example.com/wp-admin/profile.php"]


def test_login_rejects_non_wordpress_site():
    wp, fake = make()
    fake.get = lambda *a, **k: FakeResponse(200, "<html>그냥 홈페이지</html>")
    with pytest.raises(PlatformError, match="워드프레스를 찾지 못했습니다"):
        wp.login(lambda *a, **k: "example.com")


def test_login_success_and_api_errors_are_reported():
    wp, fake = make()
    wp.open_url = lambda url: None
    answers = iter(["https://example.com/", "admin", "abcd efgh"])
    wp.login(lambda *a, **k: next(answers))
    assert wp.is_logged_in()
    fake.route = lambda *a: FakeResponse(500, {"code": "x", "message": "서버 오류"})
    with pytest.raises(PlatformError, match="서버 오류"):
        wp.get_categories()


def test_publish_sends_slug_meta_and_finds_similar():
    wp, fake = make()
    post = Post("제목", "<p>본문</p>", [], slug="my-slug", meta={"rank_math_focus_keyword": "키워드"})
    wp.publish(post, Category("1", "일상"))
    assert fake.posts[0]["slug"] == "my-slug" and fake.posts[0]["meta"] == {"rank_math_focus_keyword": "키워드"}
    wp.publish(Post("제목2", "<p>본문</p>"), Category("1", "일상"))
    assert "slug" not in fake.posts[1] and "meta" not in fake.posts[1]

    fake.route = lambda method, route, params, body: FakeResponse(
        200, [{"id": 1, "title": {"rendered": "정수기 &amp; 렌탈"}, "link": "https://e/1", "status": "draft", "date": "d"}]
    )
    assert wp.find_similar("정수기") == [{"title": "정수기 & 렌탈", "link": "https://e/1", "status": "draft", "date": "d"}]
