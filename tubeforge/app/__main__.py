"""TubeForge 앱 실행: python -m app

로컬 서버를 켜고 Edge(없으면 크롬)를 주소창 없는 앱 창으로 띄운다.
창을 닫으면(화면이 1분 넘게 응답하지 않으면) 서버도 꺼진다. 렌더링 중이면 끝날 때까지 기다린다.
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.server import App, create_server  # noqa: E402
from modules.config import ROOT  # noqa: E402

IDLE_EXIT = 60  # 창이 이 시간 동안 연락이 없으면 종료
STARTUP_TIMEOUT = 180


def find_app_browser() -> str | None:
    candidates = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                candidates += [Path(base) / "Microsoft/Edge/Application/msedge.exe",
                               Path(base) / "Google/Chrome/Application/chrome.exe"]
    elif sys.platform == "darwin":
        candidates += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                       Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
    else:
        candidates += [shutil.which(n) for n in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser")]
    return next((str(c) for c in candidates if c and Path(c).exists()), None)


def open_window(url: str) -> None:
    exe = find_app_browser()
    if not exe:
        webbrowser.open(url)
        return
    profile = Path.home() / ".tubeforge" / "app-window"
    args = [exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1400,900",
            "--no-first-run", "--no-default-browser-check", "--disable-features=Translate", "--autoplay-policy=no-user-gesture-required"]
    subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))  # noqa: S603


def main() -> int:
    app = App()
    port = int(os.environ.get("TUBEFORGE_PORT", "0"))
    server = create_server(app, port)
    url = f"http://127.0.0.1:{server.server_port}/?t={app.token}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"TubeForge 실행 중: {url}", flush=True)
    print("이 검은 창은 앱이 켜져 있는 동안 그대로 두세요. 앱 창을 닫으면 함께 꺼집니다.", flush=True)
    if not os.environ.get("TUBEFORGE_NO_WINDOW"):
        open_window(url)
    started = time.time()
    try:
        while True:
            time.sleep(1)
            busy = any(j.status in ("queued", "running") for j in app.jobs.values())
            if busy:
                continue
            if app.last_ping == 0 and time.time() - started > STARTUP_TIMEOUT and not os.environ.get("TUBEFORGE_NO_WINDOW"):
                print("앱 창이 연결되지 않아 종료합니다. 위 주소를 브라우저에 직접 붙여 넣어도 됩니다.")
                break
            if app.last_ping and time.time() - app.last_ping > IDLE_EXIT:
                print("앱 창이 닫혀 종료합니다.")
                break
    except KeyboardInterrupt:
        pass
    server.shutdown()
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    raise SystemExit(main())
