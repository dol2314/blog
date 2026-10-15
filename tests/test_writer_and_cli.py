import json
from types import SimpleNamespace

import pytest

from autoposter import cli
from autoposter.models import Category
from autoposter.platforms.base import PlatformError
from autoposter.platforms.naver import _html_to_text, parse_category_list
from autoposter.platforms.tistory import normalize_blog_name, parse_category_texts
from autoposter.writer import WriterError, write_post


class FakeClient:
    def __init__(self, stop_reason="end_turn", payload=None):
        self.kwargs = None
        payload = payload or {"title": " 제주 여행 ", "html": "<p>본문</p>", "tags": ["#제주", "여행", "제주", " "]}
        self.response = SimpleNamespace(
            stop_reason=stop_reason,
            content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=json.dumps(payload))],
        )
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def test_write_post_requests_structured_output_and_cleans_tags():
    client = FakeClient()
    post = write_post("여행", topic="제주 3박4일", client=client)
    assert post.title == "제주 여행"
    assert post.tags == ["제주", "여행"]
    kw = client.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["fallbacks"] == "default"
    assert "제주 3박4일" in kw["messages"][0]["content"]


@pytest.mark.parametrize("reason", ["refusal", "max_tokens"])
def test_write_post_stop_reasons(reason):
    with pytest.raises(WriterError):
        write_post("여행", client=FakeClient(stop_reason=reason))


def test_markdown_to_html():
    title, body = cli.markdown_to_html(
        "# 제목\n\n첫 문단\n이어짐 **굵게**\n\n## 소제목\n- 하나\n- 둘\n\n1. 첫째\n\n> 인용\n<script>"
    )
    assert title == "제목"
    assert "<p>첫 문단 이어짐 <strong>굵게</strong></p>" in body
    assert "<h2>소제목</h2>" in body
    assert "<ul>\n<li>하나</li>\n<li>둘</li>\n</ul>" in body
    assert "<ol>\n<li>첫째</li>\n</ol>" in body
    assert "<blockquote>인용</blockquote>" in body
    assert "&lt;script&gt;" in body


def test_post_from_html_file(tmp_path):
    path = tmp_path / "a.html"
    path.write_text("<h1>HTML 제목</h1><p>내용</p>", encoding="utf-8")
    post = cli.post_from_file(path, ["태그"])
    assert (post.title, post.html, post.tags) == ("HTML 제목", "<p>내용</p>", ["태그"])


def test_find_category_and_parse_tags():
    cats = [Category("1", "국내", parent="여행"), Category("2", "일상")]
    assert cli.find_category(cats, "여행 > 국내").id == "1"
    assert cli.find_category(cats, "일상").id == "2"
    with pytest.raises(PlatformError, match="있는 카테고리"):
        cli.find_category(cats, "없음")
    assert cli.parse_tags("#여행, 맛집  제주") == ["여행", "맛집", "제주"]


def test_naver_category_api_parsing():
    data = {"result": {"mylogCategoryList": [
        {"categoryNo": 0, "categoryName": "전체보기", "parentCategoryNo": 0},
        {"categoryNo": 1, "categoryName": "여행", "parentCategoryNo": 0},
        {"categoryNo": 2, "categoryName": "국내", "parentCategoryNo": 1},
        {"categoryNo": 3, "categoryName": "", "divisionLine": True},
    ]}}
    assert [c.label for c in parse_category_list(data)] == ["여행", "여행 > 국내"]
    assert _html_to_text("<h2>A</h2><p>B &amp; C</p><ul><li>D</li></ul>") == "A\nB & C\nD"


def test_tistory_helpers():
    assert normalize_blog_name("https://MyBlog.tistory.com/manage") == "myblog"
    assert normalize_blog_name("myblog") == "myblog"
    with pytest.raises(PlatformError):
        normalize_blog_name("my blog!")
    cats = parse_category_texts(["카테고리 없음", "개발", "- 파이썬", "일상"])
    assert [c.label for c in cats] == ["카테고리 없음", "개발", "개발 > 파이썬", "일상"]


def test_interactive_flow_with_fake_platform(monkeypatch, capsys):
    published = {}

    class FakePlatform:
        display_name = "가짜"
        settings = {"site": "x"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def is_logged_in(self):
            return True

        def get_categories(self):
            return [Category("1", "일상"), Category("2", "여행")]

        def publish(self, post, category, draft=False):
            published.update(post=post, category=category, draft=draft)
            return SimpleNamespace(url="https://blog/1", draft=draft)

    monkeypatch.setattr(cli, "open_platform", lambda key, cfg: FakePlatform())
    monkeypatch.setattr(cli, "write_post", lambda *a, **k: write_post(*a, client=FakeClient(), **k))
    # 플랫폼 1번, 카테고리 2번(여행), AI 쓰기, 주제/말투/분량/추가요청, 발행
    answers = iter(["1", "2", "1", "제주", "", "", "", "1"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    assert cli.main([]) == 0
    assert published["category"].name == "여행" and not published["draft"]
    assert "발행 완료! https://blog/1" in capsys.readouterr().out
