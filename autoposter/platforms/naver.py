"""네이버 블로그: 공식 글쓰기 API가 없어 브라우저(스마트에디터 ONE)를 자동 조작한다.

네이버 화면이 바뀌면 아래 SELECTORS만 고치면 되도록 선택자를 한곳에 모아 두었다.
"""

from __future__ import annotations

import re
import time

from ..models import Category, Post, PublishResult
from .base import Platform, PlatformError
from .browser import Browser, click_if_visible, first_visible, manual_login, paste_html

LOGIN_URL = "https://nid.naver.com/nidlogin.login?url=https%3A%2F%2Fblog.naver.com%2FMyBlog.naver"
MY_BLOG_URL = "https://blog.naver.com/MyBlog.naver"
CATEGORY_API = "https://m.blog.naver.com/api/blogs/{blog_id}/category-list"
WRITE_URL = "https://blog.naver.com/PostWriteForm.naver?blogId={blog_id}"

SELECTORS = {
    # 글쓰기 화면에 들어가면 뜨는 팝업들 (있을 때만 닫는다)
    "popup_cancel": [".se-popup-button-cancel", "button:has-text('취소')"],  # "작성 중인 글이 있습니다"
    "help_close": [".se-help-panel-close-button", "button[class*='help'][class*='close']"],
    "title": [".se-documentTitle .se-text-paragraph", ".se-title-text", "[class*='documentTitle'] [contenteditable]"],
    "body": [
        ".se-component.se-text .se-text-paragraph",
        ".se-main-container .se-text-paragraph",
        "[class*='se-section-text'] [contenteditable]",
    ],
    "body_container": [".se-main-container", ".se-content"],
    "save_button": ["button[class*='save_btn']", ":is(button, a, [role='button']):text-is('저장')", "text=저장"],
    "publish_button": ["button[class*='publish_btn']", ":is(button, a, [role='button']):text-is('발행')"],
    "category_button": ["button[class*='selectbox_button']", "[class*='category'] button"],
    "category_options": ["[class*='option_list'] [class*='text']", "[class*='option_list'] label"],
    "tag_input": ["input[class*='tag_input']", "#tag-input", "input[placeholder*='태그']"],
    "confirm_button": ["button[class*='confirm_btn']", "[class*='layer_btn_area'] button:has-text('발행')"],
}

POST_URL_PATTERNS = [re.compile(r"logNo=(\d+)"), re.compile(r"blog\.naver\.com/[^/?#]+/(\d+)")]


class NaverBlog(Platform):
    key = "naver"
    display_name = "네이버 블로그"

    def __init__(self, settings: dict, browser: Browser | None = None):
        super().__init__(settings)
        self.browser = browser or Browser(self.key)

    # ---- 접속 -------------------------------------------------------------

    def login(self, prompt) -> None:
        if not self.is_logged_in():
            manual_login(self.browser, LOGIN_URL, prompt, self.is_logged_in)
        blog_id = self._detect_blog_id()
        if not blog_id:
            blog_id = prompt("블로그 아이디 (blog.naver.com/아이디 의 '아이디' 부분)").strip()
        self.settings["blog_id"] = blog_id

    def is_logged_in(self) -> bool:
        cookies = self.browser.cookies("https://nid.naver.com")
        return bool(cookies.get("NID_AUT") and cookies.get("NID_SES"))

    def _detect_blog_id(self) -> str | None:
        page = self.browser.page()
        page.goto(MY_BLOG_URL)
        page.wait_for_load_state("domcontentloaded")
        match = re.match(r"https://(?:m\.)?blog\.naver\.com/([A-Za-z0-9_-]+)/?$", page.url.split("?")[0])
        if match and match.group(1) not in ("MyBlog.naver", "PostList.naver"):
            return match.group(1)
        return None

    @property
    def blog_id(self) -> str:
        blog_id = self.settings.get("blog_id")
        if not blog_id:
            raise PlatformError("블로그 아이디가 없습니다. 먼저 접속(login)을 해 주세요.")
        return blog_id

    # ---- 카테고리 -----------------------------------------------------------

    def get_categories(self) -> list[Category]:
        try:
            resp = self.browser.start().request.get(
                CATEGORY_API.format(blog_id=self.blog_id),
                headers={"Referer": f"https://m.blog.naver.com/{self.blog_id}"},
            )
            categories = parse_category_list(resp.json()) if resp.ok else []
        except Exception:  # noqa: BLE001 - API가 바뀌었거나 막히면 편집기에서 읽는다
            categories = []
        return categories or self._categories_from_editor()

    def _categories_from_editor(self) -> list[Category]:
        """API가 안 될 때: 글쓰기 화면의 발행 창에서 카테고리 목록을 읽는다."""
        scope = self._open_editor()
        first_visible(scope, SELECTORS["publish_button"], what="발행 버튼").click()
        first_visible(scope, SELECTORS["category_button"], what="카테고리 버튼").click()
        first_visible(scope, SELECTORS["category_options"], what="카테고리 목록")
        names = [t.strip() for t in scope.locator(", ".join(SELECTORS["category_options"])).all_inner_texts()]
        return [Category(id=name, name=name) for name in dict.fromkeys(n for n in names if n)]

    # ---- 발행 -------------------------------------------------------------

    def publish(self, post: Post, category: Category, draft: bool = False) -> PublishResult:
        scope = self._open_editor()
        page = self.browser.page()

        first_visible(scope, SELECTORS["title"], what="제목 입력칸").click()
        page.keyboard.type(post.title)

        body = first_visible(scope, SELECTORS["body"], what="본문 입력칸")
        body.click()
        container = first_visible(scope, SELECTORS["body_container"], what="본문 영역")
        before = len(container.inner_text())
        paste_html(body, post.html, _html_to_text(post.html))
        time.sleep(1)
        if len(container.inner_text()) - before < 10:
            # 붙여넣기가 막힌 경우: 서식 없이 문단 단위로 직접 입력한다.
            for line in _html_to_text(post.html).split("\n"):
                page.keyboard.type(line)
                page.keyboard.press("Enter")

        if draft:
            first_visible(scope, SELECTORS["save_button"], what="저장 버튼").click()
            time.sleep(2)
            return PublishResult(url=None, draft=True)

        first_visible(scope, SELECTORS["publish_button"], what="발행 버튼").click()
        self._select_category(scope, category)
        if post.tags:
            tag_input = first_visible(scope, SELECTORS["tag_input"], what="태그 입력칸")
            for tag in post.tags[:30]:
                tag_input.fill(tag.lstrip("#"))
                tag_input.press("Enter")
        first_visible(scope, SELECTORS["confirm_button"], what="발행 확인 버튼").click()
        return PublishResult(url=self._wait_for_post_url(), draft=False)

    def _open_editor(self):
        page = self.browser.page()
        page.goto(WRITE_URL.format(blog_id=self.blog_id))
        page.wait_for_load_state("domcontentloaded")
        if "nidlogin" in page.url:
            raise PlatformError("네이버 로그인이 풀렸습니다. 다시 접속(login)해 주세요.")
        # 예전 주소 형태로 열리면 편집기가 mainFrame 안에 들어 있다.
        scope = page.frame(name="mainFrame") or page.main_frame
        first_visible(scope, SELECTORS["title"], timeout_ms=30_000, what="제목 입력칸")
        click_if_visible(scope, SELECTORS["popup_cancel"])
        click_if_visible(scope, SELECTORS["help_close"])
        return scope

    def _select_category(self, scope, category: Category) -> None:
        first_visible(scope, SELECTORS["category_button"], what="카테고리 버튼").click()
        options = scope.locator(", ".join(SELECTORS["category_options"]))
        first_visible(scope, SELECTORS["category_options"], what="카테고리 목록")
        exact = re.compile(rf"^\s*{re.escape(category.name)}\s*$")
        match = options.filter(has_text=exact).first
        if match.count() == 0:
            raise PlatformError(f"발행 창에서 카테고리 '{category.name}'를 찾지 못했습니다.")
        match.click()

    def _wait_for_post_url(self, timeout_s: int = 30) -> str | None:
        page = self.browser.page()
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            for url in [page.url] + [f.url for f in page.frames]:
                for pattern in POST_URL_PATTERNS:
                    match = pattern.search(url)
                    if match:
                        return f"https://blog.naver.com/{self.blog_id}/{match.group(1)}"
            time.sleep(0.5)
        return None  # 발행은 됐지만 주소를 못 읽은 경우

    def close(self) -> None:
        self.browser.close()


def parse_category_list(data: dict) -> list[Category]:
    """m.blog.naver.com 카테고리 API 응답을 Category 목록으로 바꾼다."""
    items = data["result"]["mylogCategoryList"]
    names = {str(i["categoryNo"]): i["categoryName"] for i in items}
    categories = []
    for item in items:
        number = str(item["categoryNo"])
        if number == "0" or item.get("divisionLine"):  # '전체보기', 구분선
            continue
        parent_no = str(item.get("parentCategoryNo") or "")
        parent = names.get(parent_no) if parent_no and parent_no != number else None
        categories.append(Category(id=number, name=item["categoryName"], parent=parent))
    return categories


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>|</(p|h[1-6]|li|blockquote)>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    for entity, char in (("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&amp;", "&")):
        text = text.replace(entity, char)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
