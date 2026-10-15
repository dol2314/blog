"""네이버·티스토리용 브라우저 자동화 공통 도구 (Playwright).

로그인은 사용자가 브라우저 창에서 직접 한 번 하고, 그 상태(쿠키)를
플랫폼별 프로필 폴더에 저장해 다음 실행부터 다시 쓴다.
비밀번호는 이 프로그램이 받지도 저장하지도 않는다.
"""

from __future__ import annotations

import os
from typing import Iterable

from .. import config
from .base import PlatformError

DEFAULT_TIMEOUT_MS = 15_000


class Browser:
    def __init__(self, platform: str, headless: bool | None = None):
        self.platform = platform
        if headless is None:
            headless = os.environ.get("AUTOPOSTER_HEADLESS") == "1"
        self.headless = headless
        self._pw = None
        self.context = None

    def start(self):
        if self.context:
            return self.context
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - 설치 안내용
            raise PlatformError("playwright가 설치되어 있지 않습니다: pip install -r requirements.txt") from exc
        self._pw = sync_playwright().start()
        options = dict(
            user_data_dir=str(config.profile_dir(self.platform)),
            headless=self.headless,
            locale="ko-KR",
            viewport={"width": 1280, "height": 900},
            permissions=["clipboard-read", "clipboard-write"],
        )
        # 설치된 크롬이 있으면 그걸 쓰고(로그인 차단이 덜함), 없으면 Playwright 기본 크로미움.
        # AUTOPOSTER_BROWSER_PATH로 브라우저 실행 파일을 직접 지정할 수도 있다.
        candidates = [{"channel": "chrome"}, {}]
        if os.environ.get("AUTOPOSTER_BROWSER_PATH"):
            candidates = [{"executable_path": os.environ["AUTOPOSTER_BROWSER_PATH"]}]
        errors = []
        for extra in candidates:
            try:
                kwargs = dict(options, **extra)
                self.context = self._pw.chromium.launch_persistent_context(**kwargs)
                break
            except Exception as exc:  # noqa: BLE001 - 다음 후보로 넘어간다
                errors.append(str(exc).splitlines()[0])
                _log(f"브라우저 실행 실패 {extra or '기본 크로미움'}: {errors[-1]}")
        if self.context:
            _log(f"브라우저 실행됨: {self.platform}")
        if not self.context:
            self.close()
            raise PlatformError(
                "브라우저를 실행하지 못했습니다. 'python -m playwright install chromium'을 실행해 주세요.\n"
                + "\n".join(errors)
            )
        self.context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        return self.context

    def page(self):
        context = self.start()
        return context.pages[0] if context.pages else context.new_page()

    def cookies(self, url: str) -> dict[str, str]:
        return {c["name"]: c["value"] for c in self.start().cookies(url)}

    def close(self):
        if self.context:
            self.context.close()
            self.context = None
        if self._pw:
            self._pw.stop()
            self._pw = None


def manual_login(browser: Browser, login_url: str, prompt, check) -> None:
    """브라우저 창을 띄워 사용자가 직접 로그인하게 하고, check()로 확인한다."""
    if browser.headless:
        raise PlatformError("로그인은 브라우저 창이 보여야 합니다. AUTOPOSTER_HEADLESS 설정을 끄고 다시 실행하세요.")
    page = browser.page()
    page.goto(login_url)
    for _ in range(3):
        prompt("열린 브라우저 창에서 로그인을 마친 뒤 Enter를 누르세요", allow_empty=True)
        if check():
            return
        print("아직 로그인이 확인되지 않습니다. 브라우저에서 로그인을 완료해 주세요.")
    raise PlatformError("로그인을 확인하지 못했습니다.")


def first_visible(scope, selectors: Iterable[str], timeout_ms: int = DEFAULT_TIMEOUT_MS, what: str | None = None):
    """여러 후보 선택자 중 먼저 화면에 보이는 요소를 돌려준다.

    네이버·티스토리 화면은 예고 없이 바뀌므로, 선택자는 항상 여러 개를 후보로 둔다.
    CSS 선택자뿐 아니라 'text=임시저장' 같은 글자 기준 선택자도 쓸 수 있다.
    찾지 못하면 그 순간의 화면 사진과 버튼 목록을 저장해 원인을 찾을 수 있게 한다.
    """
    selectors = list(selectors)
    locator = scope.locator(selectors[0])
    for selector in selectors[1:]:
        locator = locator.or_(scope.locator(selector))
    locator = locator.first
    try:
        locator.wait_for(state="visible", timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001
        saved = dump_screen(scope, what or selectors[0])
        name = f"'{what}'" if what else "필요한 요소"
        message = f"화면에서 {name}을(를) 찾지 못했습니다. 사이트 화면이 바뀌었을 수 있습니다."
        if saved:
            message += f"\n화면 기록을 저장했습니다: {saved}"
        _log(f"요소 찾기 실패: {what} {selectors}")
        raise PlatformError(message) from exc
    return locator


DUMP_JS = """
() => {
  const items = [];
  for (const el of document.querySelectorAll('button, a, input, textarea, select, [role=button], [contenteditable=true]')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
    items.push(`${el.tagName.toLowerCase()}#${el.id || ''}.${String(el.className || '').trim().replace(/\\s+/g, '.')} "${text.slice(0, 40)}"`);
  }
  return items.slice(0, 300).join('\\n');
}
"""


def dump_screen(scope, label: str) -> str | None:
    """오류가 난 순간의 화면 사진(png)과 버튼 목록(txt)을 ~/.blog-autoposter/debug에 남긴다."""
    try:
        import time as _time

        page = scope if hasattr(scope, "screenshot") else scope.page
        folder = config.HOME / "debug"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = _time.strftime("%Y%m%d-%H%M%S")
        safe = "".join(c if c.isalnum() else "_" for c in label)[:30]
        base = folder / f"{stamp}-{safe}"
        page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        lines = [f"주소: {page.url}", ""]
        for frame in page.frames:
            try:
                found = frame.evaluate(DUMP_JS)
            except Exception:  # noqa: BLE001
                continue
            if found:
                lines += [f"[frame] {frame.url}", found, ""]
        base.with_suffix(".txt").write_text("\n".join(lines), encoding="utf-8")
        return str(base.with_suffix(".png"))
    except Exception:  # noqa: BLE001 - 기록은 부가 기능이라 실패해도 원래 오류를 보여 준다
        return None


def click_if_visible(scope, selectors: Iterable[str], timeout_ms: int = 1_500) -> bool:
    """팝업 닫기처럼 있을 수도 없을 수도 있는 버튼을 누른다."""
    for selector in selectors:
        locator = scope.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout_ms)
        except Exception:  # noqa: BLE001
            continue
        locator.click()
        return True
    return False


PASTE_HTML_JS = """
(el, [html, text]) => {
  const doc = el.ownerDocument;
  const active = doc.activeElement;
  const target = active && active !== doc.body ? active : el;
  const data = new DataTransfer();
  data.setData('text/html', html);
  data.setData('text/plain', text);
  target.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true}));
}
"""


def paste_html(locator, html: str, text: str) -> None:
    """편집기에 HTML을 '붙여넣기'한다. 편집기가 직접 서식으로 변환한다.

    locator 요소(또는 그 안에서 포커스된 요소)에 붙여넣기 이벤트를 보낸다.
    """
    locator.evaluate(PASTE_HTML_JS, [html, text])


def _log(message: str) -> None:
    try:
        from ..app.server import log
    except Exception:  # noqa: BLE001 - 명령창 모드에서는 기록하지 않아도 된다
        return
    log(message)
