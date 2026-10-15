"""네이버·티스토리 브라우저 자동화 흐름 테스트.

실제 사이트 대신, 그 주소로 가는 요청을 가짜 편집기 화면으로 바꿔치기한다.
가짜 화면은 프로그램이 쓰는 선택자에 맞춰 만든 것이라, 실제 사이트 화면이
바뀌었는지까지는 확인하지 못한다. 대신 클릭·입력·붙여넣기·주소 읽기 같은
흐름 자체의 오류를 잡는다.
"""

import os
import shutil

import pytest

from autoposter.models import Category, Post
from autoposter.platforms.browser import Browser
from autoposter.platforms.naver import NaverBlog
from autoposter.platforms.tistory import Tistory

BROWSER_PATH = os.environ.get("AUTOPOSTER_BROWSER_PATH") or shutil.which("chromium") or "/opt/pw-browsers/chromium"
pytestmark = pytest.mark.skipif(not os.path.exists(BROWSER_PATH), reason="크로미움이 없습니다")

NAVER_EDITOR = """<!doctype html><meta charset="utf-8">
<div class="se-popup"><p>작성 중인 글이 있습니다</p>
  <button class="se-popup-button-cancel" onclick="this.parentNode.remove()">취소</button></div>
<button class="se-help-panel-close-button" onclick="this.remove()">도움말 닫기</button>
<button class="save_btn__a1" onclick="window.saved = true">저장</button>
<button class="publish_btn__b2" onclick="document.getElementById('layer').style.display='block'">발행</button>
<div class="se-documentTitle"><div class="se-text-paragraph" contenteditable="true" id="title"></div></div>
<div class="se-main-container"><div class="se-component se-text">
  <div class="se-text-paragraph" contenteditable="true" id="body"></div></div></div>
<div id="layer" style="display:none">
  <button class="selectbox_button__c3" onclick="document.getElementById('opts').style.display='block'">게시판</button>
  <ul id="opts" class="option_list__d4" style="display:none">
    <li><label class="text__e5" onclick="window.cat='일상'">일상</label></li>
    <li><label class="text__e5" onclick="window.cat='여행'">여행</label></li>
  </ul>
  <input class="tag_input__f6" onkeydown="if (event.key === 'Enter') { (window.tags = window.tags || []).push(this.value); this.value = ''; }">
  <div class="layer_btn_area__g7"><button class="confirm_btn__h8"
    onclick="sessionStorage.setItem('post', JSON.stringify({title: document.getElementById('title').innerText, body: document.getElementById('body').innerHTML, cat: window.cat, tags: window.tags})); location.href='https://blog.naver.com/PostView.naver?blogId=tester&logNo=223344'">발행</button></div>
</div>
<script>
document.getElementById('body').addEventListener('paste', (e) => {
  e.preventDefault();
  document.getElementById('body').innerHTML = e.clipboardData.getData('text/html');
});
</script>"""

TISTORY_EDITOR = """<!doctype html><meta charset="utf-8">
<textarea id="post-title-inp"></textarea>
<button id="category-btn" onclick="document.getElementById('category-list').style.display='block'">카테고리</button>
<div id="category-list" style="display:none">
  <div class="mce-menu-item" onclick="window.cat='카테고리 없음'">카테고리 없음</div>
  <div class="mce-menu-item" onclick="window.cat='개발'">개발</div>
  <div class="mce-menu-item" onclick="window.cat='파이썬'">- 파이썬</div>
</div>
<iframe id="editor-tistory_ifr" srcdoc="<body></body>"></iframe>
<input id="tagText" onkeydown="if (event.key === 'Enter') { (window.tags = window.tags || []).push(this.value); this.value = ''; }">
<button class="btn-draft" onclick="window.drafted = true">임시저장</button>
<button id="publish-layer-btn" onclick="document.getElementById('layer').style.display='block'">완료</button>
<div id="layer" style="display:none">
  <input type="radio" name="open" id="open0" checked><input type="radio" name="open" id="open20">
  <button id="publish-btn" onclick="sessionStorage.setItem('post', JSON.stringify({title: document.getElementById('post-title-inp').value, body: window.content, cat: window.cat, tags: window.tags, open: document.getElementById('open20').checked})); location.href='https://myblog.tistory.com/manage/posts/'">공개 발행</button>
</div>
<script>
window.resumed = confirm('저장된 글이 있습니다. 이어서 작성하시겠습니까?');
window.tinymce = {activeEditor: {setContent(h) { window.content = h; }, fire() {}, save() {}}};
</script>"""

TISTORY_POSTS = """<!doctype html><meta charset="utf-8">
<a href="https://myblog.tistory.com/manage">관리</a>
<a href="https://myblog.tistory.com/entry/first-post">첫 글</a>"""


def fulfill(route, body):
    route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)


@pytest.fixture
def browser(monkeypatch):
    monkeypatch.setenv("AUTOPOSTER_BROWSER_PATH", BROWSER_PATH)
    b = Browser("test", headless=True)
    yield b
    b.close()


def read_saved_post(page):
    return page.evaluate("JSON.parse(sessionStorage.getItem('post'))")


def test_naver_publish_flow(browser):
    ctx = browser.start()
    ctx.route("https://blog.naver.com/PostWriteForm.naver**", lambda r: fulfill(r, NAVER_EDITOR))
    ctx.route("https://blog.naver.com/PostView.naver**", lambda r: fulfill(r, "<p>게시됨</p>"))
    ctx.route("https://m.blog.naver.com/**", lambda r: r.abort())
    ctx.add_cookies([
        {"name": n, "value": "v", "domain": ".naver.com", "path": "/"} for n in ("NID_AUT", "NID_SES")
    ])
    naver = NaverBlog({"blog_id": "tester"}, browser=browser)
    assert naver.is_logged_in()

    # 카테고리 API가 막히면 발행 창에서 읽어 온다
    assert [c.name for c in naver.get_categories()] == ["일상", "여행"]

    post = Post("제주 여행 정리", "<h2>첫째 날</h2><p>바다를 봤다</p>", ["제주", "#여행"])
    result = naver.publish(post, Category("2", "여행"))
    assert result.url == "https://blog.naver.com/tester/223344"
    saved = read_saved_post(browser.page())
    assert saved["title"] == "제주 여행 정리"
    assert "<h2>첫째 날</h2>" in saved["body"]
    assert saved["cat"] == "여행"
    assert saved["tags"] == ["제주", "여행"]


def test_naver_draft(browser):
    ctx = browser.start()
    ctx.route("https://blog.naver.com/PostWriteForm.naver**", lambda r: fulfill(r, NAVER_EDITOR))
    naver = NaverBlog({"blog_id": "tester"}, browser=browser)
    result = naver.publish(Post("임시", "<p>저장만</p>"), Category("1", "일상"), draft=True)
    assert result.draft and result.url is None
    assert browser.page().evaluate("window.saved") is True


def test_tistory_flow(browser):
    ctx = browser.start()
    ctx.route("https://myblog.tistory.com/manage/newpost/**", lambda r: fulfill(r, TISTORY_EDITOR))
    ctx.route("https://myblog.tistory.com/manage/posts/**", lambda r: fulfill(r, TISTORY_POSTS))
    ctx.add_cookies([{"name": "TSSESSION", "value": "v", "domain": ".tistory.com", "path": "/"}])
    tistory = Tistory({"blog_name": "myblog"}, browser=browser)
    assert tistory.is_logged_in()

    cats = tistory.get_categories()
    assert [c.label for c in cats] == ["카테고리 없음", "개발", "개발 > 파이썬"]
    assert browser.page().evaluate("window.resumed") is False  # 이어쓰기 팝업은 거절

    result = tistory.publish(Post("파이썬 팁", "<p>내용</p>", ["파이썬"]), cats[2])
    assert result.url == "https://myblog.tistory.com/entry/first-post"
    saved = read_saved_post(browser.page())
    assert saved == {"title": "파이썬 팁", "body": "<p>내용</p>", "cat": "파이썬", "tags": ["파이썬"], "open": True}


def test_tistory_draft_button_found_by_text(browser):
    # 실제 티스토리처럼 임시저장이 button.btn-draft가 아닌 다른 요소일 때도 글자로 찾는다
    editor = TISTORY_EDITOR.replace(
        '<button class="btn-draft" onclick="window.drafted = true">임시저장</button>',
        '<a href="#" class="action" onclick="window.drafted = true; return false;"><span>임시저장</span><span>3</span></a>',
    )
    ctx = browser.start()
    ctx.route("https://myblog.tistory.com/manage/newpost/**", lambda r: fulfill(r, editor))
    tistory = Tistory({"blog_name": "myblog"}, browser=browser)
    result = tistory.publish(Post("임시 글", "<p>내용</p>"), Category("개발", "개발"), draft=True)
    assert result.draft and browser.page().evaluate("window.drafted") is True


def test_missing_element_saves_screen_record(browser, tmp_home):
    from autoposter.platforms.base import PlatformError

    editor = TISTORY_EDITOR.replace('<button class="btn-draft" onclick="window.drafted = true">임시저장</button>', "")
    ctx = browser.start()
    ctx.route("https://myblog.tistory.com/manage/newpost/**", lambda r: fulfill(r, editor))
    tistory = Tistory({"blog_name": "myblog"}, browser=browser)
    import autoposter.platforms.browser as browser_mod

    browser_mod.DEFAULT_TIMEOUT_MS, old = 1500, browser_mod.DEFAULT_TIMEOUT_MS
    try:
        with pytest.raises(PlatformError, match="임시저장 버튼") as info:
            tistory.publish(Post("임시 글", "<p>내용</p>"), Category("개발", "개발"), draft=True)
    finally:
        browser_mod.DEFAULT_TIMEOUT_MS = old
    pngs = list((tmp_home / "debug").glob("*.png"))
    txts = list((tmp_home / "debug").glob("*.txt"))
    assert pngs and txts and str(pngs[0]) in str(info.value)
    listing = txts[0].read_text(encoding="utf-8")
    assert "publish-layer-btn" in listing and '"완료"' in listing
