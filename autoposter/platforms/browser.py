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


def first_visible(scope, selectors: Iterable[str], timeout_ms: int = DEFAULT_TIMEOUT_MS):
    """여러 후보 선택자 중 먼저 화면에 보이는 요소를 돌려준다.

    네이버·티스토리 화면은 예고 없이 바뀌므로, 선택자는 항상 여러 개를 후보로 둔다.
    """
    selectors = list(selectors)
    combined = scope.locator(", ".join(selectors)).first
    try:
        combined.wait_for(state="visible", timeout=timeout_ms)
    except Exception as exc:  # noqa: BLE001
        raise PlatformError(f"화면에서 요소를 찾지 못했습니다: {selectors}") from exc
    return combined


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
