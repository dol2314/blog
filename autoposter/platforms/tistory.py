"""티스토리: 오픈 API가 종료돼 브라우저(티스토리 편집기)를 자동 조작한다.

티스토리 화면이 바뀌면 아래 SELECTORS만 고치면 되도록 선택자를 한곳에 모아 두었다.
"""

from __future__ import annotations

import re
import time

from ..models import Category, Post, PublishResult
from .base import Platform, PlatformError
from .browser import Browser, click_if_visible, first_visible, manual_login, paste_html

LOGIN_URL = "https://www.tistory.com/auth/login"
EDITOR_URL = "https://{blog}.tistory.com/manage/newpost/?type=post"

SELECTORS = {
    "title": ["#post-title-inp", "textarea[placeholder*='제목']"],
    "editor_iframe": ["#editor-tistory_ifr", "iframe[id$='_ifr']"],
    "category_button": ["#category-btn", "button:has-text('카테고리')"],
    "category_options": ["#category-list .mce-menu-item", "#category-list [role='option']"],
    "tag_input": ["#tagText", "input[placeholder*='태그']"],
    "draft_button": [
        "button.btn-draft",
        "a.btn-draft",
        ":is(button, a, [role='button']):has-text('임시저장')",
        "text=임시저장",
    ],
    "publish_layer_button": [
        "#publish-layer-btn",
        ":is(button, a, [role='button']):text-is('완료')",
        "text=완료",
    ],
    "public_radio": ["#open20", "label:has-text('공개'):not(:has-text('비공개'))"],
    "publish_button": [
        "#publish-btn",
        ":is(button, a, [role='button']):has-text('공개 발행')",
        ":is(button, a, [role='button']):has-text('발행')",
    ],
}

SET_CONTENT_JS = """
(html) => {
  const ed = window.tinymce && window.tinymce.activeEditor;
  if (!ed) return false;
  ed.setContent(html);
  ed.fire('change');
  ed.save && ed.save();
  return true;
}
"""


class Tistory(Platform):
    key = "tistory"
    display_name = "티스토리"

    def __init__(self, settings: dict, browser: Browser | None = None):
        super().__init__(settings)
        self.browser = browser or Browser(self.key)

    # ---- 접속 -------------------------------------------------------------

    def login(self, prompt) -> None:
        if not self.is_logged_in():
            manual_login(self.browser, LOGIN_URL, prompt, self.is_logged_in)
        answer = prompt("블로그 주소 (예: myblog.tistory.com 또는 myblog)")
        self.settings["blog_name"] = normalize_blog_name(answer)

    def is_logged_in(self) -> bool:
        return bool(self.browser.cookies("https://www.tistory.com").get("TSSESSION"))

    @property
    def blog(self) -> str:
        blog = self.settings.get("blog_name")
        if not blog:
            raise PlatformError("블로그 주소가 없습니다. 먼저 접속(login)을 해 주세요.")
        return blog

    # ---- 카테고리 -----------------------------------------------------------

    def get_categories(self) -> list[Category]:
        page = self._open_editor()
        first_visible(page, SELECTORS["category_button"], what="카테고리 버튼").click()
        first_visible(page, SELECTORS["category_options"], what="카테고리 목록")
        texts = page.locator(", ".join(SELECTORS["category_options"])).all_inner_texts()
        page.keyboard.press("Escape")
        return parse_category_texts(texts)

    # ---- 발행 -------------------------------------------------------------

    def publish(self, post: Post, category: Category, draft: bool = False) -> PublishResult:
        page = self._open_editor()

        first_visible(page, SELECTORS["title"], what="제목 입력칸").fill(post.title)
        self._set_body(page, post.html)
        self._select_category(page, category)

        if post.tags:
            tag_input = first_visible(page, SELECTORS["tag_input"], what="태그 입력칸")
            for tag in post.tags[:10]:  # 티스토리는 태그 10개 제한
                tag_input.fill(tag.lstrip("#"))
                tag_input.press("Enter")

        if draft:
            first_visible(page, SELECTORS["draft_button"], what="임시저장 버튼").click()
            time.sleep(2)
            return PublishResult(url=None, draft=True)

        first_visible(page, SELECTORS["publish_layer_button"], what="완료 버튼").click()
        click_if_visible(page, SELECTORS["public_radio"], timeout_ms=3_000)
        first_visible(page, SELECTORS["publish_button"], what="발행 버튼").click()
        try:
            page.wait_for_url(lambda url: "newpost" not in url, timeout=30_000)
        except Exception as exc:  # noqa: BLE001
            raise PlatformError("발행 완료를 확인하지 못했습니다. 브라우저 화면을 확인해 주세요.") from exc
        return PublishResult(url=self._latest_post_url(page), draft=False)

    def _open_editor(self):
        page = self.browser.page()
        page.once("dialog", lambda dialog: dialog.dismiss())  # "저장된 글을 이어서 쓸까요?" → 새 글
        page.goto(EDITOR_URL.format(blog=self.blog))
        page.wait_for_load_state("domcontentloaded")
        if "auth/login" in page.url or "accounts.kakao.com" in page.url:
            raise PlatformError("티스토리 로그인이 풀렸습니다. 다시 접속(login)해 주세요.")
        first_visible(page, SELECTORS["title"], timeout_ms=30_000, what="글쓰기 화면")
        return page

    def _set_body(self, page, html: str) -> None:
        first_visible(page, SELECTORS["editor_iframe"], timeout_ms=30_000, what="본문 편집기")
        if page.evaluate(SET_CONTENT_JS, html):
            return
        # 편집기 객체를 못 찾으면 본문 영역에 붙여넣는다.
        frame = page.frame_locator(", ".join(SELECTORS["editor_iframe"])).first
        body = frame.locator("body")
        body.click()
        paste_html(body, html, re.sub(r"<[^>]+>", "", html))

    def _select_category(self, page, category: Category) -> None:
        first_visible(page, SELECTORS["category_button"], what="카테고리 버튼").click()
        first_visible(page, SELECTORS["category_options"], what="카테고리 목록")
        exact = re.compile(rf"^[\s\-]*{re.escape(category.name)}\s*$")
        match = page.locator(", ".join(SELECTORS["category_options"])).filter(has_text=exact).first
        if match.count() == 0:
            raise PlatformError(f"편집기에서 카테고리 '{category.name}'를 찾지 못했습니다.")
        match.click()

    def _latest_post_url(self, page) -> str | None:
        """발행 후 관리 화면 글 목록의 첫 글 주소를 읽는다 (못 읽으면 None)."""
        try:
            page.wait_for_load_state("domcontentloaded")
            hrefs = page.eval_on_selector_all("a[href]", "links => links.map(a => a.href)")
        except Exception:  # noqa: BLE001
            return None
        pattern = re.compile(rf"^https?://{re.escape(self.blog)}\.tistory\.com/(entry/[^?#]+|\d+)/?$")
        return next((href for href in hrefs if pattern.match(href)), None)

    def close(self) -> None:
        self.browser.close()


def normalize_blog_name(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value).split("/")[0]
    value = value.removesuffix(".tistory.com")
    if not re.fullmatch(r"[a-z0-9-]+", value):
        raise PlatformError(f"블로그 주소 형식이 올바르지 않습니다: {value!r}")
    return value


def parse_category_texts(texts: list[str]) -> list[Category]:
    """편집기 카테고리 목록 글자를 Category로 바꾼다. 하위 카테고리는 '- '로 시작한다."""
    categories: list[Category] = []
    parent: str | None = None
    for raw in texts:
        text = raw.strip()
        if not text or text == "카테고리":  # '카테고리 없음'은 남겨 둔다
            continue
        if text.startswith("-"):
            name = text.lstrip("- ").strip()
            categories.append(Category(id=name, name=name, parent=parent))
        else:
            parent = text
            categories.append(Category(id=text, name=text))
    return categories
