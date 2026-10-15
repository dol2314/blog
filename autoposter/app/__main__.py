"""앱 실행: 로컬 서버를 켜고, Edge(없으면 크롬)를 주소창 없는 앱 창으로 띄운다.

창을 닫으면 서버도 함께 꺼진다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .. import config
from .server import App, create_server, log, log_error

STARTUP_TIMEOUT = 180  # 창이 이 시간 안에 한 번도 연결하지 않으면 종료
CLOSE_GRACE = 20  # 창과의 연결이 모두 끊긴 뒤(새로고침이 아니면) 이 시간이 지나면 종료


def find_app_browser() -> str | None:
    candidates = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                candidates += [
                    Path(base) / "Microsoft/Edge/Application/msedge.exe",
                    Path(base) / "Google/Chrome/Application/chrome.exe",
                ]
    else:
        candidates += [shutil.which(n) for n in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser")]
    return next((str(c) for c in candidates if c and Path(c).exists()), None)


def open_window(url: str) -> subprocess.Popen | None:
    exe = find_app_browser()
    if not exe:
        webbrowser.open(url)
        return None
    profile = config.HOME / "app-window"  # 앱 창 전용 프로필 → 창을 닫으면 프로세스도 끝난다
    args = [
        exe,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--window-size=1360,880",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(args, creationflags=flags)  # noqa: S603


def main() -> int:
    app = App()
    server = create_server(app)
    url = f"http://127.0.0.1:{server.server_port}/?t={app.token}"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    if not os.environ.get("AUTOPOSTER_NO_WINDOW"):
        open_window(url)  # 브라우저 프로세스는 다른 프로세스에 창을 넘기고 바로 끝날 수 있어 추적하지 않는다
    if os.environ.get("AUTOPOSTER_PRINT_URL"):
        print(url, flush=True)
    log(f"앱 시작: {url.split('?')[0]}")
    started = time.time()
    reason = "중단"
    try:
        while True:
            time.sleep(0.5)
            now = time.time()
            if app.clients > 0:
                continue
            if not app.ever_connected and now - started > STARTUP_TIMEOUT:
                reason = "앱 창이 연결되지 않음"
                break
            if app.ever_connected and now - app.last_disconnect > CLOSE_GRACE:
                reason = "앱 창이 닫힘"
                break
    except KeyboardInterrupt:
        pass
    finally:
        log(f"앱 종료: {reason}")
        app.stopping = True
        server.shutdown()
        app.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # 콘솔 없이 실행되므로 오류를 파일에 남긴다
        log_error(exc)
        raise
